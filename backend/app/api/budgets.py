from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Budget, BudgetLine, Category, Household
from app.schemas import BudgetUpsert
from app.security import AuthContext, current_auth
from app.services.budgets import month_start, upsert_budget
from app.services.cards import statement_obligations
from app.services.clock import today_in
from app.services.income import month_breakdown
from app.services.security_audit import record_security_event

router = APIRouter(prefix="/budgets", tags=["budgets"])


def _require_editor(auth: AuthContext) -> None:
    if auth.role == "viewer":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "View-only household members cannot change budgets",
        )


async def _month_context(db: AsyncSession, household_id, month: date, override):
    """
    The two things a budget month needs that are not stored on it.

    Both are computed rather than saved, for the same reason: a stored copy of
    a derived figure is a second source of truth that starts drifting the day
    somebody edits a pay date or a transaction.
    """
    household = await db.get(Household, household_id)
    today = today_in(household.timezone if household else None)
    return {
        "income": await month_breakdown(db, household_id, month, override),
        "cards": await statement_obligations(db, household_id, month, today),
    }


@router.get("/{month}")
async def get_budget(
    month: date,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    first = month_start(month)
    budget = await db.scalar(
        select(Budget).where(
            Budget.household_id == auth.household_id,
            Budget.month == first,
        )
    )
    if not budget:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    lines = (
        await db.scalars(
            select(BudgetLine).where(BudgetLine.budget_id == budget.id)
        )
    ).all()
    context = await _month_context(
        db, auth.household_id, first, budget.extra_paycheque
    )
    return {
        "id": budget.id,
        "month": budget.month,
        "mode": budget.mode,
        "expected_income": budget.expected_income,
        "flex_amount": budget.flex_amount,
        "extra_paycheque": budget.extra_paycheque,
        "lines": lines,
        **context,
    }


@router.get("/{month}/context")
async def month_context(
    month: date,
    extra_paycheque: bool | None = None,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    The same two figures for a month with **no budget saved yet**.

    Without this the first month a household plans has no income figure and no
    card obligations until they press save, which is precisely the month they
    most need to see both.
    """
    return await _month_context(
        db, auth.household_id, month_start(month), extra_paycheque
    )


@router.put("/{month}")
async def save_budget(
    month: date,
    payload: BudgetUpsert,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    if month_start(month) != month_start(payload.month):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Path and payload months must match",
        )
    incoming_categories = {line.category_id for line in payload.lines}
    household_categories = set(
        (
            await db.scalars(
                select(Category.id).where(
                    Category.household_id == auth.household_id,
                    Category.id.in_(incoming_categories),
                )
            )
        ).all()
    )
    if household_categories != incoming_categories:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Budget contains an invalid household category",
        )
    budget = await upsert_budget(db, auth.household_id, payload)
    await record_security_event(
        db,
        "finance.budget_saved",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "budget_id": budget.id,
            "month": budget.month.isoformat(),
            "mode": budget.mode.value,
            "lines": len(payload.lines),
        },
    )
    await db.commit()
    await db.refresh(budget)
    return {"id": budget.id, "month": budget.month, "mode": budget.mode}
