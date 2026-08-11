import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Account,
    ApiKey,
    Household,
    HouseholdInvite,
    HouseholdMember,
    HouseholdRole,
    Transaction,
    User,
    UserProfile,
)
from app.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyResponse,
    HouseholdMemberResponse,
    InviteRequest,
    InviteResponse,
    InviteSummary,
    InviteTokenRequest,
    LedgerResponse,
    LedgerSwitch,
    SandboxCreate,
    SandboxRename,
)
from app.security import (
    AuthContext,
    current_auth,
    new_api_key,
    new_token,
    switch_session_household,
    token_hash,
)
from app.services import sandbox
from app.services.invites import load_open_invite
from app.services.profiles import avatar_url
from app.services.security_audit import identifier_fingerprint, record_security_event

router = APIRouter(prefix="/households", tags=["households"])


def _safe_csv_cell(value: str) -> str:
    """Keep spreadsheet applications from executing exported text as a formula."""
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


@router.get("/members", response_model=list[HouseholdMemberResponse])
async def list_members(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(HouseholdMember, User, UserProfile)
        .join(User, HouseholdMember.user_id == User.id)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .where(HouseholdMember.household_id == auth.household_id)
        .order_by(HouseholdMember.joined_at.asc())
    )
    return [
        HouseholdMemberResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=membership.role,
            joined_at=membership.joined_at,
            avatar_url=avatar_url(user.id, profile) if profile else None,
        )
        for membership, user, profile in rows
    ]


@router.get("/export")
async def export_household(
    request: Request,
    format: Literal["csv", "json"] = "csv",
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    accounts = (
        await db.scalars(
            select(Account)
            .where(Account.household_id == auth.household_id)
            .order_by(Account.name.asc())
        )
    ).all()
    transactions = (
        await db.scalars(
            select(Transaction)
            .where(Transaction.household_id == auth.household_id)
            .order_by(Transaction.posted_date.desc())
        )
    ).all()
    account_names = {account.id: account.name for account in accounts}
    stamp = datetime.now(timezone.utc).date().isoformat()
    await record_security_event(
        db,
        "household.export",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "format": format,
            "accounts": len(accounts),
            "transactions": len(transactions),
        },
    )
    await db.commit()

    if format == "json":
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "accounts": [
                {
                    "id": str(account.id),
                    "name": account.name,
                    "institution_name": account.institution_name,
                    "type": account.type.value,
                    "kind": account.kind.value,
                    "current_balance": str(account.current_balance),
                    "is_on_budget": account.is_on_budget,
                    "is_hidden": account.is_hidden,
                }
                for account in accounts
            ],
            "transactions": [
                {
                    "id": str(transaction.id),
                    "account_id": str(transaction.account_id),
                    "account_name": account_names.get(transaction.account_id),
                    "posted_date": transaction.posted_date.isoformat(),
                    "merchant": transaction.merchant_name
                    or transaction.original_description,
                    "amount": str(transaction.amount),
                    "category_id": (
                        str(transaction.category_id)
                        if transaction.category_id
                        else None
                    ),
                    "notes": transaction.notes,
                    "reviewed": transaction.reviewed,
                }
                for transaction in transactions
            ],
        }
        body = json.dumps(payload, indent=2).encode()
        return StreamingResponse(
            iter([body]),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="raven-ledger-{stamp}.json"'
                )
            },
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "date",
            "merchant",
            "amount",
            "account",
            "category_id",
            "notes",
            "reviewed",
        ]
    )
    for transaction in transactions:
        writer.writerow(
            [
                transaction.posted_date.isoformat(),
                _safe_csv_cell(
                    transaction.merchant_name or transaction.original_description
                ),
                str(transaction.amount),
                _safe_csv_cell(account_names.get(transaction.account_id, "")),
                str(transaction.category_id) if transaction.category_id else "",
                _safe_csv_cell(transaction.notes or ""),
                transaction.reviewed,
            ]
        )
    return StreamingResponse(
        iter([output.getvalue().encode()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (f'attachment; filename="raven-ledger-{stamp}.csv"')
        },
    )


@router.post("/invites", response_model=InviteResponse)
async def create_invite(
    payload: InviteRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if auth.role != HouseholdRole.owner.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    invited_email = str(payload.email).lower()
    existing_member = await db.scalar(
        select(HouseholdMember.id)
        .join(User, User.id == HouseholdMember.user_id)
        .where(
            HouseholdMember.household_id == auth.household_id,
            User.email == invited_email,
        )
    )
    if existing_member:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That person is already a member of this household.",
        )

    # Reissuing an invitation is rotation, not duplication: only the newest
    # capability for this address remains valid.
    replaced = await db.execute(
        delete(HouseholdInvite).where(
            HouseholdInvite.household_id == auth.household_id,
            HouseholdInvite.invited_email == invited_email,
            HouseholdInvite.accepted_at.is_(None),
        )
    )
    token = new_token()
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    invite = HouseholdInvite(
        household_id=auth.household_id,
        invited_email=invited_email,
        token_hash=token_hash(token),
        role=payload.role,
        expires_at=expires,
    )
    db.add(invite)
    await record_security_event(
        db,
        "household.invite_created",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "invite": identifier_fingerprint(str(payload.email)),
            "role": payload.role.value,
            "replaced": replaced.rowcount or 0,
        },
    )
    await db.commit()
    return InviteResponse(invite_token=token, expires_at=expires)


