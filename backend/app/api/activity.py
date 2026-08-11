"""Undo for the last bulk action."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import HouseholdRole
from app.security import AuthContext, current_auth
from app.services import undo

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/undoable")
async def read_undoable(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    The most recent action that can still be put back, if there is one.

    Only the latest: undoing something older would silently discard everything
    done after it.
    """
    entry = await undo.undoable(db, auth.household_id)
    if entry is None:
        return {"available": False}
    return {
        "available": True,
        "id": str(entry.id),
        "kind": entry.kind,
        "summary": entry.summary,
        "created_at": entry.created_at,
        "affects": len({change["transaction_id"] for change in entry.changes}),
    }


@router.post("/undo")
async def undo_last(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if auth.role == HouseholdRole.viewer.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers cannot undo")
    entry = await undo.undoable(db, auth.household_id)
    if entry is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "There is nothing recent enough to undo.",
        )
    result = await undo.apply_undo(db, entry)
    await db.commit()
    return {"summary": entry.summary, **result}
