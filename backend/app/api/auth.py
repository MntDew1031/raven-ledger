from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import (
    Category,
    CategoryGroup,
    FlexBucket,
    Household,
    HouseholdInvite,
    HouseholdMember,
    HouseholdRole,
    User,
)
from app.schemas import (
    InvitePreview,
    InviteTokenRequest,
    LoginRequest,
    RegisterRequest,
    RegistrationStatus,
    SessionResponse,
)
from app.security import (
    SESSION_COOKIE,
    AuthContext,
    clear_rate_limit,
    client_ip,
    create_session,
    current_auth,
    destroy_session,
    enforce_rate_limit,
    hash_password,
    verify_password,
    verify_user_mfa,
)
from app.services.invites import load_open_invite
from app.services.profiles import ensure_profile, user_response
from app.services.security_audit import (
    identifier_fingerprint,
    record_security_event,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


async def _set_cookie(response: Response, token: str) -> None:
    # Remove the pre-hardening cookie after a successful production login.
    if SESSION_COOKIE != "raven_session":
        response.delete_cookie("raven_session", path="/")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


async def _default_categories(db: AsyncSession, household_id) -> None:
    groups = [
        ("Income", True, [("Income", "#4f8062", FlexBucket.fixed)]),
        (
            "Required",
            False,
            [
                ("Housing", "#bd5b51", FlexBucket.fixed),
                ("Utilities", "#c86b5e", FlexBucket.fixed),
                ("Transportation", "#d47768", FlexBucket.fixed),
                ("Debt Payments", "#af4a43", FlexBucket.fixed),
                ("Food & Household", "#c86459", FlexBucket.flex),
            ],
        ),
        (
            "Wants",
            False,
            [
                ("Subscriptions", "#d99049", FlexBucket.flex),
                ("Dining", "#e3a158", FlexBucket.flex),
                ("Fun Money", "#d77f35", FlexBucket.flex),
            ],
        ),
        (
            "Savings",
            False,
            [
                ("Emergency Fund", "#4f8062", FlexBucket.goal),
                ("Non-monthly Expenses", "#699476", FlexBucket.non_monthly),
            ],
        ),
    ]
    for sort_order, (group_name, is_income, categories) in enumerate(groups):
        group = CategoryGroup(
            household_id=household_id,
            name=group_name,
            is_income=is_income,
            sort_order=sort_order,
        )
        db.add(group)
        await db.flush()
        for name, color, bucket in categories:
            db.add(
                Category(
                    household_id=household_id,
                    group_id=group.id,
                    name=name,
                    color=color,
                    flex_bucket=bucket,
                )
            )


async def _registration_status(db: AsyncSession) -> RegistrationStatus:
    """
    Open registration exists only to create the first household. After that,
    joining requires an invitation unless an operator deliberately reopens it.
    """
    if settings.allow_public_registration:
        return RegistrationStatus(open=True, reason="enabled")
    has_user = await db.scalar(select(select(User.id).exists()))
    if has_user:
        return RegistrationStatus(open=False, reason="closed")
    return RegistrationStatus(open=True, reason="bootstrap")


@router.get("/registration", response_model=RegistrationStatus)
async def registration_status(db: AsyncSession = Depends(get_db)):
    return await _registration_status(db)


async def _preview_invite(
    token: str,
    request: Request,
    db: AsyncSession,
) -> InvitePreview:
    await enforce_rate_limit(
        "invite-preview",
        client_ip(request),
        limit=30,
        window_seconds=15 * 60,
    )
    invite = await load_open_invite(db, token)
    household = await db.get(Household, invite.household_id)
    if not household:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Invitation is invalid or expired"
        )
    return InvitePreview(
        household_name=household.name,
        invited_email=invite.invited_email,
        role=invite.role,
        expires_at=invite.expires_at,
    )


