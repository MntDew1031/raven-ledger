"""Safe to spend, and the next sixty days."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security import AuthContext, current_auth
from app.services import forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("")
async def read_forecast(
    days: int = Query(default=forecast.FORECAST_DAYS, ge=7, le=180),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Cash on hand walked forward against known paydays and known bills.

    Answers the two questions a monthly budget cannot: what is safe to spend
    before the next money arrives, and how low does the balance get.
    """
    return await forecast.build(db, auth.household_id, date.today(), days=days)
