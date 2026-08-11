"""
Splitting one bank charge across several categories.

A $180 Costco run is groceries *and* household goods *and* a bit of clothing.
Forcing it into one category is the single most common reason a budget stops
matching reality, so a charge can be broken into lines that each carry their
own category, note, and tags.

The model is deliberately boring: **a split line is an ordinary transaction row**
that points at its parent. Every filter, export, report, and tag join in the
application already understands transaction rows, so none of them needed to
learn a new shape.

That leaves exactly one hazard, and it is the whole reason this module exists:

    the parent and its lines describe the same money.

Counting both doubles a household's spending. The defence is a single predicate,
`countable()`, applied at every aggregation site, plus `SPLIT_TOTAL_TOLERANCE`
below to guarantee the lines really do reconstruct the parent.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Category, Tag, Transaction

# Lines must reconstruct the parent exactly. Amounts are NUMERIC(18,2) and are
# validated as 2dp before they get here, so this is an equality check written
# defensively rather than a real tolerance.
SPLIT_TOTAL_TOLERANCE = Decimal("0.00")

MIN_SPLIT_LINES = 2
MAX_SPLIT_LINES = 40


class SplitError(ValueError):
    """A split that would not reconstruct its parent, stated for a person."""


def countable(model: type[Transaction] = Transaction):
    """
    The predicate every money aggregation must carry.

    A split parent is a container: its lines hold the categorized amounts, and
    summing both counts the same dollars twice. Import this rather than writing
    `Transaction.is_split.is_(False)` by hand — a single named rule is auditable,
    a dozen open-coded ones are a matter of time.
    """
    return model.is_split.is_(False)


def quantize(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(Decimal("0.01"))


def validate_lines(parent: Transaction, lines: list[dict]) -> list[dict]:
    """
    Check a proposed split before anything is written.

    Three rules, each of which has a reason a person would recognise:

    - The lines must sum to the parent. Otherwise the ledger stops agreeing
      with the bank, which is the one thing it must never do.
    - Every line must share the parent's sign. A "refund" line inside a
      purchase would land in income and quietly inflate earnings.
    - No zero lines. They add review work and mean nothing.
    """
    if len(lines) < MIN_SPLIT_LINES:
        raise SplitError("A split needs at least two lines.")
    if len(lines) > MAX_SPLIT_LINES:
        raise SplitError(f"A split can have at most {MAX_SPLIT_LINES} lines.")

    cleaned: list[dict] = []
    for index, line in enumerate(lines, start=1):
        amount = quantize(line["amount"])
        if amount == 0:
            raise SplitError(f"Line {index} is zero. Remove it or give it an amount.")
        if (amount > 0) != (parent.amount > 0):
            direction = "positive" if parent.amount > 0 else "negative"
            raise SplitError(
                f"Line {index} runs the wrong way. Every line of this "
                f"transaction must be {direction}, like the charge itself."
            )
        cleaned.append({**line, "amount": amount})

    total = sum(line["amount"] for line in cleaned)
    parent_amount = quantize(parent.amount)
    if abs(total - parent_amount) > SPLIT_TOTAL_TOLERANCE:
        # Compare magnitudes, not signed values. On a $100 purchase, lines
        # totalling $120 are *too much* — but signed arithmetic makes that a
        # positive difference and would tell the person to add another $20.
        # Signs are already known to match the charge, so this is safe.
        shortfall = quantize(abs(parent_amount) - abs(total))
        raise SplitError(
            f"The lines add up to {abs(total)}, but the transaction is "
            f"{abs(parent_amount)}. "
            f"{'Add' if shortfall > 0 else 'Remove'} {abs(shortfall)} "
            "to balance it."
        )
    return cleaned


async def load_for_split(
    db: AsyncSession, household_id: uuid.UUID, transaction_id: uuid.UUID
) -> Transaction:
    transaction = await db.scalar(
        select(Transaction)
        .options(selectinload(Transaction.splits))
        .where(
            Transaction.id == transaction_id,
            Transaction.household_id == household_id,
        )
    )
    if transaction is None:
        raise SplitError("Transaction not found.")
    if transaction.parent_transaction_id is not None:
        raise SplitError(
            "This is already one line of a split. Edit the original "
            "transaction to change how it is divided."
        )
    return transaction


async def _resolve(
    db: AsyncSession, household_id: uuid.UUID, lines: list[dict]
) -> None:
    """Reject foreign categories and tags before writing anything."""
    category_ids = {
        line["category_id"] for line in lines if line.get("category_id")
    }
    if category_ids:
        found = set(
            (
                await db.scalars(
                    select(Category.id).where(
                        Category.household_id == household_id,
                        Category.id.in_(category_ids),
                    )
                )
            ).all()
        )
        if found != category_ids:
            raise SplitError("A category on one of the lines does not exist.")

    tag_ids = {tag for line in lines for tag in line.get("tag_ids") or []}
    if tag_ids:
        found = set(
            (
                await db.scalars(
                    select(Tag.id).where(
                        Tag.household_id == household_id, Tag.id.in_(tag_ids)
                    )
                )
            ).all()
        )
        if found != tag_ids:
            raise SplitError("A tag on one of the lines does not exist.")


async def apply_split(
    db: AsyncSession,
    household_id: uuid.UUID,
    parent: Transaction,
    lines: list[dict],
) -> Transaction:
    """
    Replace a transaction's split with the given lines.

    Replace rather than patch: the editor always sends the whole set, so there
    is no partial state where the lines briefly fail to sum to the parent.
    """
    cleaned = validate_lines(parent, lines)
    await _resolve(db, household_id, cleaned)

    tag_lookup: dict[uuid.UUID, Tag] = {}
    wanted_tags = {tag for line in cleaned for tag in line.get("tag_ids") or []}
    if wanted_tags:
        tag_lookup = {
            tag.id: tag
            for tag in (
                await db.scalars(
                    select(Tag).where(
                        Tag.household_id == household_id, Tag.id.in_(wanted_tags)
                    )
                )
            ).all()
        }

    # Rebuilding the lines discards the old ones through delete-orphan.
    parent.splits.clear()
    await db.flush()

    for line in cleaned:
        child = Transaction(
            household_id=household_id,
            account_id=parent.account_id,
            parent_transaction_id=parent.id,
            category_id=line.get("category_id"),
            merchant_name=parent.merchant_name,
            original_description=parent.original_description,
            normalized_merchant=parent.normalized_merchant,
            amount=line["amount"],
            currency=parent.currency,
            posted_date=parent.posted_date,
            authorized_date=parent.authorized_date,
            pending=parent.pending,
            notes=line.get("notes"),
            excluded_from_budget=bool(line.get("excluded_from_budget", False)),
            is_transfer=parent.is_transfer,
            # Dividing a charge by hand is a categorization decision, so the
            # lines arrive reviewed rather than landing back in the queue.
            reviewed=True,
            categorization_source="split",
            provider_category=parent.provider_category,
        )
        if line.get("tag_ids"):
            child.tags = [
                tag_lookup[tag_id]
                for tag_id in line["tag_ids"]
                if tag_id in tag_lookup
            ]
        db.add(child)

    # The parent stops being a categorized amount and becomes a container. Its
    # own category would otherwise be counted by anything joining on category.
    parent.is_split = True
    parent.category_id = None
    parent.reviewed = True
    await db.flush()
    return parent


async def clear_split(db: AsyncSession, parent: Transaction) -> Transaction:
    """
    Fold a split back into a single transaction.

    The lines are discarded, so the parent returns to the review queue
    uncategorized rather than silently inheriting one line's category and
    looking like a decision somebody made.
    """
    if not parent.is_split:
        raise SplitError("That transaction is not split.")
    parent.splits.clear()
    parent.is_split = False
    parent.reviewed = False
    parent.categorization_source = None
    await db.flush()
    return parent
