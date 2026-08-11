"""
Turning what people are actually paid into a monthly figure.

The budget used to hold one "expected monthly income" number. Alex is paid
$2,049 every two weeks and Jordan $1,340 every two weeks; a single field cannot
say that, and it cannot survive either of them getting a raise without somebody
re-deriving the total by hand.

**The arithmetic is the whole point of this module.** Being paid every two
weeks is not the same as being paid twice a month:

    biweekly  →  26 payments a year  →  amount × 26 / 12
    semimonthly → 24 payments a year →  amount × 2

Alex's $2,049 bi-weekly is $4,439.50 a month, not $4,098. Doubling it
under-counts by $341.50 every month — and hides the fact that two months a year
carry a third paycheque, which is exactly the money a household is most likely
to plan badly. Their combined figure is $7,342.83, against $6,778 if you
multiply by two.

Rounding is deliberate: each source is converted, then rounded to the cent, and
only then summed. Summing exact fractions and rounding once produces a total
that does not equal the sum of the figures printed beside it, which reads as a
bug every time somebody checks the addition.
"""

import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IncomeSource, PayCadence

# Payments per year for each cadence. Weekly and bi-weekly are the two that
# people — and budgeting apps — routinely get wrong.
PAYMENTS_PER_YEAR: dict[PayCadence, Decimal] = {
    PayCadence.weekly: Decimal(52),
    PayCadence.biweekly: Decimal(26),
    PayCadence.semimonthly: Decimal(24),
    PayCadence.monthly: Decimal(12),
    PayCadence.annual: Decimal(1),
}

CADENCE_LABELS: dict[PayCadence, str] = {
    PayCadence.weekly: "every week",
    PayCadence.biweekly: "every 2 weeks",
    PayCadence.semimonthly: "twice a month",
    PayCadence.monthly: "monthly",
    PayCadence.annual: "yearly",
}


def monthly_equivalent(amount: Decimal, cadence: PayCadence) -> Decimal:
    """One source's pay expressed as a monthly figure, rounded to the cent."""
    per_year = PAYMENTS_PER_YEAR.get(cadence, Decimal(12))
    return (Decimal(amount) * per_year / Decimal(12)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def extra_paycheque_months(cadence: PayCadence) -> int:
    """
    How many months a year carry an extra payment.

    Being paid every two weeks means two months of the year hold three
    paycheques rather than two; weekly means four months hold five. Worth
    surfacing, because that money is the most commonly mis-planned in a
    household budget — it arrives looking like a windfall and is in fact
    already counted in the monthly average above.
    """
    if cadence == PayCadence.biweekly:
        return 2
    if cadence == PayCadence.weekly:
        return 4
    return 0


async def monthly_total(db: AsyncSession, household_id: uuid.UUID) -> Decimal:
    """
    Expected monthly income from every active source.

    Rounded per source before summing, so the total equals the sum of the
    figures shown next to each name.
    """
    sources = (
        await db.scalars(
            select(IncomeSource).where(
                IncomeSource.household_id == household_id,
                IncomeSource.is_active.is_(True),
            )
        )
    ).all()
    return sum(
        (monthly_equivalent(item.amount, item.cadence) for item in sources),
        Decimal("0.00"),
    )


def payments_in_month(
    cadence: PayCadence,
    first_paid_on: date | None,
    month: date,
) -> int | None:
    """
    How many times this source actually pays during `month`.

    **This is the number Alex asked for and the one the budget was not using.**
    A monthly average is the right figure for a year and the wrong figure for a
    month: $2,049.70 every two weeks averages $4,441.02, but ten months of the
    year hold two cheques ($4,099.40) and two hold three ($6,149.10). Budgeting
    the average in a two-cheque month plans $341.62 that will not arrive.

    Returns `None` when it cannot be known — no anchor date, or a cadence where
    the question does not arise — and the caller falls back to the average.

    Semimonthly and monthly are exact by definition and need no anchor: twice a
    month is twice in every month, whatever the calendar does.
    """
    if cadence == PayCadence.semimonthly:
        return 2
    if cadence == PayCadence.monthly:
        return 1
    if cadence == PayCadence.annual:
        # Only in its own month, and only if we know which one that is.
        if first_paid_on is None:
            return None
        return 1 if first_paid_on.month == month.month else 0
    if first_paid_on is None:
        return None

    step = 7 if cadence == PayCadence.weekly else 14
    start = month.replace(day=1)
    end = _next_month(start)

    # Walk to the first payment on or after the first of the month. Modular
    # arithmetic rather than a loop from the anchor, so an anchor twenty years
    # ago costs the same as one last week — and it works backwards, for an
    # anchor that is the *next* pay date rather than a past one.
    delta = (start - first_paid_on).days
    offset = delta % step
    first_in_month = start if offset == 0 else start + timedelta(days=step - offset)

    count = 0
    cursor = first_in_month
    while cursor < end:
        count += 1
        cursor += timedelta(days=step)
    return count


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def baseline_payments(cadence: PayCadence) -> int:
    """
    The number of payments a month holds when it is *not* an extra-cheque
    month. Used to describe the two states of the override in words rather
    than making somebody work out which is which.
    """
    if cadence == PayCadence.weekly:
        return 4
    if cadence == PayCadence.biweekly:
        return 2
    if cadence == PayCadence.semimonthly:
        return 2
    if cadence == PayCadence.monthly:
        return 1
    return 0


async def month_breakdown(
    db: AsyncSession,
    household_id: uuid.UUID,
    month: date,
    override: bool | None = None,
) -> dict:
    """
    What this household is actually paid in one specific month.

    `override` is the tri-state the budget stores: `None` uses the calendar,
    `True` forces the extra cheque, `False` forces the baseline. A person needs
    that when a payment lands a day either side of a month boundary and the
    bank disagrees with the arithmetic.
    """
    sources = (
        await db.scalars(
            select(IncomeSource).where(
                IncomeSource.household_id == household_id,
                IncomeSource.is_active.is_(True),
            )
        )
    ).all()

    rows: list[dict] = []
    total = Decimal("0.00")
    exact = True
    has_extra = False
    for item in sources:
        counted = payments_in_month(
            item.cadence, item.first_paid_on, month
        )
        base = baseline_payments(item.cadence)
        if counted is None:
            # No anchor: the average is the honest answer, and the month total
            # is flagged as an estimate rather than quietly presented as fact.
            exact = False
            amount = monthly_equivalent(item.amount, item.cadence)
            payments = None
        else:
            if override is True and extra_paycheque_months(item.cadence):
                counted = base + 1
            elif override is False and extra_paycheque_months(item.cadence):
                counted = base
            payments = counted
            if counted > base:
                has_extra = True
            amount = (Decimal(item.amount) * counted).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        total += amount
        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "amount": Decimal(item.amount),
                "cadence": item.cadence.value,
                "payments": payments,
                "baseline_payments": base,
                "month_amount": amount,
                "monthly_average": monthly_equivalent(item.amount, item.cadence),
            }
        )

    return {
        "month_total": total,
        "average_total": sum(
            (row["monthly_average"] for row in rows), Decimal("0.00")
        ),
        "sources": rows,
        # False when any source lacks an anchor date, so the UI can say the
        # figure is an average rather than a count.
        "exact": exact,
        "has_extra_paycheque": has_extra,
        "override": override,
    }
