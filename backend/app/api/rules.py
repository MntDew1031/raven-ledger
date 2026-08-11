import uuid

import regex
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    CategorizationRule,
    Category,
    RuleMatchType,
    Transaction,
)
from app.schemas import (
    RuleCreate,
    RulePreviewRequest,
    RulePreviewResponse,
    RulePreviewSample,
    RuleResponse,
    RuleRunResponse,
    RuleUpdate,
)
from app.security import AuthContext, current_auth
from app.services.categorizer import (
    HUMAN_SOURCES,
    Rule,
    normalize_merchant,
    rule_matches,
)
from app.services.security_audit import record_security_event
from app.worker import enqueue_job

router = APIRouter(prefix="/rules", tags=["rules"])

# Preview scans recent transactions in-process, so bound the work: a
# catastrophic user regex should waste a moment, not pin the API.
PREVIEW_SCAN_LIMIT = 1000
PREVIEW_SAMPLES = 5


def _require_editor(auth: AuthContext) -> None:
    if auth.role == "viewer":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "View-only household members cannot manage rules",
        )


def _validate_pattern(match_type: RuleMatchType, pattern: str) -> None:
    if match_type == RuleMatchType.regex:
        try:
            regex.compile(pattern)
        except regex.error as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Invalid regular expression: {exc}",
            ) from exc


async def _household_category(
    db: AsyncSession, household_id: uuid.UUID, category_id: uuid.UUID
) -> None:
    exists = await db.scalar(
        select(Category.id).where(
            Category.id == category_id,
            Category.household_id == household_id,
        )
    )
    if not exists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")


async def _household_rule(
    db: AsyncSession, household_id: uuid.UUID, rule_id: uuid.UUID
) -> CategorizationRule:
    rule = await db.scalar(
        select(CategorizationRule).where(
            CategorizationRule.id == rule_id,
            CategorizationRule.household_id == household_id,
        )
    )
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return rule


@router.get("", response_model=list[RuleResponse])
async def list_rules(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(CategorizationRule, Category.name)
        .join(Category, CategorizationRule.category_id == Category.id)
        .where(CategorizationRule.household_id == auth.household_id)
        .order_by(
            CategorizationRule.priority.asc(),
            CategorizationRule.created_at.asc(),
        )
    )
    return [
        RuleResponse(
            id=rule.id,
            name=rule.name,
            match_type=rule.match_type,
            merchant_pattern=rule.merchant_pattern,
            min_amount=rule.min_amount,
            max_amount=rule.max_amount,
            category_id=rule.category_id,
            category_name=category_name,
            priority=rule.priority,
            is_active=rule.is_active,
        )
        for rule, category_name in rows
    ]


@router.post("", response_model=RuleResponse, status_code=201)
async def create_rule(
    payload: RuleCreate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    _validate_pattern(payload.match_type, payload.merchant_pattern)
    await _household_category(db, auth.household_id, payload.category_id)
    if payload.priority is None:
        last = await db.scalar(
            select(func.max(CategorizationRule.priority)).where(
                CategorizationRule.household_id == auth.household_id
            )
        )
        priority = (last or 0) + 10
    else:
        priority = payload.priority
    rule = CategorizationRule(
        household_id=auth.household_id,
        name=payload.name,
        match_type=payload.match_type,
        merchant_pattern=payload.merchant_pattern,
        min_amount=payload.min_amount,
        max_amount=payload.max_amount,
        category_id=payload.category_id,
        priority=priority,
        is_active=payload.is_active,
    )
    db.add(rule)
    await db.flush()
    await record_security_event(
        db,
        "finance.rule_created",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"rule_id": rule.id, "match_type": rule.match_type.value},
    )
    await db.commit()
    await db.refresh(rule)
    category_name = await db.scalar(
        select(Category.name).where(Category.id == rule.category_id)
    )
    return RuleResponse(
        id=rule.id,
        name=rule.name,
        match_type=rule.match_type,
        merchant_pattern=rule.merchant_pattern,
        min_amount=rule.min_amount,
        max_amount=rule.max_amount,
        category_id=rule.category_id,
        category_name=category_name or "",
        priority=rule.priority,
        is_active=rule.is_active,
    )