@router.get("/invites", response_model=list[InviteSummary])
async def list_pending_invites(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if auth.role != HouseholdRole.owner.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    return (
        await db.scalars(
            select(HouseholdInvite)
            .where(
                HouseholdInvite.household_id == auth.household_id,
                HouseholdInvite.accepted_at.is_(None),
            )
            .order_by(HouseholdInvite.created_at.desc())
            .limit(50)
        )
    ).all()


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if auth.role != HouseholdRole.owner.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
    invite = await db.scalar(
        select(HouseholdInvite).where(
            HouseholdInvite.id == invite_id,
            HouseholdInvite.household_id == auth.household_id,
            HouseholdInvite.accepted_at.is_(None),
        )
    )
    if not invite:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such pending invitation")
    fingerprint = identifier_fingerprint(invite.invited_email)
    await db.delete(invite)
    await record_security_event(
        db,
        "household.invite_revoked",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"invite": fingerprint, "role": invite.role.value},
    )
    await db.commit()


async def _accept_invite(
    token: str,
    request: Request,
    auth: AuthContext,
    db: AsyncSession,
) -> None:
    invite = await load_open_invite(db, token, email=auth.user.email, lock=True)
    existing = await db.scalar(
        select(HouseholdMember).where(
            HouseholdMember.household_id == invite.household_id,
            HouseholdMember.user_id == auth.user.id,
        )
    )
    if not existing:
        db.add(
            HouseholdMember(
                household_id=invite.household_id,
                user_id=auth.user.id,
                role=invite.role,
            )
        )
    invite.accepted_at = datetime.now(timezone.utc)
    await record_security_event(
        db,
        "household.invite_accepted",
        request=request,
        household_id=invite.household_id,
        user_id=auth.user.id,
        details={"role": invite.role.value},
    )
    await db.commit()


