"""
Merchant memory: the household's own decisions, reused.

The categorizer used to be stateless. Every month a fresh batch of Trader
Joe's charges arrived, and every month a rule, a keyword table, or a language
model worked out again what a person had already decided in January. That is
the difference between a system that is accurate and one that gets more
accurate, and it is what this module fixes.

Reading is cheap and exact: one indexed lookup on a normalized merchant key,
no inference involved. Writing happens as a by-product of ordinary review, so
nobody has to maintain anything. Precedence is deliberate:

    household rule  >  merchant memory  >  Plaid's category  >  keywords  >  AI

Rules sit above memory because they are authored on purpose and a person
expects them to win. Memory sits above everything else because a decision this
household actually made beats any guess about what it might want.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, MerchantMemory, Transaction
from app.services.merchants import normalize_merchant

# A model's guess is worth remembering only so the same guess is not paid for
# twice. It must never overwrite what a person chose.
AI_SOURCE = "ai"
HUMAN_SOURCE = "human"


def merchant_key(transaction: Transaction) -> str:
    """
    The key everything matches on. Normalizing here rather than trusting
    `normalized_merchant` means memories written before a transaction was
    normalized still line up with ones written after.
    """
    raw = (
        transaction.normalized_merchant
        or transaction.merchant_name
        or transaction.original_description
        or ""
    )
    return normalize_merchant(raw)[:255]


async def remember(
    db: AsyncSession,
    household_id: uuid.UUID,
    transaction: Transaction,
    *,
    source: str = HUMAN_SOURCE,
) -> None:
    """
    Record what this household decided about a merchant.

    Does not commit: this is called from inside request handlers that own the
    transaction boundary.
    """
    key = merchant_key(transaction)
    if not key or transaction.category_id is None:
        return

    values = {
        "household_id": household_id,
        "merchant_key": key,
        "category_id": transaction.category_id,
        "sample_label": (
            transaction.merchant_name or transaction.original_description
        )[:255],
        "source": source,
        "hits": 0,
    }
    statement = insert(MerchantMemory).values(**values)
    if source == HUMAN_SOURCE:
        statement = statement.on_conflict_do_update(
            index_elements=["household_id", "merchant_key"],
            set_={
                "category_id": statement.excluded.category_id,
                "sample_label": statement.excluded.sample_label,
                "source": HUMAN_SOURCE,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    else:
        # A model may fill a gap but never correct a person.
        statement = statement.on_conflict_do_nothing(
            index_elements=["household_id", "merchant_key"]
        )
    await db.execute(statement)


async def forget(
    db: AsyncSession, household_id: uuid.UUID, key: str
) -> None:
    memory = await db.scalar(
        select(MerchantMemory).where(
            MerchantMemory.household_id == household_id,
            MerchantMemory.merchant_key == key,
        )
    )
    if memory:
        await db.delete(memory)


async def load(
    db: AsyncSession, household_id: uuid.UUID
) -> dict[str, tuple[uuid.UUID, str]]:
    """
    Every remembered merchant, as key -> (category id, who decided it).

    The source travels with the decision because it changes how the result is
    presented: a category a person chose is settled, while one only a model
    ever chose is still a suggestion and must keep saying so.
    """
    rows = (
        await db.execute(
            select(
                MerchantMemory.merchant_key,
                MerchantMemory.category_id,
                MerchantMemory.source,
            ).where(MerchantMemory.household_id == household_id)
        )
    ).all()
    return {key: (category_id, source) for key, category_id, source in rows}


async def examples(
    db: AsyncSession, household_id: uuid.UUID, limit: int = 24
) -> list[tuple[str, str]]:
    """
    A sample of this household's own decisions, as (merchant, category) pairs.

    Shown to the model so it matches house style rather than a generic idea of
    what a category means — whether Costco is groceries or general shopping is
    a question only this household's history answers.
    """
    rows = (
        await db.execute(
            select(MerchantMemory.sample_label, Category.name)
            .join(Category, Category.id == MerchantMemory.category_id)
            .where(
                MerchantMemory.household_id == household_id,
                MerchantMemory.sample_label.is_not(None),
            )
            .order_by(MerchantMemory.updated_at.desc())
            .limit(limit)
        )
    ).all()
    return [(label[:60], name) for label, name in rows if label]


async def record_hits(
    db: AsyncSession, household_id: uuid.UUID, keys: set[str]
) -> None:
    """
    Note that a memory earned its keep. Purely observational — it is what
    makes a stale or never-used memory visible later rather than invisible
    forever.
    """
    if not keys:
        return
    now = datetime.now(timezone.utc)
    memories = (
        await db.scalars(
            select(MerchantMemory).where(
                MerchantMemory.household_id == household_id,
                MerchantMemory.merchant_key.in_(keys),
            )
        )
    ).all()
    for entry in memories:
        entry.hits += 1
        entry.last_applied_at = now
