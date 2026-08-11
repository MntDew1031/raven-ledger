import io
import uuid
import warnings
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import HouseholdMember, SecurityEvent, UserProfile
from app.schemas import (
    MfaDisableRequest,
    MfaEnableRequest,
    MfaEnableResponse,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaStatusResponse,
    PasswordChangeRequest,
    ProfileResponse,
    ProfileUpdate,
    SecurityEventResponse,
    SessionInfoResponse,
)
from app.security import (
    MFA_SETUP_TTL_SECONDS,
    AuthContext,
    clear_pending_mfa_setup,
    client_ip,
    current_auth,
    encrypt_secret,
    enforce_rate_limit,
    generate_mfa_secret,
    generate_recovery_codes,
    hash_password,
    pending_mfa_setup,
    recovery_code_hash,
    revoke_other_sessions,
    revoke_session,
    store_pending_mfa_setup,
    user_sessions,
    verify_password,
    verify_totp,
    verify_user_mfa,
)
from app.services.profiles import ensure_profile, profile_response
from app.services.security_audit import record_security_event

router = APIRouter(prefix="/profile", tags=["profile"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_EDGE = 512
Image.MAX_IMAGE_PIXELS = 25_000_000


def _process_avatar(payload: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as source:
                source.verify()
            with Image.open(io.BytesIO(payload)) as source:
                image = ImageOps.exif_transpose(source)
                image.thumbnail(
                    (MAX_AVATAR_EDGE, MAX_AVATAR_EDGE),
                    Image.Resampling.LANCZOS,
                )
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert(
                        "RGBA" if "transparency" in image.info else "RGB"
                    )
                output = io.BytesIO()
                image.save(
                    output,
                    format="WEBP",
                    quality=86,
                    method=6,
                    exif=b"",
                    icc_profile=b"",
                )
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise ValueError("Upload a valid PNG, JPEG, or WebP image") from exc
    result = output.getvalue()
    if not result or len(result) > MAX_AVATAR_BYTES:
        raise ValueError("The processed profile image is too large")
    return result


@router.get("", response_model=ProfileResponse)
async def get_profile(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    profile = await ensure_profile(db, auth.user)
    await db.commit()
    return profile_response(auth.user, profile)


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    profile = await ensure_profile(db, auth.user)
    changes = payload.model_dump(exclude_unset=True)
    display_name = changes.pop("display_name", None)
    if display_name is not None:
        display_name = display_name.strip()
        if not display_name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Display name cannot be blank",
            )
        auth.user.display_name = display_name
    for field, value in changes.items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(auth.user)
    await db.refresh(profile)
    return profile_response(auth.user, profile)


@router.post("/avatar", response_model=ProfileResponse)
async def upload_avatar(
    avatar: UploadFile = File(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    payload = await avatar.read(MAX_UPLOAD_BYTES + 1)
    await avatar.close()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Profile images must be 5 MB or smaller",
        )
    try:
        processed = await run_in_threadpool(_process_avatar, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    profile = await ensure_profile(db, auth.user)
    profile.avatar_data = processed
    profile.avatar_mime = "image/webp"
    profile.avatar_size = len(processed)
    profile.avatar_revision = str(uuid.uuid4())
    await db.commit()
    await db.refresh(profile)
    return profile_response(auth.user, profile)


@router.delete("/avatar", response_model=ProfileResponse)
async def delete_avatar(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    profile = await ensure_profile(db, auth.user)
    profile.avatar_data = None
    profile.avatar_mime = None
    profile.avatar_size = None
    profile.avatar_revision = None
    await db.commit()
    await db.refresh(profile)
    return profile_response(auth.user, profile)


@router.get("/avatar/{user_id}")
async def get_avatar(
    user_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    allowed = await db.scalar(
        select(HouseholdMember.id).where(
            HouseholdMember.household_id == auth.household_id,
            HouseholdMember.user_id == user_id,
        )
    )
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile image not found")
    row = (
        await db.execute(
            select(
                UserProfile.avatar_data,
                UserProfile.avatar_mime,
                UserProfile.avatar_revision,
            ).where(UserProfile.user_id == user_id)
        )
    ).one_or_none()
    if not row or not row.avatar_data or not row.avatar_mime:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile image not found")
    return Response(
        content=row.avatar_data,
        media_type=row.avatar_mime,
        headers={
            "Cache-Control": "private, max-age=300",
            "ETag": f'"{row.avatar_revision}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/password", status_code=204)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(payload.current_password, auth.user.password_hash):
        await record_security_event(
            db,
            "account.password_change",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Current password is incorrect"
        )
    if verify_password(payload.new_password, auth.user.password_hash):
        await record_security_event(
            db,
            "account.password_change",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            success=False,
            details={"reason": "password_reused"},
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "New password must be different from the current password",
        )
    auth.user.password_hash = hash_password(payload.new_password)
    await record_security_event(
        db,
        "account.password_change",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
    )
    await db.commit()
    await revoke_other_sessions(auth.user.id, auth.session_id)


@router.get("/mfa", response_model=MfaStatusResponse)
async def mfa_status(auth: AuthContext = Depends(current_auth)):
    return MfaStatusResponse(
        enabled=bool(auth.user.mfa_enabled_at),
        enabled_at=auth.user.mfa_enabled_at,
        recovery_codes_remaining=len(auth.user.mfa_recovery_codes or []),
    )


@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def setup_mfa(
    payload: MfaSetupRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if auth.via_api_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A browser session is required")
    await enforce_rate_limit(
        "mfa-setup",
        f"{auth.user.id}:{client_ip(request)}",
        limit=5,
        window_seconds=60 * 60,
    )
    if auth.user.mfa_enabled_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "MFA is already enabled")
    if not verify_password(payload.current_password, auth.user.password_hash):
        await record_security_event(
            db,
            "account.mfa_setup",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            success=False,
            details={"stage": "password"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")

    secret = generate_mfa_secret()
    await store_pending_mfa_setup(auth.session_id, secret)
    issuer = quote("Raven Ledger")
    label = quote(f"Raven Ledger:{auth.user.email}")
    uri = (
        f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"
        "&algorithm=SHA1&digits=6&period=30"
    )
    return MfaSetupResponse(
        secret=secret,
        otpauth_uri=uri,
        expires_in_seconds=MFA_SETUP_TTL_SECONDS,
    )


@router.post("/mfa/enable", response_model=MfaEnableResponse)
async def enable_mfa(
    payload: MfaEnableRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if auth.via_api_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A browser session is required")
    await enforce_rate_limit(
        "mfa-enable",
        f"{auth.user.id}:{client_ip(request)}",
        limit=10,
        window_seconds=15 * 60,
    )
    if auth.user.mfa_enabled_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "MFA is already enabled")
    if not verify_password(payload.current_password, auth.user.password_hash):
        await record_security_event(
            db,
            "account.mfa_enable",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            success=False,
            details={"stage": "password"},
        )
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")
    secret = await pending_mfa_setup(auth.session_id)
    if not secret:
        raise HTTPException(status.HTTP_410_GONE, "MFA setup expired; start again")
    if not verify_totp(secret, payload.code):
        await record_security_event(
            db,
            "account.mfa_enable",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Authenticator code is invalid"
        )

    recovery_codes = generate_recovery_codes()
    auth.user.mfa_secret_encrypted = encrypt_secret(secret)
    auth.user.mfa_enabled_at = datetime.now(timezone.utc)
    auth.user.mfa_recovery_codes = [recovery_code_hash(code) for code in recovery_codes]
    await record_security_event(
        db,
        "account.mfa_enable",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"recovery_codes": len(recovery_codes)},
    )
    await db.commit()
    await clear_pending_mfa_setup(auth.session_id)
    await revoke_other_sessions(auth.user.id, auth.session_id)
    return MfaEnableResponse(recovery_codes=recovery_codes)


@router.delete("/mfa", status_code=204)
async def disable_mfa(
    payload: MfaDisableRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if auth.via_api_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A browser session is required")
    await enforce_rate_limit(
        "mfa-disable",
        f"{auth.user.id}:{client_ip(request)}",
        limit=10,
        window_seconds=15 * 60,
    )
    if not auth.user.mfa_enabled_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "MFA is not enabled")
    password_ok = verify_password(payload.current_password, auth.user.password_hash)
    if not password_ok:
        code_ok, recovery_used = False, False
    else:
        code_ok, recovery_used = verify_user_mfa(auth.user, payload.code)
    if not code_ok:
        await record_security_event(
            db,
            "account.mfa_disable",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Password or MFA code is invalid"
        )

    auth.user.mfa_secret_encrypted = None
    auth.user.mfa_enabled_at = None
    auth.user.mfa_recovery_codes = None
    await record_security_event(
        db,
        "account.mfa_disable",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"recovery_code_used": recovery_used},
    )
    await db.commit()
    await revoke_other_sessions(auth.user.id, auth.session_id)


@router.post("/mfa/recovery-codes", response_model=MfaEnableResponse)
async def rotate_recovery_codes(
    payload: MfaEnableRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if auth.via_api_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A browser session is required")
    await enforce_rate_limit(
        "mfa-recovery-rotate",
        f"{auth.user.id}:{client_ip(request)}",
        limit=10,
        window_seconds=15 * 60,
    )
    if not auth.user.mfa_enabled_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "MFA is not enabled")
    password_ok = verify_password(payload.current_password, auth.user.password_hash)
    code_ok = verify_user_mfa(auth.user, payload.code)[0] if password_ok else False
    if not code_ok:
        await record_security_event(
            db,
            "account.mfa_recovery_codes_rotated",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            success=False,
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Password or MFA code is invalid"
        )
    recovery_codes = generate_recovery_codes()
    auth.user.mfa_recovery_codes = [recovery_code_hash(code) for code in recovery_codes]
    await record_security_event(
        db,
        "account.mfa_recovery_codes_rotated",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"recovery_codes": len(recovery_codes)},
    )
    await db.commit()
    return MfaEnableResponse(recovery_codes=recovery_codes)


@router.get("/security-events", response_model=list[SecurityEventResponse])
async def list_security_events(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    return list(
        await db.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.user_id == auth.user.id)
            .order_by(SecurityEvent.created_at.desc())
            .limit(50)
        )
    )


@router.get("/sessions", response_model=list[SessionInfoResponse])
async def list_sessions(auth: AuthContext = Depends(current_auth)):
    rows = await user_sessions(auth.user.id)
    result: list[SessionInfoResponse] = []
    now = datetime.now(timezone.utc)
    for row in rows:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
            last_seen_at = datetime.fromisoformat(row["last_seen_at"])
        except (KeyError, ValueError):
            created_at = last_seen_at = now
        result.append(
            SessionInfoResponse(
                id=row["id"],
                current=row["id"] == auth.session_id,
                created_at=created_at,
                last_seen_at=last_seen_at,
                user_agent=row.get("user_agent") or "Unknown device",
            )
        )
    return sorted(result, key=lambda item: item.last_seen_at, reverse=True)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if len(session_id) != 64 or any(
        character not in "0123456789abcdef" for character in session_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if session_id == auth.session_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Use sign out to end the current session",
        )
    if not await revoke_session(auth.user.id, session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    await record_security_event(
        db,
        "auth.session_revoked",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"session": session_id[:12]},
    )
    await db.commit()


@router.post("/sessions/revoke-others")
async def delete_other_sessions(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    removed = await revoke_other_sessions(auth.user.id, auth.session_id)
    await record_security_event(
        db,
        "auth.sessions_revoked",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"count": removed},
    )
    await db.commit()
    return {"revoked": removed}
