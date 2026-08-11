"""Named income sources: who earns what, and how often."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import HouseholdRole, IncomeSource
from app.schemas import (
    IncomeSourceCreate,
    IncomeSourceResponse,
    IncomeSourceUpdate,
    IncomeSummary,
)
from app.security import AuthContext, current_auth
from app.services.income import (
    CADENCE_LABELS,
    extra_paycheque_months,
    monthly_equivalent,
)

router = APIRouter(prefix="/income-sources", tags=["income"])


def _render(source: IncomeSource) -> IncomeSourceResponse:
    return IncomeSourceResponse(
        id=source.id,
        name=source.name,
        amount=source.amount,
        cadence=source.cadence,
        is_active=source.is_active,
        first_paid_on=source.first_paid_on,
        notes=source.notes,
        monthly_equivalent=monthly_equivalent(source.amount, source.cadence),
        cadence_label=CADENCE_LABELS.get(source.cadence, "monthly"),
        extra_paycheque_months=extra_paycheque_months(source.cadence),
    )


def _require_editor(auth: AuthContext) -> None:
    if auth.role == HouseholdRole.viewer.value:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Viewers cannot change income sources"
        )


@router.get("", response_model=IncomeSummary)
async def list_income_sources(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.scalars(
            select(IncomeSource)
            .where(IncomeSource.household_id == auth.household_id)
            .order_by(IncomeSource.created_at.asc())
        )
    ).all()
    rendered = [_render(item) for item in rows]
    # Summed from the rounded per-source figures, so the total equals the sum
    # of the numbers printed beside each name.
    total = sum(
        (item.monthly_equivalent for item in rendered if item.is_active),
        __import__("decimal").Decimal("0.00"),
    )
    return IncomeSummary(sources=rendered, monthly_total=total)


@router.post("", response_model=IncomeSourceResponse, status_code=201)
async def create_income_source(
    payload: IncomeSourceCreate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    existing = await db.scalar(
        select(IncomeSource).where(
            IncomeSource.household_id == auth.household_id,
            IncomeSource.name == payload.name.strip(),
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"There is already an income source called {payload.name.strip()}.",
        )
    source = IncomeSource(
        household_id=auth.household_id,
        name=payload.name.strip(),
        amount=payload.amount,
        cadence=payload.cadence,
        is_active=payload.is_active,
        first_paid_on=payload.first_paid_on,
        notes=payload.notes,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return _render(source)


@router.patch("/{source_id}", response_model=IncomeSourceResponse)
async def update_income_source(
    source_id: uuid.UUID,
    payload: IncomeSourceUpdate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    source = await db.get(IncomeSource, source_id)
    if source is None or source.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such income source")
    # `model_fields_set` rather than a None check, because clearing the pay
    # anchor is a legitimate edit and `None` is how you say it. Testing for
    # None makes a field that can be set but never unset.
    for field in (
        "name", "amount", "cadence", "is_active", "first_paid_on", "notes"
    ):
        if field not in payload.model_fields_set:
            continue
        value = getattr(payload, field)
        if field == "name":
            if value is None:
                continue
            value = value.strip()
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return _render(source)


@router.delete("/{source_id}", status_code=204)
async def delete_income_source(
    source_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    source = await db.get(IncomeSource, source_id)
    if source is None or source.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such income source")
    await db.delete(source)
    await db.commit()
