"""
Recurring merchant detection.

Finds bills, subscriptions, and paychecks by looking for merchants whose
transactions repeat on a steady cadence with steady amounts. Detection is
deterministic and re-runs safely: results are upserted by merchant, and a
person's decision to mute an item survives every re-run.
"""

import statistics
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Household, RecurringItem, Transaction
from app.services.clock import today_in

# Cadence bands in days: median gap → label.
CADENCE_BANDS: list[tuple[int, int, str]] = [
    (6, 8, "weekly"),
    (12, 17, "biweekly"),
    (26, 35, "monthly"),
    (55, 70, "bimonthly"),
    (80, 100, "quarterly"),
    (340, 400, "yearly"),
]

MIN_OCCURRENCES = 3
# Look back far enough to catch yearly items with three occurrences.
LOOKBACK_DAYS = 3 * 400
MAX_TRANSACTIONS = 5000
# Tolerances: a bill drifting a few days or a utility varying in amount is
# still recurring; a merchant you merely visit often is not.
GAP_TOLERANCE_FRACTION = 0.35
GAP_TOLERANCE_MIN_DAYS = 5
AMOUNT_TOLERANCE_FRACTION = 0.30
CONSISTENCY_REQUIRED = 0.7


def classify_cadence(median_gap_days: float) -> str | None:
    for low, high, label in CADENCE_BANDS:
        if low <= median_gap_days <= high:
            return label
    return None


def evaluate_group(
    dates: list[date], amounts: list[Decimal]
) -> tuple[str, date, Decimal] | None:
    """
    Decide whether one merchant's history is recurring.

    Returns (cadence, next_due, average_amount), or None.
    """
    if len(dates) < MIN_OCCURRENCES:
        return None
    ordered = sorted(dates)
    gaps = [
        (later - earlier).days
        for earlier, later in zip(ordered, ordered[1:])
    ]
    # Same-day duplicates (split shipments, partial charges) are not gaps.
    gaps = [gap for gap in gaps if gap > 0]
    if len(gaps) < MIN_OCCURRENCES - 1:
        return None
    median_gap = statistics.median(gaps)
    cadence = classify_cadence(median_gap)
    if cadence is None:
        return None
    tolerance = max(GAP_TOLERANCE_MIN_DAYS, median_gap * GAP_TOLERANCE_FRACTION)
    steady_gaps = sum(1 for gap in gaps if abs(gap - median_gap) <= tolerance)
    if steady_gaps / len(gaps) < CONSISTENCY_REQUIRED:
        return None

    magnitudes = [abs(amount) for amount in amounts]
    median_amount = statistics.median(magnitudes)
    if median_amount == 0:
        return None
    steady_amounts = sum(
        1
        for amount in magnitudes
        if abs(amount - median_amount) / median_amount
        <= AMOUNT_TOLERANCE_FRACTION
    )
    if steady_amounts / len(magnitudes) < CONSISTENCY_REQUIRED:
        return None

    next_due = ordered[-1] + timedelta(days=round(median_gap))
    return cadence, next_due, Decimal(str(median_amount)).quantize(
        Decimal("0.01")
    )


async def detect_recurring(db: AsyncSession, household_id: uuid.UUID) -> dict:
    household = await db.get(Household, household_id)
    today = today_in(household.timezone if household else None)
    since = today - timedelta(days=LOOKBACK_DAYS)
    transactions = (
        await db.scalars(
            select(Transaction)
            .where(
                Transaction.household_id == household_id,
                Transaction.posted_date >= since,
                Transaction.is_transfer.is_(False),
                Transaction.pending.is_(False),
                # Recurrence is a property of the bank charge. Split lines
                # repeat their parent's merchant and date, so counting them
                # would turn one monthly bill into several.
                Transaction.parent_transaction_id.is_(None),
            )
            .order_by(Transaction.posted_date.desc())
            .limit(MAX_TRANSACTIONS)
        )
    ).all()

    groups: dict[tuple[str, str], list[Transaction]] = {}
    for item in transactions:
        key = item.normalized_merchant or ""
        if not key:
            continue
        direction = "inflow" if item.amount > 0 else "outflow"
        groups.setdefault((key, direction), []).append(item)

    found = 0
    for (merchant_key, direction), members in groups.items():
        outcome = evaluate_group(
            [item.posted_date for item in members],
            [item.amount for item in members],
        )
        if outcome is None:
            continue
        cadence, next_due, average_amount = outcome
        latest = max(members, key=lambda item: item.posted_date)
        statement = (
            insert(RecurringItem)
            .values(
                household_id=household_id,
                merchant_key=merchant_key,
                display_name=(
                    latest.merchant_name or latest.original_description
                )[:255],
                direction=direction,
                cadence=cadence,
                average_amount=average_amount,
                last_amount=latest.amount,
                occurrences=len(members),
                last_seen=latest.posted_date,
                next_due=next_due,
                category_id=latest.category_id,
                account_id=latest.account_id,
            )
            .on_conflict_do_update(
                index_elements=["household_id", "merchant_key", "direction"],
                # A mute (is_active=False) is a human decision: never undo it.
                set_={
                    "display_name": (
                        latest.merchant_name or latest.original_description
                    )[:255],
                    "cadence": cadence,
                    "average_amount": average_amount,
                    "last_amount": latest.amount,
                    "occurrences": len(members),
                    "last_seen": latest.posted_date,
                    "next_due": next_due,
                    "category_id": latest.category_id,
                    "account_id": latest.account_id,
                },
            )
        )
        await db.execute(statement)
        found += 1
    await db.commit()
    return {"detected": found, "scanned": len(transactions)}
