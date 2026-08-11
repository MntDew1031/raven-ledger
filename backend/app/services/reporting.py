import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountKind, AccountType, Transaction
from app.schemas import DashboardSummary
from app.services.budgets import month_start, next_month
from app.services.spending_scope import is_income, is_spending
from app.services.splits import countable


async def dashboard_summary(
    db: AsyncSession, household_id: uuid.UUID, month: date
) -> DashboardSummary:
    account_totals = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Account.kind == AccountKind.asset, Account.current_balance),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Account.kind == AccountKind.liability,
                            func.abs(Account.current_balance),
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Account.type == AccountType.credit,
                            func.abs(Account.current_balance),
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            Account.household_id == household_id,
            Account.is_hidden.is_(False),
        )
    )
    assets, liabilities, reserved = account_totals.one()
    start = month_start(month)
    end = next_month(month)
    # Classified by category, not merely by sign. Summing every negative amount
    # as "spending" meant a payroll reversal in an income category was reported
    # as money spent — on the dashboard, which is the first thing anybody sees.
    # Spending uses the same predicate as every other report in the app.
    spending_total = (
        await db.scalar(
            select(
                func.coalesce(func.sum(func.abs(Transaction.amount)), 0)
            ).where(
                Transaction.household_id == household_id,
                Transaction.posted_date >= start,
                Transaction.posted_date < end,
                is_spending(household_id),
            )
        )
    ) or 0
    # Income is the mirror, and it now uses the same predicate every other
    # report does. Spelling it out here is how the dashboard and
    # `/reports/cash-flow` came to disagree about the same month.
    income_total = (
        await db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.household_id == household_id,
                Transaction.posted_date >= start,
                Transaction.posted_date < end,
                is_income(household_id),
            )
        )
    ) or 0
    income, spending = income_total, spending_total
    income = Decimal(income)
    spending = Decimal(spending)
    needs_review = (
        await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.household_id == household_id,
                Transaction.reviewed.is_(False),
                countable(),
            )
        )
    ) or 0

    return DashboardSummary(
        needs_review=needs_review,
        assets=Decimal(assets),
        liabilities=Decimal(liabilities),
        net_worth=Decimal(assets) - Decimal(liabilities),
        month_income=income,
        month_spending=spending,
        savings_rate=(income - spending) / income if income else Decimal("0"),
        reserved=Decimal(reserved),
    )
