"""
What a goal needs each month, and whether it is on track.

The interesting part is not the progress bar — it is the sentence underneath
it. "You have $4,200 of $12,000" tells you nothing you could not see; "$650 a
month to make June" tells you whether to change something.

Two rules about how honest to be:

**Round the required contribution up.** $649.31 a month becomes $650. Rounding
down produces a figure that is arithmetically correct and still misses the
target, which is the one thing a savings plan must not do.

**A goal with a date in the past is not "0 months left".** It is overdue, and
saying so is more useful than dividing by zero or quietly showing the whole
remaining balance as this month's contribution.
"""

import uuid
from datetime import date
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Goal


def months_between(start: date, end: date) -> int:
    """
    Whole months from one date to another, never below zero.

    Counted by calendar month rather than by dividing days, because "by June"
    means the end of June regardless of which day of the month it is today.
    """
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def summarize(goal: Goal, saved: Decimal, today: date) -> dict:
    target = Decimal(goal.target_amount)
    remaining = max(target - saved, Decimal("0.00"))
    progress = (
        float((saved / target * 100).quantize(Decimal("0.1")))
        if target > 0
        else 0.0
    )

    months_left: int | None = None
    monthly_needed: Decimal | None = None
    overdue = False
    if goal.target_date is not None:
        if goal.target_date < today and remaining > 0:
            overdue = True
        else:
            months_left = months_between(today, goal.target_date)
            if remaining > 0:
                # Rounded up: a figure that is arithmetically right and still
                # misses the target is the one outcome a savings plan cannot
                # afford. The remainder of this month counts as a month.
                divisor = Decimal(max(months_left, 1))
                monthly_needed = (remaining / divisor).quantize(
                    Decimal("1"), rounding=ROUND_CEILING
                )

    return {
        "id": goal.id,
        "name": goal.name,
        "target_amount": str(target),
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "account_id": goal.account_id,
        "saved_amount": str(saved.quantize(Decimal("0.01"))),
        "remaining": str(remaining.quantize(Decimal("0.01"))),
        "progress_percent": min(progress, 100.0),
        "months_left": months_left,
        "monthly_needed": str(monthly_needed) if monthly_needed is not None else None,
        "overdue": overdue,
        "is_achieved": goal.is_achieved or remaining <= 0,
        "notes": goal.notes,
    }


async def list_goals(
    db: AsyncSession, household_id: uuid.UUID, today: date
) -> list[dict]:
    goals = (
        await db.scalars(
            select(Goal)
            .where(Goal.household_id == household_id)
            .order_by(Goal.is_achieved.asc(), Goal.created_at.asc())
        )
    ).all()
    if not goals:
        return []

    # A linked account's balance is the truth; `saved_amount` is only the
    # fallback for goals not yet backed by one. Fetched in a single query
    # rather than per goal.
    linked = {goal.account_id for goal in goals if goal.account_id}
    balances: dict[uuid.UUID, Decimal] = {}
    if linked:
        rows = (
            await db.execute(
                select(Account.id, Account.current_balance).where(
                    Account.id.in_(linked),
                    Account.household_id == household_id,
                )
            )
        ).all()
        balances = {row[0]: Decimal(row[1] or 0) for row in rows}

    return [
        summarize(
            goal,
            balances.get(goal.account_id, Decimal(goal.saved_amount))
            if goal.account_id
            else Decimal(goal.saved_amount),
            today,
        )
        for goal in goals
    ]
