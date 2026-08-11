"""
What is actually safe to spend, and where the next tight spot is.

A monthly "remaining" figure is nearly useless on the 9th. It says nothing
about whether rent has gone out yet, or whether payday is tomorrow or twelve
days away — and those are the only two things that decide whether a purchase is
fine right now.

Raven already knows both. `income_sources` carries each earner's amount and
cadence, and `recurring_items` carries every bill it has detected with a
`next_due` date. Putting them on one timeline gives two answers:

**Safe to spend** — cash on hand, minus the bills falling due before the next
money arrives. What is genuinely yours between now and then.

**The forecast** — the same walk continued for sixty days, which surfaces the
*lowest point* the balance reaches. That is the number that matters for "can we
afford this", and it is almost never today's balance.

Two deliberate choices about how conservative to be:

- Payday projection ignores income sources' *history* and works purely from
  cadence, because a missed or early paycheque should not shift future dates.
- The safe-to-spend figure subtracts every bill due in the window but counts
  **no** income except what has already arrived. Being told you have less than
  you do is a small annoyance; being told you have more is an overdraft.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    AccountKind,
    AccountType,
    IncomeSource,
    PayCadence,
    RecurringItem,
)

FORECAST_DAYS = 60

# Days between payments, for walking a cadence forward. Semi-monthly is handled
# separately because it lands on days of the month rather than on an interval —
# Jordan is paid on the 15th and the 30th, which is not "every 15.2 days".
CADENCE_DAYS: dict[PayCadence, int] = {
    PayCadence.weekly: 7,
    PayCadence.biweekly: 14,
}

# Where a semi-monthly earner's money lands. The 30th is clamped to the last
# day of the month, so February pays on the 28th rather than being skipped.
SEMIMONTHLY_DAYS = (15, 30)

# How a detected bill's cadence advances.
BILL_CADENCE_DAYS: dict[str, int] = {
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
    "bimonthly": 61,
    "quarterly": 91,
    "yearly": 365,
}


def _clamp_to_month(year: int, month: int, day: int) -> date:
    """The given day of that month, or its last day if the month is shorter."""
    if month == 12:
        first_of_next = date(year + 1, 1, 1)
    else:
        first_of_next = date(year, month + 1, 1)
    last_day = (first_of_next - timedelta(days=1)).day
    return date(year, month, min(day, last_day))


def paydays_for(
    source: IncomeSource, start: date, end: date
) -> list[tuple[date, Decimal]]:
    """
    Every payment from one earner between two dates.

    Worked from the cadence rather than from when they were last paid, so one
    early or missed deposit does not shift every future date.
    """
    amount = Decimal(source.amount)
    if amount <= 0 or not source.is_active:
        return []

    if source.cadence == PayCadence.semimonthly:
        days: list[date] = []
        year, month = start.year, start.month
        # Two months of candidates is enough to cover any window that starts
        # mid-month; anything past `end` is filtered below.
        for _ in range(((end - start).days // 28) + 3):
            for day in SEMIMONTHLY_DAYS:
                days.append(_clamp_to_month(year, month, day))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return [(day, amount) for day in days if start <= day <= end]

    if source.cadence == PayCadence.monthly:
        days = []
        year, month = start.year, start.month
        for _ in range(((end - start).days // 28) + 3):
            days.append(_clamp_to_month(year, month, 1))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return [(day, amount) for day in days if start <= day <= end]

    if source.cadence == PayCadence.annual:
        # Spread rather than dropped: a yearly figure has no meaningful payday,
        # and pretending it all lands on one unknown date would make every
        # forecast wrong twice.
        return []

    step = CADENCE_DAYS.get(source.cadence)
    if step is None:
        return []
    # Anchored to the source's creation so bi-weekly dates stay stable between
    # runs rather than drifting with today's date.
    anchor = source.created_at.date()
    while anchor < start:
        anchor += timedelta(days=step)
    out: list[tuple[date, Decimal]] = []
    while anchor <= end:
        out.append((anchor, amount))
        anchor += timedelta(days=step)
    return out


def bill_dates(item: RecurringItem, start: date, end: date) -> list[date]:
    """When a detected bill falls due inside the window."""
    step = BILL_CADENCE_DAYS.get(item.cadence)
    if step is None:
        return []
    due = item.next_due
    # A bill whose due date has already passed without a matching transaction
    # is rolled forward rather than dropped: it is late, not cancelled.
    while due < start:
        due += timedelta(days=step)
    out: list[date] = []
    while due <= end:
        out.append(due)
        due += timedelta(days=step)
    return out


async def spendable_balance(db: AsyncSession, household_id: uuid.UUID) -> Decimal:
    """
    Money you could actually spend today.

    Checking, savings and cash. Credit is excluded deliberately — available
    credit is not money you have, and counting it is how a "safe to spend"
    figure becomes an argument for spending more.
    """
    rows = (
        await db.scalars(
            select(Account.current_balance).where(
                Account.household_id == household_id,
                Account.kind == AccountKind.asset,
                Account.type.in_(
                    [AccountType.checking, AccountType.savings, AccountType.cash]
                ),
                Account.is_hidden.is_(False),
            )
        )
    ).all()
    return sum((Decimal(value or 0) for value in rows), Decimal("0.00"))


async def build(
    db: AsyncSession, household_id: uuid.UUID, today: date, days: int = FORECAST_DAYS
) -> dict:
    """
    Walk the next `days` forward, one day at a time.

    Returns the day-by-day balance, the lowest point it reaches, the next
    payday, and what is safe to spend before that payday arrives.
    """
    end = today + timedelta(days=days)

    sources = (
        await db.scalars(
            select(IncomeSource).where(
                IncomeSource.household_id == household_id,
                IncomeSource.is_active.is_(True),
            )
        )
    ).all()
    bills = (
        await db.scalars(
            select(RecurringItem).where(
                RecurringItem.household_id == household_id,
                RecurringItem.is_active.is_(True),
                RecurringItem.direction == "outflow",
            )
        )
    ).all()

    events: dict[date, list[dict]] = {}
    for source in sources:
        for day, amount in paydays_for(source, today + timedelta(days=1), end):
            events.setdefault(day, []).append(
                {
                    "kind": "income",
                    "label": source.name,
                    "amount": str(amount),
                }
            )
    for item in bills:
        for day in bill_dates(item, today, end):
            events.setdefault(day, []).append(
                {
                    "kind": "bill",
                    "label": item.display_name,
                    # Stored as the average outflow, which is negative.
                    "amount": str(item.average_amount),
                }
            )

    balance = await spendable_balance(db, household_id)
    running = balance
    timeline: list[dict] = []
    low_point = {"date": today.isoformat(), "balance": str(balance)}
    for offset in range(days + 1):
        day = today + timedelta(days=offset)
        for event in events.get(day, []):
            running += Decimal(event["amount"])
        timeline.append(
            {
                "date": day.isoformat(),
                "balance": str(running.quantize(Decimal("0.01"))),
                "events": events.get(day, []),
            }
        )
        if running < Decimal(low_point["balance"]):
            low_point = {
                "date": day.isoformat(),
                "balance": str(running.quantize(Decimal("0.01"))),
            }

    # The next time money arrives, and what has to come out of today's balance
    # before it does.
    next_payday: date | None = None
    for day in sorted(events):
        if day <= today:
            continue
        if any(event["kind"] == "income" for event in events[day]):
            next_payday = day
            break

    horizon = next_payday or end
    due_before_payday = [
        {**event, "date": day.isoformat()}
        for day in sorted(events)
        if today <= day <= horizon
        for event in events[day]
        if event["kind"] == "bill"
    ]
    committed = sum(
        (Decimal(item["amount"]) for item in due_before_payday), Decimal("0.00")
    )
    # No incoming money is counted here even if a payday sits inside the window
    # — being told you have less than you do is an annoyance, being told you
    # have more is an overdraft.
    safe = (balance + committed).quantize(Decimal("0.01"))

    return {
        "balance": str(balance.quantize(Decimal("0.01"))),
        "safe_to_spend": str(safe),
        "next_payday": next_payday.isoformat() if next_payday else None,
        "days_until_payday": (next_payday - today).days if next_payday else None,
        "committed_before_payday": str(committed.quantize(Decimal("0.01"))),
        "bills_before_payday": due_before_payday,
        "low_point": low_point,
        "timeline": timeline,
        "has_income_sources": bool(sources),
        "has_bills": bool(bills),
    }
