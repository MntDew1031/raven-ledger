import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Budget, BudgetLine, Transaction
from app.schemas import BudgetUpsert
from app.services.splits import countable


def month_start(value: date) -> date:
    return value.replace(day=1)


def previous_month(value: date) -> date:
    return (month_start(value) - timedelta(days=1)).replace(day=1)


def next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


async def _rollover_amount(
    db: AsyncSession,
    household_id: uuid.UUID,
    category_id: uuid.UUID,
    month: date,
) -> Decimal:
    prior_budget = await db.scalar(
        select(Budget).where(
            Budget.household_id == household_id,
            Budget.month == previous_month(month),
        )
    )
    if not prior_budget:
        return Decimal("0")
    prior_line = await db.scalar(
        select(BudgetLine).where(
            BudgetLine.budget_id == prior_budget.id,
            BudgetLine.category_id == category_id,
            BudgetLine.rollover_enabled.is_(True),
        )
    )
    if not prior_line:
        return Decimal("0")

    spent = await db.scalar(
        select(func.coalesce(func.sum(func.abs(Transaction.amount)), 0)).where(
            Transaction.household_id == household_id,
            Transaction.category_id == category_id,
            Transaction.amount < 0,
            Transaction.excluded_from_budget.is_(False),
            countable(),
            Transaction.posted_date >= previous_month(month),
            Transaction.posted_date < month_start(month),
        )
    )
    return max(
        Decimal("0"),
        prior_line.planned_amount + prior_line.rollover_amount - Decimal(spent),
    )


async def upsert_budget(
    db: AsyncSession, household_id: uuid.UUID, payload: BudgetUpsert
) -> Budget:
    month = month_start(payload.month)
    budget = await db.scalar(
        select(Budget).where(
            Budget.household_id == household_id,
            Budget.month == month,
        )
    )
    if budget is None:
        budget = Budget(household_id=household_id, month=month)
        db.add(budget)
        await db.flush()

    budget.mode = payload.mode
    budget.expected_income = payload.expected_income
    budget.flex_amount = payload.flex_amount
    budget.extra_paycheque = payload.extra_paycheque
    existing = {
        line.category_id: line
        for line in (
            await db.scalars(
                select(BudgetLine).where(BudgetLine.budget_id == budget.id)
            )
        ).all()
    }
    incoming_ids: set[uuid.UUID] = set()
    for item in payload.lines:
        incoming_ids.add(item.category_id)
        line = existing.get(item.category_id)
        if line is None:
            line = BudgetLine(
                budget_id=budget.id,
                category_id=item.category_id,
            )
            db.add(line)
        line.planned_amount = item.planned_amount
        line.rollover_enabled = item.rollover_enabled
        line.rollover_amount = (
            await _rollover_amount(db, household_id, item.category_id, month)
            if item.rollover_enabled
            else Decimal("0")
        )
        line.non_monthly_target = item.non_monthly_target
        line.non_monthly_due_date = item.non_monthly_due_date

    for category_id, line in existing.items():
        if category_id not in incoming_ids:
            await db.delete(line)
    await db.flush()
    return budget
