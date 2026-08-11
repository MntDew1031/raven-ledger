"""Things being saved for."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Goal, HouseholdRole
from app.schemas import GoalCreate, GoalResponse, GoalUpdate
from app.security import AuthContext, current_auth
from app.services import goals as goal_service

router = APIRouter(prefix="/goals", tags=["goals"])


def _require_editor(auth: AuthContext) -> None:
    if auth.role == HouseholdRole.viewer.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers cannot change goals")


@router.get("", response_model=list[GoalResponse])
async def list_goals(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = await goal_service.list_goals(db, auth.household_id, date.today())
    return [GoalResponse(**row) for row in rows]


async def _one(db: AsyncSession, goal: Goal) -> GoalResponse:
    rows = await goal_service.list_goals(db, goal.household_id, date.today())
    match = next((row for row in rows if row["id"] == goal.id), None)
    if match is None:  # pragma: no cover - it was just written
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such goal")
    return GoalResponse(**match)


@router.post("", response_model=GoalResponse, status_code=201)
async def create_goal(
    payload: GoalCreate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    goal = Goal(
        household_id=auth.household_id,
        name=payload.name.strip(),
        target_amount=payload.target_amount,
        target_date=payload.target_date,
        account_id=payload.account_id,
        saved_amount=payload.saved_amount,
        notes=payload.notes,
    )
    db.add(goal)
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - the unique constraint
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"There is already a goal called {payload.name.strip()}.",
        ) from exc
    await db.refresh(goal)
    return await _one(db, goal)


@router.patch("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: uuid.UUID,
    payload: GoalUpdate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    goal = await db.get(Goal, goal_id)
    if goal is None or goal.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such goal")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(goal, field, value.strip() if field == "name" and value else value)
    await db.commit()
    await db.refresh(goal)
    return await _one(db, goal)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    goal = await db.get(Goal, goal_id)
    if goal is None or goal.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such goal")
    await db.delete(goal)
    await db.commit()
