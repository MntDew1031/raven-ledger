import base64
import hashlib
import hmac
import ipaddress
import secrets
import struct
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from fastapi import Cookie, Depends, HTTPException, Request, status
from pwdlib import PasswordHash
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import HouseholdMember, User

settings = get_settings()
password_hash = PasswordHash.recommended()
redis = Redis.from_url(settings.redis_url, decode_responses=True)
SESSION_COOKIE = (
    "__Host-raven_session" if settings.environment == "production" else "raven_session"
)


# Anything that is not a read. Kept here rather than at each route because one
# forgotten decorator would be a silent write hole for a read-only key.
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
API_KEY_PREFIX = "rvn"


@dataclass(frozen=True)
class AuthContext:
    user: User
    household_id: uuid.UUID
    role: str
    session_id: str
    # True when the caller is a tool holding an API key rather than a person at
    # a browser. Sensitive, person-only operations refuse these outright.
    via_api_key: bool = False
    api_key_can_write: bool = False
    api_key_name: str | None = None


OPERATOR_CONFIRM_KEY = "raven:operator-confirm:{session}"
# Long enough to click through a confirmation, short enough that a stolen
# session is not also a standing licence to export the whole database.
OPERATOR_CONFIRM_TTL_SECONDS = 5 * 60
MFA_SETUP_KEY = "raven:mfa-setup:{session}"
MFA_SETUP_TTL_SECONDS = 10 * 60


def operator_emails() -> frozenset[str]:
    return frozenset(
        item.strip().lower()
        for item in (settings.operator_emails or "").split(",")
        if item.strip()
    )


def is_operator(user: User) -> bool:
    """
    Whether this person runs the server, as distinct from owning a household.

    Deliberately not a database column and not a household role: both would be
    grantable from inside the application, and the whole point is that no
    invitation, role change, or compromised household owner can confer it.
    """
    configured = operator_emails()
    return bool(configured) and (user.email or "").lower() in configured


async def grant_operator_confirmation(session_id: str) -> None:
    await redis.set(
        OPERATOR_CONFIRM_KEY.format(session=session_id),
        "1",
        ex=OPERATOR_CONFIRM_TTL_SECONDS,
    )


async def has_operator_confirmation(session_id: str) -> bool:
    return bool(await redis.get(OPERATOR_CONFIRM_KEY.format(session=session_id)))


async def revoke_operator_confirmation(session_id: str) -> None:
    await redis.delete(OPERATOR_CONFIRM_KEY.format(session=session_id))


def new_api_key() -> tuple[str, str, str]:
    """
    Mint a key: the secret to show once, its hash to store, and a prefix.

    The prefix is kept so a person can tell two keys apart in a list. It is
    short enough to be useless on its own — the entropy lives in the rest.
    """
    secret = f"{API_KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    return secret, token_hash(secret), secret[: len(API_KEY_PREFIX) + 7]


def bearer_token(request: Request) -> str | None:
    """
    Pull a key out of the request.

    `Authorization: Bearer …` is what every client already knows how to send;
    `X-Raven-Key` exists because some tools reserve the Authorization header
    for their own use.
    """
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        candidate = header[7:].strip()
        if candidate:
            return candidate
    return request.headers.get("x-raven-key") or None


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hash.verify(password, hashed)
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_mfa_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _decode_mfa_secret(secret: str) -> bytes:
    normalized = secret.strip().replace(" ", "").upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    return base64.b32decode(normalized + padding, casefold=True)


