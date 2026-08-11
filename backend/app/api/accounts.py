import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Account, AccountKind, AccountType
from app.schemas import AccountCreate, AccountResponse, AccountUpdate
from app.security import AuthContext, current_auth
from app.services.loans import ensure_payment_category, project
from app.services.net_worth import record_net_worth_snapshot
from app.services.security_audit import record_security_event

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _require_editor(auth: AuthContext) -> None:
    if auth.role == "viewer":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "View-only household members cannot change accounts",
        )


def _normalized_balance(value: Decimal, kind: AccountKind) -> Decimal:
    amount = abs(value)
    return -amount if kind == AccountKind.liability else amount


def _normalized_kind(
    account_type: AccountType,
    kind: AccountKind,
) -> AccountKind:
    if account_type.value in {"credit", "mortgage", "debt"}:
        return AccountKind.liability
    if account_type.value in {"checking", "savings", "investment", "cash"}:
        return AccountKind.asset
    return kind


async def _household_account(
    db: AsyncSession,
    household_id: uuid.UUID,
    account_id: uuid.UUID,
) -> Account:
    account = await db.scalar(
        select(Account).where(
            Account.id == account_id,
            Account.household_id == household_id,
            Account.is_hidden.is_(False),
        )
    )
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return account


@router.get("", response_model=list[AccountResponse])
async def list_accounts(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    return (
        await db.scalars(
            select(Account)
            .where(
                Account.household_id == auth.household_id,
                Account.is_hidden.is_(False),
            )
            .order_by(Account.kind.asc(), Account.name.asc())
        )
    ).all()


# Declared before `/{account_id}`: FastAPI matches in order, and a static
# segment placed after a parameterised one is swallowed by it — "reconcile"
# was being parsed as an account id.
@router.get("/reconcile")
async def reconcile(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Whether each account's transactions add up to its balance.

    Reports only. It never adjusts anything: a reconciliation that silently
    corrects a balance to match its own arithmetic can never find anything
    again.
    """
    from datetime import date as _date

    from app.services.reconcile import check_household

    return await check_household(db, auth.household_id, _date.today())


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    return await _household_account(db, auth.household_id, account_id)


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(
    payload: AccountCreate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    kind = _normalized_kind(payload.type, payload.kind)
    account = Account(
        household_id=auth.household_id,
        name=payload.name,
        type=payload.type,
        kind=kind,
        current_balance=_normalized_balance(payload.current_balance, kind),
        is_on_budget=payload.is_on_budget,
        institution_name=payload.institution_name,
        credit_limit=payload.credit_limit,
        owner_user_id=payload.owner_user_id,
        interest_rate=payload.interest_rate,
        minimum_payment=payload.minimum_payment,
        statement_day=payload.statement_day,
        is_manual=True,
    )
    db.add(account)
    await db.flush()
    # A loan gets its own category with it, so its payments have somewhere to
    # land from the start rather than after somebody notices they do not.
    await ensure_payment_category(db, account)
    await record_net_worth_snapshot(db, auth.household_id)
    await record_security_event(
        db,
        "finance.account_created",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"account_id": account.id, "manual": True},
    )
    await db.commit()
    await db.refresh(account)
    return account


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    account = await _household_account(db, auth.household_id, account_id)
    changed = payload.model_fields_set
    required_fields = {"name", "type", "kind", "current_balance", "is_on_budget"}
    null_required = [
        field
        for field in required_fields.intersection(changed)
        if getattr(payload, field) is None
    ]
    if null_required:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{', '.join(sorted(null_required))} cannot be null",
        )

    if "current_balance" in changed and not account.is_manual:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Plaid manages the balance for this account",
        )

    for field in (
        "name",
        "institution_name",
        "type",
        "is_on_budget",
        "credit_limit",
        "owner_user_id",
        "interest_rate",
        "minimum_payment",
        "statement_day",
        "opening_balance",
    ):
        if field in changed:
            setattr(account, field, getattr(payload, field))

    if "kind" in changed:
        account.kind = payload.kind
    if "type" in changed or "kind" in changed:
        account.kind = _normalized_kind(account.type, account.kind)

    if "current_balance" in changed:
        account.current_balance = _normalized_balance(
            payload.current_balance,
            account.kind,
        )
    elif "kind" in changed or "type" in changed:
        account.current_balance = _normalized_balance(
            account.current_balance,
            account.kind,
        )

    await db.flush()
    await record_net_worth_snapshot(db, auth.household_id)
    await record_security_event(
        db,
        "finance.account_updated",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "account_id": account.id,
            "fields": ",".join(sorted(changed)),
        },
    )
    await db.commit()
    await db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
async def hide_account(
    account_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    account = await _household_account(db, auth.household_id, account_id)
    account.is_hidden = True
    await db.flush()
    await record_net_worth_snapshot(db, auth.household_id)
    await record_security_event(
        db,
        "finance.account_hidden",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"account_id": account.id},
    )
    await db.commit()


@router.get("/{account_id}/debt")
async def debt_projection(
    account_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    What this debt costs each month and when it ends.

    "Never" is reported as its own state rather than as a very large number of
    months — a payment that does not cover the interest is a warning, not a
    schedule.
    """
    from datetime import date as _date

    account = await db.get(Account, account_id)
    if account is None or account.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")
    return project(account, _date.today())