@router.post("/invites/accept", status_code=204)
async def accept_invite(
    payload: InviteTokenRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Accept an invitation whose secret arrived in the request body."""
    await _accept_invite(payload.token, request, auth, db)


@router.post("/invites/{token}/accept", status_code=204, deprecated=True)
async def accept_invite_legacy(
    token: str,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Compatibility for invitation links created before fragment links."""
    await _accept_invite(token, request, auth, db)


@router.get("/ledgers", response_model=list[LedgerResponse])
async def list_ledgers(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Every ledger this person can open — the real one first, then sandboxes."""
    return [
        LedgerResponse(**row) for row in await sandbox.list_ledgers(db, auth.user.id)
    ]


@router.post("/sandboxes", response_model=LedgerResponse, status_code=201)
async def create_sandbox(
    payload: SandboxCreate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Copy this ledger into a disposable one.

    The copy holds no bank connection, so it can never sync and never touch a
    real account. Its balances are a snapshot of this moment.
    """
    if auth.role != HouseholdRole.owner.value:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the household owner can copy the ledger",
        )
    try:
        created = await sandbox.create_sandbox(
            db, auth.household_id, auth.user.id, payload.name
        )
    except sandbox.SandboxError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return LedgerResponse(
        id=created.id,
        name=created.name,
        role="owner",
        is_sandbox=True,
        cloned_from_id=created.cloned_from_id,
        cloned_at=created.cloned_at,
    )


@router.post("/switch", status_code=204)
async def switch_ledger(
    payload: LedgerSwitch,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Move this session to another ledger the person belongs to."""
    membership = await db.scalar(
        select(HouseholdMember).where(
            HouseholdMember.household_id == payload.household_id,
            HouseholdMember.user_id == auth.user.id,
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ledger not found")
    await switch_session_household(
        auth.session_id, payload.household_id, membership.role.value
    )


@router.patch("/sandboxes/{household_id}", response_model=LedgerResponse)
async def rename_sandbox(
    household_id: uuid.UUID,
    payload: SandboxRename,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Name a sandbox for what you are trying out in it."""
    try:
        renamed = await sandbox.rename_sandbox(
            db, household_id, auth.user.id, payload.name
        )
    except sandbox.SandboxError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return LedgerResponse(
        id=renamed.id,
        name=renamed.name,
        role="owner",
        is_sandbox=True,
        cloned_from_id=renamed.cloned_from_id,
        cloned_at=renamed.cloned_at,
    )


@router.delete("/sandboxes/{household_id}", status_code=204)
async def destroy_sandbox(
    household_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Throw a sandbox away. Refuses anything that is not one.

    If the session is standing in the sandbox being deleted, it is moved back
    to a real ledger first — otherwise the next request would authenticate
    against a household that no longer exists.
    """
    try:
        if auth.household_id == household_id:
            home = await db.scalar(
                select(HouseholdMember)
                .join(Household, Household.id == HouseholdMember.household_id)
                .where(
                    HouseholdMember.user_id == auth.user.id,
                    Household.is_sandbox.is_(False),
                )
            )
            if home is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "There is no real ledger to return to.",
                )
            await switch_session_household(
                auth.session_id, home.household_id, home.role.value
            )
        await sandbox.destroy_sandbox(db, household_id, auth.user.id)
    except sandbox.SandboxError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """The keys for this ledger. Secrets are not stored, so none is returned."""
    _require_key_manager(auth)
    rows = (
        await db.scalars(
            select(ApiKey)
            .where(ApiKey.household_id == auth.household_id)
            .order_by(ApiKey.created_at.desc())
        )
    ).all()
    return [
        ApiKeyResponse(
            id=row.id,
            name=row.name,
            prefix=row.prefix,
            can_write=row.can_write,
            last_used_at=row.last_used_at,
            revoked_at=row.revoked_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    payload: ApiKeyCreate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Mint a key for one tool.

    The secret comes back exactly once. Only its hash is stored, so it cannot
    be shown again and a copy of the database yields nothing usable.
    """
    _require_key_manager(auth)
    secret, hashed, prefix = new_api_key()
    record = ApiKey(
        household_id=auth.household_id,
        created_by_user_id=auth.user.id,
        name=payload.name,
        token_hash=hashed,
        prefix=prefix,
        can_write=payload.can_write,
    )
    db.add(record)
    await record_security_event(
        db,
        "api_key.created",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "name": payload.name,
            "prefix": prefix,
            "can_write": payload.can_write,
        },
    )
    await db.commit()
    await db.refresh(record)
    return ApiKeyCreated(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        can_write=record.can_write,
        last_used_at=None,
        revoked_at=None,
        created_at=record.created_at,
        secret=secret,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Revoke immediately. Revocation is a flag, so it survives being reused."""
    _require_key_manager(auth)
    record = await db.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.household_id == auth.household_id
        )
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    record.revoked_at = datetime.now(timezone.utc)
    await record_security_event(
        db,
        "api_key.revoked",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"name": record.name, "prefix": record.prefix},
    )
    await db.commit()


def _require_key_manager(auth: AuthContext) -> None:
    """
    Only an owner, and never a key itself.

    A key that could mint more keys would make revocation meaningless — the
    tool could simply issue itself a replacement.
    """
    if auth.via_api_key:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "API keys cannot manage other API keys.",
        )
    if auth.role != HouseholdRole.owner.value:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the household owner can manage API keys",
        )