@router.patch("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    payload: RuleUpdate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    rule = await _household_rule(db, auth.household_id, rule_id)
    fields = payload.model_fields_set
    match_type = payload.match_type if "match_type" in fields else rule.match_type
    pattern = (
        payload.merchant_pattern
        if "merchant_pattern" in fields
        else rule.merchant_pattern
    )
    _validate_pattern(match_type, pattern)
    if "category_id" in fields and payload.category_id:
        await _household_category(db, auth.household_id, payload.category_id)
    for field in (
        "name",
        "match_type",
        "merchant_pattern",
        "min_amount",
        "max_amount",
        "category_id",
        "priority",
        "is_active",
    ):
        if field in fields:
            value = getattr(payload, field)
            required_fields = {
                "name",
                "match_type",
                "merchant_pattern",
                "category_id",
                "priority",
                "is_active",
            }
            if value is None and field in required_fields:
                continue
            setattr(rule, field, value)
    await record_security_event(
        db,
        "finance.rule_updated",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "rule_id": rule.id,
            "fields": ",".join(sorted(fields)),
        },
    )
    await db.commit()
    await db.refresh(rule)
    category_name = await db.scalar(
        select(Category.name).where(Category.id == rule.category_id)
    )
    return RuleResponse(
        id=rule.id,
        name=rule.name,
        match_type=rule.match_type,
        merchant_pattern=rule.merchant_pattern,
        min_amount=rule.min_amount,
        max_amount=rule.max_amount,
        category_id=rule.category_id,
        category_name=category_name or "",
        priority=rule.priority,
        is_active=rule.is_active,
    )


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    rule = await _household_rule(db, auth.household_id, rule_id)
    await db.delete(rule)
    await record_security_event(
        db,
        "finance.rule_deleted",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"rule_id": rule.id},
    )
    await db.commit()


@router.post("/preview", response_model=RulePreviewResponse)
async def preview_rule(
    payload: RulePreviewRequest,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Which recent transactions a rule would match, before it is saved. Purely
    read-only, so it is available to every household member.
    """
    _validate_pattern(payload.match_type, payload.merchant_pattern)
    candidate = Rule(
        category_id=uuid.uuid4(),  # unused by matching
        match_type=payload.match_type,
        pattern=payload.merchant_pattern,
        min_amount=payload.min_amount,
        max_amount=payload.max_amount,
    )
    transactions = (
        await db.scalars(
            select(Transaction)
            .where(Transaction.household_id == auth.household_id)
            .order_by(Transaction.posted_date.desc())
            .limit(PREVIEW_SCAN_LIMIT)
        )
    ).all()
    matches = [
        item
        for item in transactions
        if rule_matches(
            candidate,
            normalize_merchant(
                item.merchant_name or item.original_description
            ),
            item.amount,
        )
    ]
    return RulePreviewResponse(
        scanned=len(transactions),
        matched=len(matches),
        uncategorized_matched=sum(
            1 for item in matches if item.category_id is None
        ),
        samples=[
            RulePreviewSample(
                merchant=item.merchant_name or item.original_description,
                amount=item.amount,
                posted_date=item.posted_date,
            )
            for item in matches[:PREVIEW_SAMPLES]
        ],
    )


@router.post("/run", response_model=RuleRunResponse, status_code=202)
async def run_rules(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-run the household's rules.

    This considers everything a rule is allowed to change, not just blanks. A
    rule written by hand outranks a guess, so a charge the AI or the keyword
    table already labelled is reconsidered; a category a person chose, and the
    lines of a split, are left alone.
    """
    _require_editor(auth)
    pending = (
        await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.household_id == auth.household_id,
                or_(
                    Transaction.category_id.is_(None),
                    Transaction.categorization_source.is_(None),
                    Transaction.categorization_source.not_in(HUMAN_SOURCES),
                ),
            )
        )
    ) or 0
    await enqueue_job("categorize_household", str(auth.household_id), True)
    await record_security_event(
        db,
        "automation.rules_queued",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"transactions": pending},
    )
    await db.commit()
    return RuleRunResponse(queued=pending)
