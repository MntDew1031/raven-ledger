import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Account, Category, RecurringItem
from app.schemas import (
    RecurringDetectResponse,
    RecurringItemResponse,
    RecurringItemUpdate,
)
from app.security import AuthContext, current_auth
from app.worker import enqueue_job

router = APIRouter(prefix="/recurring", tags=["recurring"])


def _require_editor(auth: AuthContext) -> None:
    if auth.role == "viewer":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "View-only household members cannot change recurring items",
        )


@router.get("", response_model=list[RecurringItemResponse])
async def list_recurring(
    include_muted: bool = False,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(RecurringItem, Category.name, Account.name)
        .outerjoin(Category, RecurringItem.category_id == Category.id)
        .outerjoin(Account, RecurringItem.account_id == Account.id)
        .where(RecurringItem.household_id == auth.household_id)
        .order_by(RecurringItem.next_due.asc())
    )
    if not include_muted:
        query = query.where(RecurringItem.is_active.is_(True))
    rows = await db.execute(query)
    return [
        RecurringItemResponse(
            id=item.id,
            display_name=item.display_name,
            direction=item.direction,
            cadence=item.cadence,
            average_amount=item.average_amount,
            last_amount=item.last_amount,
            occurrences=item.occurrences,
            last_seen=item.last_seen,
            next_due=item.next_due,
            category_id=item.category_id,
            category_name=category_name,
            account_name=account_name,
            is_active=item.is_active,
        )
        for item, category_name, account_name in rows
    ]


@router.post("/detect", response_model=RecurringDetectResponse, status_code=202)
async def detect_now(
    auth: AuthContext = Depends(current_auth),
):
    _require_editor(auth)
    await enqueue_job("detect_recurring_household", str(auth.household_id))
    return RecurringDetectResponse(queued=True)


@router.patch("/{item_id}", response_model=RecurringItemResponse)
async def update_recurring(
    item_id: uuid.UUID,
    payload: RecurringItemUpdate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    item = await db.scalar(
        select(RecurringItem).where(
            RecurringItem.id == item_id,
            RecurringItem.household_id == auth.household_id,
        )
    )
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recurring item not found")
    fields = payload.model_fields_set
    if "category_id" in fields and payload.category_id:
        category_exists = await db.scalar(
            select(Category.id).where(
                Category.id == payload.category_id,
                Category.household_id == auth.household_id,
            )
        )
        if not category_exists:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    for field in ("display_name", "category_id", "is_active"):
        if field in fields:
            value = getattr(payload, field)
            if value is None and field == "display_name":
                continue
            setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    category_name = (
        await db.scalar(
            select(Category.name).where(Category.id == item.category_id)
        )
        if item.category_id
        else None
    )
    account_name = (
        await db.scalar(
            select(Account.name).where(Account.id == item.account_id)
        )
        if item.account_id
        else None
    )
    return RecurringItemResponse(
        id=item.id,
        display_name=item.display_name,
        direction=item.direction,
        cadence=item.cadence,
        average_amount=item.average_amount,
        last_amount=item.last_amount,
        occurrences=item.occurrences,
        last_seen=item.last_seen,
        next_due=item.next_due,
        category_id=item.category_id,
        category_name=category_name,
        account_name=account_name,
        is_active=item.is_active,
    )
