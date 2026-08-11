from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Account,
    Budget,
    Household,
    HouseholdInvite,
    HouseholdMember,
    InstitutionConnection,
    Transaction,
)
from app.schemas import OnboardingStatus, OnboardingStep
from app.security import AuthContext, current_auth
from app.services.profiles import ensure_profile

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


async def _exists(db: AsyncSession, query) -> bool:
    return await db.scalar(select(query.exists())) or False


@router.get("", response_model=OnboardingStatus)
async def onboarding_status(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    household = await db.get(Household, auth.household_id)
    if not household:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Household not found")

    has_account = await _exists(
        db,
        select(Account.id).where(
            Account.household_id == auth.household_id,
            Account.is_hidden.is_(False),
        ),
    )
    has_transaction = await _exists(
        db,
        select(Transaction.id).where(
            Transaction.household_id == auth.household_id
        ),
    )
    has_budget = await _exists(
        db, select(Budget.id).where(Budget.household_id == auth.household_id)
    )
    has_bank = await _exists(
        db,
        select(InstitutionConnection.id).where(
            InstitutionConnection.household_id == auth.household_id
        ),
    )
    member_count = (
        await db.scalar(
            select(func.count(HouseholdMember.id)).where(
                HouseholdMember.household_id == auth.household_id
            )
        )
    ) or 0
    has_open_invite = await _exists(
        db,
        select(HouseholdInvite.id).where(
            HouseholdInvite.household_id == auth.household_id,
            HouseholdInvite.accepted_at.is_(None),
            HouseholdInvite.expires_at > datetime.now(timezone.utc),
        ),
    )

    profile = await ensure_profile(db, auth.user)
    await db.commit()

    return OnboardingStatus(
        household_name=household.name,
        role=auth.role,
        dismissed=profile.onboarding_dismissed_at is not None,
        steps=[
            OnboardingStep(key="household", complete=True),
            OnboardingStep(key="account", complete=has_account),
            OnboardingStep(key="transactions", complete=has_transaction),
            OnboardingStep(key="budget", complete=has_budget),
            OnboardingStep(key="bank", complete=has_bank),
            OnboardingStep(
                key="partner", complete=member_count > 1 or has_open_invite
            ),
        ],
    )


@router.post("/dismiss", status_code=204)
async def dismiss_onboarding(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    profile = await ensure_profile(db, auth.user)
    profile.onboarding_dismissed_at = datetime.now(timezone.utc)
    await db.commit()


@router.post("/restore", status_code=204)
async def restore_onboarding(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    profile = await ensure_profile(db, auth.user)
    profile.onboarding_dismissed_at = None
    await db.commit()
