from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Household, NetWorthSnapshot
from app.schemas import DashboardSummary
from app.security import AuthContext, current_auth
from app.services.clock import today_in
from app.services.reporting import dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary(
    month: date | None = None,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    `month` defaults to the household's current month.

    It must not be a function default: Python evaluates those once at import,
    which would freeze the dashboard to whenever the container happened to
    start.
    """
    household = await db.get(Household, auth.household_id)
    effective = month or today_in(household.timezone if household else None)
    return await dashboard_summary(db, auth.household_id, effective)


@router.get("/net-worth")
async def net_worth_history(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    snapshots = (
        await db.scalars(
            select(NetWorthSnapshot)
            .where(NetWorthSnapshot.household_id == auth.household_id)
            .order_by(NetWorthSnapshot.snapshot_date.asc())
            .limit(730)
        )
    ).all()
    return snapshots
