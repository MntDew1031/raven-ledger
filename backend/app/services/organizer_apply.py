"""
Applying a proposal somebody approved.

Kept apart from the code that *makes* proposals, because these are the only
functions here that change the ledger and they deserve to be read on their own.

Two rules hold throughout:

1. **Apply exactly what was on screen.** Approval acts on `payload`, which is
   rewritten when somebody edits a proposal before accepting it. Re-deriving
   anything at apply time would mean approving one thing and getting another.

2. **Re-check the world first.** A proposal is a statement about the ledger as
   it was when the run happened. Transactions get deleted, categories get
   renamed, someone else may have filed the same row by hand in between. Every
   apply verifies its target still exists and still looks the way it did; if
   not it is marked `stale` rather than forced through.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiProposal,
    Budget,
    BudgetLine,
    CategorizationRule,
    Category,
    ProposalKind,
    ProposalStatus,
    RuleMatchType,
    Transaction,
)
from app.services.budgets import month_start


class StaleProposal(RuntimeError):
    """The ledger moved on. Nothing was changed."""


async def apply_proposal(
    db: AsyncSession, proposal: AiProposal, user_id: uuid.UUID
) -> None:
    handlers = {
        ProposalKind.category: _apply_category,
        ProposalKind.transfer: _apply_transfer,
        ProposalKind.exclusion: _apply_exclusion,
        # A duplicate is excluded rather than deleted: the row is real, the
        # provider really sent it, and destroying bank data to tidy a total is
        # not a trade worth making.
        ProposalKind.duplicate: _apply_exclusion,
        ProposalKind.rule: _apply_rule,
        ProposalKind.budget: _apply_budget,
    }
    handler = handlers.get(proposal.kind)
    if handler is None:  # pragma: no cover - the enum is closed
        raise StaleProposal("Raven no longer knows how to apply this.")
    await handler(db, proposal)
    proposal.status = ProposalStatus.approved
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decided_by_user_id = user_id


async def _load_transactions(
    db: AsyncSession, proposal: AiProposal, ids: list[str]
) -> list[Transaction]:
    rows = (
        await db.scalars(
            select(Transaction).where(
                Transaction.id.in_([uuid.UUID(value) for value in ids]),
                Transaction.household_id == proposal.household_id,
            )
        )
    ).all()
    if len(rows) != len(ids):
        raise StaleProposal(
            "One of these transactions is gone. Run the organizer again."
        )
    return list(rows)


async def _apply_category(db: AsyncSession, proposal: AiProposal) -> None:
    payload = proposal.payload
    transaction = (
        await _load_transactions(db, proposal, [payload["transaction_id"]])
    )[0]
    category_id = uuid.UUID(payload["category_id"])
    category = await db.get(Category, category_id)
    if category is None or category.household_id != proposal.household_id:
        raise StaleProposal("That category no longer exists.")
    transaction.category_id = category_id
    # Approved by a person, so it is a person's decision from here on and no
    # later guess may overwrite it. This is the whole difference between the
    # organizer and the AI writing directly.
    transaction.categorization_source = "manual"


async def _apply_transfer(db: AsyncSession, proposal: AiProposal) -> None:
    for transaction in await _load_transactions(
        db, proposal, proposal.payload["transaction_ids"]
    ):
        # Both flags together, always: the reports read is_transfer and the
        # older queries read excluded_from_budget, and setting one without the
        # other hides a row from one screen while leaving it on another.
        transaction.is_transfer = True
        transaction.excluded_from_budget = True


async def _apply_exclusion(db: AsyncSession, proposal: AiProposal) -> None:
    for transaction in await _load_transactions(
        db, proposal, proposal.payload["transaction_ids"]
    ):
        transaction.excluded_from_budget = True


async def _apply_rule(db: AsyncSession, proposal: AiProposal) -> None:
    payload = proposal.payload
    category_id = uuid.UUID(payload["category_id"])
    category = await db.get(Category, category_id)
    if category is None or category.household_id != proposal.household_id:
        raise StaleProposal("That category no longer exists.")
    pattern = str(payload["merchant_pattern"]).strip()
    if not pattern:
        raise StaleProposal("A rule needs something to match on.")
    existing = await db.scalar(
        select(CategorizationRule).where(
            CategorizationRule.household_id == proposal.household_id,
            CategorizationRule.merchant_pattern == pattern,
        )
    )
    if existing is not None:
        # Somebody wrote it themselves in the meantime. Their version wins.
        raise StaleProposal(f"There is already a rule for {pattern}.")
    highest = await db.scalar(
        select(CategorizationRule.priority)
        .where(CategorizationRule.household_id == proposal.household_id)
        .order_by(CategorizationRule.priority.desc())
        .limit(1)
    )
    db.add(
        CategorizationRule(
            household_id=proposal.household_id,
            name=f"{payload.get('sample_label') or pattern} → {category.name}",
            match_type=RuleMatchType(payload.get("match_type", "contains")),
            merchant_pattern=pattern,
            category_id=category_id,
            # Last, so a rule accepted from a suggestion never silently
            # outranks one the household wrote deliberately.
            priority=(highest or 0) + 1,
            is_active=True,
        )
    )


async def _apply_budget(db: AsyncSession, proposal: AiProposal) -> None:
    payload = proposal.payload
    category_id = uuid.UUID(payload["category_id"])
    category = await db.get(Category, category_id)
    if category is None or category.household_id != proposal.household_id:
        raise StaleProposal("That category no longer exists.")
    raw = payload.get("month")
    if not raw:
        raise StaleProposal("This proposal does not say which month.")
    month = month_start(date.fromisoformat(str(raw)))
    budget = await db.scalar(
        select(Budget).where(
            Budget.household_id == proposal.household_id, Budget.month == month
        )
    )
    if budget is None:
        budget = Budget(household_id=proposal.household_id, month=month)
        db.add(budget)
        await db.flush()
    line = await db.scalar(
        select(BudgetLine).where(
            BudgetLine.budget_id == budget.id,
            BudgetLine.category_id == category_id,
        )
    )
    amount = Decimal(str(payload["planned_amount"]))
    if line is None:
        db.add(
            BudgetLine(
                budget_id=budget.id,
                category_id=category_id,
                planned_amount=amount,
            )
        )
    else:
        line.planned_amount = amount
