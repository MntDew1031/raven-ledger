"""
Who spent what.

A household ledger that can only say "we spent $3,400" answers the less
interesting question. Once two people share it, "on what, and by whom" is
usually what somebody actually wants to know — not to keep score, but because
"our Dining is up" and "one of us ate out eleven times" call for different
conversations.

Attribution hangs off the **account**, because that is where it is genuinely
known: a card belongs to somebody and every charge on it is theirs. A
per-transaction override covers the exceptions — a shared card used for
something personal.

`NULL` means shared, and shared is the honest default. A joint checking account
belongs to the household rather than to whoever opened it, and forcing every
row to be attributed to a person would invent certainty that does not exist.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, HouseholdMember, Transaction, User
from app.services.spending_scope import is_spending


async def by_person(
    db: AsyncSession, household_id: uuid.UUID, start, end
) -> list[dict]:
    """
    Spending grouped by who it belongs to, plus a shared bucket.

    The per-transaction override wins over the account's owner, which is why
    this is a `COALESCE` rather than a join on one or the other.
    """
    owner = func.coalesce(Transaction.paid_by_user_id, Account.owner_user_id)
    rows = (
        await db.execute(
            select(
                owner.label("user_id"),
                func.sum(func.abs(Transaction.amount)).label("amount"),
                func.count(Transaction.id).label("count"),
            )
            .join(Account, Account.id == Transaction.account_id)
            .where(
                Transaction.household_id == household_id,
                Transaction.posted_date >= start,
                Transaction.posted_date <= end,
                is_spending(household_id),
            )
            .group_by(owner)
        )
    ).all()

    names = dict(
        (
            await db.execute(
                select(User.id, User.display_name)
                .join(HouseholdMember, HouseholdMember.user_id == User.id)
                .where(HouseholdMember.household_id == household_id)
            )
        ).all()
    )

    out = [
        {
            "user_id": str(user_id) if user_id else None,
            # A row with no owner is shared, not "unknown" — the account
            # genuinely belongs to both of them.
            "name": names.get(user_id, "Shared") if user_id else "Shared",
            "amount": str(Decimal(amount or 0)),
            "count": count,
        }
        for user_id, amount, count in rows
    ]
    # Largest first, with Shared last regardless of size: it is a different
    # kind of thing from a person and reads oddly interleaved with them.
    out.sort(key=lambda row: (row["user_id"] is None, -float(row["amount"])))
    return out
