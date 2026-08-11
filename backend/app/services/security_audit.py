import hashlib
import uuid
from collections.abc import Mapping

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SecurityEvent
from app.security import client_ip

MAX_DETAIL_ITEMS = 20
MAX_DETAIL_TEXT = 240


def identifier_fingerprint(value: str) -> str:
    """Correlate failed identifiers without storing an email address."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:16]


def _safe_details(details: Mapping[str, object] | None) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in list((details or {}).items())[:MAX_DETAIL_ITEMS]:
        clean_key = str(key)[:80]
        if value is None or isinstance(value, (bool, int, float)):
            safe[clean_key] = value
        else:
            safe[clean_key] = str(value)[:MAX_DETAIL_TEXT]
    return safe


async def record_security_event(
    db: AsyncSession,
    event_type: str,
    *,
    request: Request | None = None,
    household_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    success: bool = True,
    details: Mapping[str, object] | None = None,
) -> SecurityEvent:
    event = SecurityEvent(
        household_id=household_id,
        user_id=user_id,
        event_type=event_type[:80],
        success=success,
        ip_address=client_ip(request) if request else None,
        user_agent=(request.headers.get("user-agent") or "Unknown device")[:240]
        if request
        else None,
        details=_safe_details(details),
    )
    db.add(event)
    await db.flush()
    return event
