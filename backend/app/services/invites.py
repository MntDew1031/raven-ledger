from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HouseholdInvite
from app.security import token_hash


def validate_invite(
    invite: HouseholdInvite | None,
    *,
    email: str | None = None,
    now: datetime | None = None,
) -> HouseholdInvite:
    """Fail closed on missing, used, expired, or misaddressed invitations."""
    moment = now or datetime.now(timezone.utc)
    if (
        invite is None
        or invite.accepted_at is not None
        or invite.expires_at < moment
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Invitation is invalid or expired"
        )
    if email is not None and invite.invited_email != email.lower():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This invitation was sent to a different email address",
        )
    return invite


async def load_open_invite(
    db: AsyncSession,
    token: str,
    *,
    email: str | None = None,
    lock: bool = False,
) -> HouseholdInvite:
    """Look an invitation up by its secret token and verify it is usable."""
    query = select(HouseholdInvite).where(
        HouseholdInvite.token_hash == token_hash(token),
        HouseholdInvite.accepted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    return validate_invite(await db.scalar(query), email=email)
