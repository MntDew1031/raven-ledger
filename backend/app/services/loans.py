"""
Debts that keep up with themselves.

A manually tracked loan used to be a number that only fell when somebody
remembered to edit it. That is wrong in a specific direction: interest accrues
whether or not anybody opens the app, so an un-modelled balance drifts
*optimistic*, and a debt you believe is smaller than it is is the worst kind of
wrong number to have.

Three pieces:

**Payments reduce the balance.** A transaction filed against the debt's own
category moves the balance by that amount. Nothing else does — spending *on* a
credit card is a charge, not a payment, and the two must not be confused.

**Interest is added monthly.** Simple monthly accrual at APR ÷ 12 on the
balance at the time. Not daily compounding, and deliberately not: a household
budgeting app that models amortisation to the cent implies a precision it does
not have, since it does not know the lender's day-count convention, when they
post, or how they treat a partial month. This gets within a few dollars of the
statement, which is what "roughly keep up" needs.

**No rate means no modelling.** The default is None and stays None. A guessed
rate produces a confidently wrong balance, which is worse than a stale one that
somebody knows is stale.
"""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    AccountKind,
    AccountType,
    Category,
    CategoryGroup,
    Transaction,
)

# The account types this applies to. A credit card is excluded on purpose: its
# balance comes from the charges on it, not from an amortisation schedule.
BORROWING = frozenset(
    {AccountType.loan, AccountType.mortgage, AccountType.debt}
)


def months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def monthly_interest(balance: Decimal, apr: Decimal) -> Decimal:
    """
    One month of interest, at APR ÷ 12 on the balance owed.

    Simple rather than daily-compounded. A household app that models
    amortisation to the cent claims a precision it does not have — it does not
    know the lender's day-count convention or posting day — and being a few
    dollars out on a balance you check monthly is not the problem worth
    solving.
    """
    if apr is None or balance >= 0:
        return Decimal("0.00")
    owed = abs(Decimal(balance))
    return (owed * Decimal(apr) / Decimal(1200)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def payoff_months(
    balance: Decimal, apr: Decimal | None, payment: Decimal | None
) -> int | None:
    """
    How long at the current payment, or None when it will never get there.

    Returning None for "the payment does not cover the interest" is the useful
    answer: a number like 900 months is technically true and reads as a
    schedule rather than as a warning.
    """
    if not payment or payment <= 0 or balance >= 0:
        return None
    owed = abs(Decimal(balance))
    rate = Decimal(apr or 0) / Decimal(1200)
    if rate > 0 and owed * rate >= Decimal(payment):
        return None
    months = 0
    while owed > 0 and months < 1200:
        owed += owed * rate
        owed -= Decimal(payment)
        months += 1
    return months if owed <= 0 else None


async def ensure_payment_category(
    db: AsyncSession, account: Account
) -> Category | None:
    """
    Give a new debt somewhere for its payments to go.

    Created with the account rather than left for later, so a loan is
    budgetable the moment it exists instead of after somebody notices its
    payments have nowhere to land. Reuses a category of the same name if one is
    already there — adding "Car loan" twice should not produce two of them.
    """
    if account.type not in BORROWING:
        return None
    name = f"{account.name} payment"[:100]
    existing = await db.scalar(
        select(Category).where(
            Category.household_id == account.household_id,
            func.lower(Category.name) == name.lower(),
        )
    )
    if existing is not None:
        account.payment_category_id = existing.id
        return existing

    group = await db.scalar(
        select(CategoryGroup)
        .where(
            CategoryGroup.household_id == account.household_id,
            CategoryGroup.is_income.is_(False),
        )
        .order_by(CategoryGroup.sort_order.asc())
        .limit(1)
    )
    if group is None:
        return None
    category = Category(
        household_id=account.household_id,
        group_id=group.id,
        name=name,
        # Fixed: a loan payment is the same every month, which is the whole
        # reason it is easy to budget for.
        flex_bucket="fixed",
    )
    db.add(category)
    await db.flush()
    account.payment_category_id = category.id
    return category


async def apply_payments(
    db: AsyncSession, account: Account, since: date | None = None
) -> Decimal:
    """
    Move the balance by whatever has been paid toward it.

    Only transactions filed against the debt's own category count. Spending on
    a credit card is a charge, not a payment, and conflating the two would let
    a shopping trip look like progress.
    """
    if account.payment_category_id is None:
        return Decimal("0.00")
    query = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.household_id == account.household_id,
        Transaction.category_id == account.payment_category_id,
        Transaction.amount < 0,
    )
    if since:
        query = query.where(Transaction.posted_date >= since)
    paid = Decimal(await db.scalar(query) or 0)
    return abs(paid)


def project(account: Account, today: date) -> dict:
    """What this debt looks like, and when it ends."""
    balance = Decimal(account.current_balance or 0)
    apr = Decimal(account.interest_rate) if account.interest_rate else None
    payment = (
        Decimal(account.minimum_payment) if account.minimum_payment else None
    )
    interest = monthly_interest(balance, apr) if apr else Decimal("0.00")
    months = payoff_months(balance, apr, payment)
    return {
        "balance": str(balance),
        "interest_rate": str(apr) if apr is not None else None,
        "monthly_interest": str(interest),
        "minimum_payment": str(payment) if payment is not None else None,
        "payoff_months": months,
        # Named rather than implied: "never" is the important case and a
        # missing number reads as "not calculated yet".
        "never_pays_off": bool(
            payment and apr and months is None and balance < 0
        ),
        "payment_category_id": str(account.payment_category_id)
        if account.payment_category_id
        else None,
    }


async def accrue_interest(
    db: AsyncSession, household_id: uuid.UUID, today: date
) -> dict[str, int]:
    """
    Add a month of interest to every borrowing account that has a rate.

    Guarded by `interest_applied_through` so running twice in a month is a
    no-op — this is called from a scheduled job, and a job that double-charges
    interest when it retries is worse than one that never runs.
    """
    accounts = (
        await db.scalars(
            select(Account).where(
                Account.household_id == household_id,
                Account.kind == AccountKind.liability,
                Account.interest_rate.is_not(None),
            )
        )
    ).all()

    month = today.replace(day=1)
    applied = 0
    for account in accounts:
        if account.type not in BORROWING:
            continue
        if (
            account.interest_applied_through
            and account.interest_applied_through >= month
        ):
            continue
        charge = monthly_interest(
            Decimal(account.current_balance or 0), Decimal(account.interest_rate)
        )
        if charge <= 0:
            account.interest_applied_through = month
            continue
        # A liability balance is negative, so interest makes it more so.
        account.current_balance = Decimal(account.current_balance) - charge
        account.interest_applied_through = month
        applied += 1
    return {"accounts": len(accounts), "charged": applied}