def totp_code(secret: str, at: int | None = None) -> str:
    counter = int((time.time() if at is None else at) // 30)
    digest = hmac.new(
        _decode_mfa_secret(secret),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_totp(secret: str, code: str, at: int | None = None) -> bool:
    candidate = code.strip().replace(" ", "")
    if len(candidate) != 6 or not candidate.isdigit():
        return False
    now = int(time.time() if at is None else at)
    return any(
        hmac.compare_digest(totp_code(secret, now + offset * 30), candidate)
        for offset in (-1, 0, 1)
    )


def generate_recovery_codes(count: int = 8) -> list[str]:
    return [
        "-".join(
            secrets.token_hex(8).upper()[index : index + 4] for index in range(0, 16, 4)
        )
        for _ in range(count)
    ]


def recovery_code_hash(code: str) -> str:
    normalized = code.replace("-", "").replace(" ", "").upper()
    return hmac.new(
        settings.secret_key.encode(), normalized.encode(), hashlib.sha256
    ).hexdigest()


def verify_user_mfa(user: User, code: str) -> tuple[bool, bool]:
    """Return (accepted, recovery_code_consumed), mutating recovery state."""
    if not user.mfa_enabled_at or not user.mfa_secret_encrypted:
        return True, False
    try:
        secret = decrypt_secret(user.mfa_secret_encrypted)
    except Exception:
        return False, False
    if verify_totp(secret, code):
        return True, False

    candidate = recovery_code_hash(code)
    remaining = list(user.mfa_recovery_codes or [])
    for index, stored in enumerate(remaining):
        if hmac.compare_digest(stored, candidate):
            remaining.pop(index)
            user.mfa_recovery_codes = remaining
            return True, True
    return False, False


async def store_pending_mfa_setup(session_id: str, secret: str) -> None:
    await redis.set(
        MFA_SETUP_KEY.format(session=session_id),
        encrypt_secret(secret),
        ex=MFA_SETUP_TTL_SECONDS,
    )


async def pending_mfa_setup(session_id: str) -> str | None:
    value = await redis.get(MFA_SETUP_KEY.format(session=session_id))
    if not value:
        return None
    try:
        return decrypt_secret(value)
    except Exception:
        await redis.delete(MFA_SETUP_KEY.format(session=session_id))
        return None


async def clear_pending_mfa_setup(session_id: str) -> None:
    await redis.delete(MFA_SETUP_KEY.format(session=session_id))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def fernet_key() -> bytes:
    """
    The key actually used to encrypt provider tokens, derived when one is not
    configured. Exposed so backups can fingerprint it: a database restored
    under a different key decrypts to nothing, and that is worth catching
    before the next sync rather than during it.
    """
    if settings.encryption_key:
        return settings.encryption_key.encode()
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(fernet_key())


def verify_encryption_key() -> None:
    """
    Fail at startup rather than inside a background job. A malformed
    ENCRYPTION_KEY otherwise only surfaces when a provider token is decrypted,
    which happens in the worker, where nobody is watching.
    """
    try:
        _fernet()
    except Exception as exc:  # noqa: BLE001 - any failure here is fatal config
        configured = settings.encryption_key or ""
        raise RuntimeError(
            "ENCRYPTION_KEY is not a valid Fernet key "
            f"(got {len(configured)} characters; a valid key is 44 characters "
            "of url-safe base64 ending in '='). Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"` and set the identical '
            "value on the backend and the worker."
        ) from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


async def create_session(
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    role: str,
    user_agent: str = "Unknown device",
) -> str:
    token = new_token()
    session_id = token_hash(token)
    key = f"session:{session_id}"
    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(
        key,
        mapping={
            "user_id": str(user_id),
            "household_id": str(household_id),
            "role": role,
            "created_at": now,
            "last_seen_at": now,
            "user_agent": user_agent[:240] or "Unknown device",
        },
    )
    await redis.expire(key, settings.session_ttl_seconds)
    index_key = f"user_sessions:{user_id}"
    await redis.sadd(index_key, session_id)
    await redis.expire(index_key, settings.session_ttl_seconds)
    return token


async def switch_session_household(
    session_id: str, household_id: uuid.UUID, role: str
) -> None:
    """
    Point an existing session at a different ledger.

    Switching is a pointer move rather than a new sign-in, so it is instant and
    costs nothing to undo — which is the whole appeal of a sandbox you can step
    into and back out of.
    """
    await redis.hset(
        f"session:{session_id}",
        mapping={"household_id": str(household_id), "role": role},
    )


async def destroy_session(token: str | None) -> None:
    if token:
        session_id = token_hash(token)
        key = f"session:{session_id}"
        data = await redis.hgetall(key)
        await redis.delete(key)
        if data.get("user_id"):
            await redis.srem(f"user_sessions:{data['user_id']}", session_id)


async def revoke_session(user_id: uuid.UUID, session_id: str) -> bool:
    index_key = f"user_sessions:{user_id}"
    if not await redis.sismember(index_key, session_id):
        return False
    await redis.delete(f"session:{session_id}")
    await redis.srem(index_key, session_id)
    return True


async def revoke_other_sessions(user_id: uuid.UUID, current_session_id: str) -> int:
    index_key = f"user_sessions:{user_id}"
    session_ids = await redis.smembers(index_key)
    removed = 0
    for session_id in session_ids:
        if session_id == current_session_id:
            continue
        await redis.delete(f"session:{session_id}")
        await redis.srem(index_key, session_id)
        removed += 1
    return removed


async def user_sessions(user_id: uuid.UUID) -> list[dict[str, str]]:
    index_key = f"user_sessions:{user_id}"
    session_ids = await redis.smembers(index_key)
    sessions: list[dict[str, str]] = []
    for session_id in session_ids:
        data = await redis.hgetall(f"session:{session_id}")
        if not data:
            await redis.srem(index_key, session_id)
            continue
        sessions.append({"id": session_id, **data})
    return sessions


def rate_limit_key(bucket: str, identifier: str) -> str:
    digest = hashlib.sha256(
        f"{settings.secret_key}:{identifier.lower()}".encode()
    ).hexdigest()
    return f"rate:{bucket}:{digest}"


def client_ip(request: Request) -> str:
    """Resolve a visitor address without trusting arbitrary forwarded headers."""
    peer = request.client.host if request.client else "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer

    trusted = []
    for raw in settings.trusted_proxy_cidrs.split(","):
        candidate = raw.strip()
        if not candidate:
            continue
        try:
            trusted.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            continue
    if not any(peer_ip in network for network in trusted):
        return peer_ip.compressed

    # Cloudflare overwrites CF-Connecting-IP at its edge. X-Forwarded-For is
    # the fallback for direct reverse proxies; the first address is the
    # original client in the topology Raven supports.
    forwarded = request.headers.get("cf-connecting-ip")
    if not forwarded:
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0]
    try:
        return ipaddress.ip_address(forwarded.strip()).compressed
    except ValueError:
        return peer_ip.compressed


async def enforce_rate_limit(
    bucket: str,
    identifier: str,
    *,
    limit: int,
    window_seconds: int,
) -> str:
    key = rate_limit_key(bucket, identifier)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    if count > limit:
        ttl = max(await redis.ttl(key), 1)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Please wait and try again.",
            headers={"Retry-After": str(ttl)},
        )
    return key


async def clear_rate_limit(key: str) -> None:
    await redis.delete(key)


async def _auth_from_api_key(request: Request, db: AsyncSession) -> AuthContext | None:
    """
    Resolve an API key, or return None so cookie handling can report the error.

    The scope check lives here rather than at each route: a read-only key is
    refused on any non-read method centrally, so no future endpoint can forget
    to ask.
    """
    from app.models import ApiKey

    presented = bearer_token(request)
    if not presented:
        return None

    record = await db.scalar(
        select(ApiKey).where(ApiKey.token_hash == token_hash(presented))
    )
    now = datetime.now(timezone.utc)
    if record is None or record.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key is not valid")
    if record.expires_at is not None and record.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key has expired")

    if request.method not in READ_METHODS and not record.can_write:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"The key '{record.name}' can read your ledger but not change it.",
        )

    user = await db.get(User, record.created_by_user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key owner disabled")
    membership = await db.scalar(
        select(HouseholdMember).where(
            HouseholdMember.household_id == record.household_id,
            HouseholdMember.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key is not valid")

    # Best effort: a failed timestamp must never cost somebody their request.
    try:
        record.last_used_at = now
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()

    return AuthContext(
        user=user,
        household_id=record.household_id,
        role=membership.role.value,
        session_id=f"apikey:{record.id}",
        via_api_key=True,
        api_key_can_write=record.can_write,
        api_key_name=record.name,
    )


async def current_auth(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if not session_token:
        # No cookie: this may be a tool holding an API key rather than a
        # browser. Falling through here is what makes the same routes serve
        # both, with the scope check below deciding what a key may do.
        key_auth = await _auth_from_api_key(request, db)
        if key_auth is not None:
            return key_auth
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    session_id = token_hash(session_token)
    data = await redis.hgetall(f"session:{session_id}")
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    try:
        user_id = uuid.UUID(data["user_id"])
        household_id = uuid.UUID(data["household_id"])
    except (KeyError, ValueError):
        await destroy_session(session_token)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalid")

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User disabled")

    membership = await db.scalar(
        select(HouseholdMember).where(
            HouseholdMember.user_id == user.id,
            HouseholdMember.household_id == household_id,
        )
    )
    if not membership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Household access revoked")

    now = datetime.now(timezone.utc)
    if not data.get("created_at"):
        data["created_at"] = now.isoformat()
        data["last_seen_at"] = now.isoformat()
        data["user_agent"] = request.headers.get("user-agent", "Unknown device")[:240]
        await redis.hset(
            f"session:{session_id}",
            mapping={
                "created_at": data["created_at"],
                "last_seen_at": data["last_seen_at"],
                "user_agent": data["user_agent"],
            },
        )
    index_key = f"user_sessions:{user.id}"
    await redis.sadd(index_key, session_id)
    await redis.expire(index_key, settings.session_ttl_seconds)

    last_seen_raw = data.get("last_seen_at")
    try:
        last_seen = datetime.fromisoformat(last_seen_raw) if last_seen_raw else None
    except ValueError:
        last_seen = None
    if not last_seen or now - last_seen > timedelta(minutes=5):
        await redis.hset(f"session:{session_id}", "last_seen_at", now.isoformat())

    return AuthContext(
        user=user,
        household_id=membership.household_id,
        role=membership.role.value,
        session_id=session_id,
    )