@router.post("/invites/preview", response_model=InvitePreview)
async def preview_invite(
    payload: InviteTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Preview an invitation without putting its capability in access logs."""
    return await _preview_invite(payload.token, request, db)


@router.get("/invites/{token}", response_model=InvitePreview, deprecated=True)
async def preview_invite_legacy(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Compatibility for invitation links created before fragment links."""
    return await _preview_invite(token, request, db)


@router.post("/register", response_model=SessionResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    await enforce_rate_limit(
        "register",
        client_ip(request),
        limit=5,
        window_seconds=60 * 60,
    )
    email = payload.email.lower()
    invite: HouseholdInvite | None = None

    if payload.invite_token:
        invite = await load_open_invite(
            db, payload.invite_token, email=email, lock=True
        )
        household = await db.get(Household, invite.household_id)
        if not household:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "Invitation is invalid or expired"
            )
        role = invite.role
    elif payload.household_name:
        # Serialize the one-time bootstrap decision. Without this lock, two
        # simultaneous first registrations with different emails can both see
        # an empty users table and create separate owner households.
        await db.execute(text("SELECT pg_advisory_xact_lock(1380013893)"))
        status_now = await _registration_status(db)
        if not status_now.open:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This server is invitation-only. Ask a household owner to "
                "send you an invitation link.",
            )
        household = Household(name=payload.household_name)
        role = HouseholdRole.owner
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A household name or an invitation is required",
        )

    user = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    if invite is None:
        db.add(household)
    try:
        await db.flush()
        membership = HouseholdMember(
            household_id=household.id,
            user_id=user.id,
            role=role,
        )
        db.add(membership)
        if invite is None:
            await _default_categories(db, household.id)
        else:
            invite.accepted_at = datetime.now(timezone.utc)
        profile = await ensure_profile(db, user)
        await record_security_event(
            db,
            "account.registered",
            request=request,
            household_id=household.id,
            user_id=user.id,
            details={"role": role.value, "via_invite": invite is not None},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Email already registered"
        ) from exc

    token = await create_session(
        user.id,
        household.id,
        membership.role.value,
        request.headers.get("user-agent", "Unknown device"),
    )
    await _set_cookie(response, token)
    return SessionResponse(
        user=user_response(user, profile),
        household_id=household.id,
        household_name=household.name,
        role=membership.role,
    )


@router.post("/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    rate_key = await enforce_rate_limit(
        "login",
        f"{client_ip(request)}:{payload.email}",
        limit=10,
        window_seconds=15 * 60,
    )
    user = await db.scalar(
        select(User).where(User.email == payload.email.lower()).with_for_update()
    )
    if (
        not user
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        await record_security_event(
            db,
            "auth.login",
            request=request,
            user_id=user.id if user and user.is_active else None,
            success=False,
            details={
                "identifier": identifier_fingerprint(str(payload.email)),
                "stage": "password",
            },
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    membership = (
        await db.scalars(
            select(HouseholdMember)
            .where(HouseholdMember.user_id == user.id)
            .order_by(HouseholdMember.joined_at.asc())
        )
    ).first()
    if not membership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No household membership")
    household = await db.get(Household, membership.household_id)
    if not household:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Household not found")
    recovery_used = False
    if user.mfa_enabled_at:
        if not payload.mfa_code:
            raise HTTPException(428, "MFA code required")
        accepted, recovery_used = verify_user_mfa(user, payload.mfa_code)
        if not accepted:
            await record_security_event(
                db,
                "auth.login",
                request=request,
                household_id=membership.household_id,
                user_id=user.id,
                success=False,
                details={"stage": "mfa"},
            )
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    profile = await ensure_profile(db, user)
    await record_security_event(
        db,
        "auth.login",
        request=request,
        household_id=membership.household_id,
        user_id=user.id,
        details={"recovery_code_used": recovery_used},
    )
    await db.commit()
    await clear_rate_limit(rate_key)
    token = await create_session(
        user.id,
        membership.household_id,
        membership.role.value,
        request.headers.get("user-agent", "Unknown device"),
    )
    await _set_cookie(response, token)
    return SessionResponse(
        user=user_response(user, profile),
        household_id=membership.household_id,
        household_name=household.name,
        role=membership.role,
    )


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    await destroy_session(session_token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    if SESSION_COOKIE != "raven_session":
        response.delete_cookie("raven_session", path="/")


@router.get("/me", response_model=SessionResponse)
async def me(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    household = await db.get(Household, auth.household_id)
    if not household:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Household not found")
    profile = await ensure_profile(db, auth.user)
    await db.commit()
    return SessionResponse(
        user=user_response(auth.user, profile),
        household_id=auth.household_id,
        household_name=household.name,
        role=auth.role,
    )
