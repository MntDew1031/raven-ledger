"""
Putting a bulk action back.

The organizer can change thirty things in one tap, a bulk edit as many, and
running rules more. With no way back, the safe move is to hesitate before
pressing the button — which is exactly the friction those features exist to
remove. An undo is what makes "apply all" a reasonable thing to do.

**How it works, and why it is deliberately dumb.** Every reversible action
writes down each field it touched and the value that field held *before*.
Undoing sets those values back. There is no attempt to work out an inverse
operation, because inverses go wrong in ways that are hard to see: the opposite
of "categorize as Dining" is not "uncategorize", it is "restore whatever was
there, which might have been Groceries, or nothing".

Three rules:

- **A whole action, or none of it.** Approving twenty proposals is one action;
  undoing puts back all twenty.
- **Only the most recent, and only for a while.** An undo that reaches back
  past later edits would silently discard them. Anything older than
  `UNDO_WINDOW_HOURS` is history rather than a mistake.
- **A row edited since is skipped, not overwritten.** If somebody has changed a
  transaction by hand since the action, their edit wins and the undo reports
  what it left alone.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, Transaction

# Long enough to cover "I pressed that and then looked at the result", short
# enough that undoing cannot reach back past a week of later work.
UNDO_WINDOW_HOURS = 24

# Fields an undo is allowed to restore. Anything not listed here cannot be
# reversed by this mechanism, which is safer than reflecting over arbitrary
# attribute names taken from stored JSON.
RESTORABLE = frozenset(
    {
        "category_id",
        "categorization_source",
        "is_transfer",
        "excluded_from_budget",
        "reviewed",
        "amount",
        "merchant_name",
        "notes",
    }
)


def record(
    household_id: uuid.UUID,
    user_id: uuid.UUID | None,
    kind: str,
    summary: str,
    changes: list[dict],
) -> ActivityLog:
    """
    Build the log entry for an action.

    `changes` is a list of
    `{"transaction_id": str, "field": str, "before": <json value>}`.
    Written by the caller *before* it applies anything, since afterwards the
    previous values are gone.
    """
    return ActivityLog(
        household_id=household_id,
        user_id=user_id,
        kind=kind,
        summary=summary[:300],
        changes=[
            entry
            for entry in changes
            if entry.get("field") in RESTORABLE and entry.get("transaction_id")
        ],
    )


def capture(transaction: Transaction, fields: list[str]) -> list[dict]:
    """Snapshot the current value of the fields an action is about to change."""
    out: list[dict] = []
    for field in fields:
        if field not in RESTORABLE:
            continue
        value = getattr(transaction, field, None)
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        out.append(
            {
                "transaction_id": str(transaction.id),
                "field": field,
                "before": value,
            }
        )
    return out


async def undoable(
    db: AsyncSession, household_id: uuid.UUID, now: datetime | None = None
) -> ActivityLog | None:
    """
    The most recent action that can still be put back.

    Only the latest: undoing something older would silently discard everything
    done after it.
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(hours=UNDO_WINDOW_HOURS)
    return await db.scalar(
        select(ActivityLog)
        .where(
            ActivityLog.household_id == household_id,
            ActivityLog.undone_at.is_(None),
            ActivityLog.created_at >= cutoff,
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(1)
    )


async def apply_undo(
    db: AsyncSession, entry: ActivityLog
) -> dict[str, int]:
    """
    Put the recorded values back.

    A transaction edited by hand since the action is left alone: their change
    is newer and more deliberate than the one being reversed.
    """
    ids = {
        uuid.UUID(change["transaction_id"])
        for change in entry.changes
        if change.get("transaction_id")
    }
    rows = {
        item.id: item
        for item in (
            await db.scalars(
                select(Transaction).where(
                    Transaction.id.in_(ids),
                    Transaction.household_id == entry.household_id,
                )
            )
        ).all()
    }

    restored, skipped = 0, 0
    for change in entry.changes:
        field = change.get("field")
        if field not in RESTORABLE:
            skipped += 1
            continue
        transaction = rows.get(uuid.UUID(change["transaction_id"]))
        if transaction is None:
            # Deleted since. Nothing to put back.
            skipped += 1
            continue
        if transaction.updated_at and transaction.updated_at > entry.created_at:
            # Touched by a person after the action. Their edit is newer and
            # more deliberate than the one being reversed.
            skipped += 1
            continue
        value = change.get("before")
        if field in {"category_id"} and value is not None:
            value = uuid.UUID(value)
        setattr(transaction, field, value)
        restored += 1

    entry.undone_at = datetime.now(timezone.utc)
    return {"restored": restored, "skipped": skipped}
