import uuid
from dataclasses import dataclass
from decimal import Decimal

import regex
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    AccountKind,
    CategorizationRule,
    Category,
    CategoryGroup,
    RuleMatchType,
    Transaction,
)
from app.services import memory, provider_categories
from app.services.splits import countable
from app.services.merchants import normalize_merchant

__all__ = [
    "Rule",
    "categorize_uncategorized",
    "choose_category",
    "keyword_category",
    "match_rules",
    "normalize_merchant",
    "rule_matches",
]


@dataclass(frozen=True)
class Rule:
    category_id: uuid.UUID
    match_type: RuleMatchType
    pattern: str
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None


KEYWORD_CATEGORIES = {
    "grocer": ("costco", "kroger", "safeway", "whole foods", "trader joe"),
    "transport": ("shell", "chevron", "exxon", "uber", "lyft"),
    "utilities": ("electric", "water", "internet", "utility"),
    "subscription": ("netflix", "spotify", "apple.com/bill", "hulu"),
    "income": ("payroll", "salary", "direct deposit", "interest"),
}


def rule_matches(rule: Rule, merchant: str, amount: Decimal) -> bool:
    if rule.min_amount is not None and abs(amount) < rule.min_amount:
        return False
    if rule.max_amount is not None and abs(amount) > rule.max_amount:
        return False
    if rule.match_type == RuleMatchType.exact:
        return merchant == normalize_merchant(rule.pattern)
    if rule.match_type == RuleMatchType.regex:
        try:
            return bool(
                regex.search(
                    rule.pattern,
                    merchant[:512],
                    flags=regex.IGNORECASE,
                    timeout=0.02,
                    concurrent=True,
                )
            )
        except (regex.error, TimeoutError):
            return False
    return normalize_merchant(rule.pattern) in merchant


def match_rules(
    merchant: str, amount: Decimal, rules: list[Rule]
) -> uuid.UUID | None:
    """First matching household rule, in priority order."""
    normalized = normalize_merchant(merchant)
    for rule in rules:
        if rule_matches(rule, normalized, amount):
            return rule.category_id
    return None


def keyword_category(
    merchant: str, category_name_map: dict[str, uuid.UUID]
) -> tuple[uuid.UUID | None, str | None]:
    """
    The last deterministic resort: a small table of unmistakable merchants.

    Deliberately narrow. It runs after Plaid's category and after anything this
    household has decided, so its only job is the handful of cases where the
    merchant string alone is conclusive.
    """
    normalized = normalize_merchant(merchant)
    for keyword, aliases in KEYWORD_CATEGORIES.items():
        if any(alias in normalized for alias in aliases):
            candidates = [
                (name, category_id)
                for name, category_id in category_name_map.items()
                if keyword in name
                or (keyword == "grocer" and "food" in name)
                or (keyword == "transport" and "gas" in name)
            ]
            if candidates:
                return candidates[0][1], "keyword_model"
    return None, None


def choose_category(
    merchant: str,
    amount: Decimal,
    rules: list[Rule],
    category_name_map: dict[str, uuid.UUID],
) -> tuple[uuid.UUID | None, str | None]:
    """Rules, then keywords — the two signals that need no database access."""
    category_id = match_rules(merchant, amount, rules)
    if category_id:
        return category_id, "household_rule"
    return keyword_category(merchant, category_name_map)


async def _income_category_ids(
    db: AsyncSession, household_id: uuid.UUID
) -> frozenset[uuid.UUID]:
    """Categories that live under an income group, for sign checks."""
    rows = (
        await db.scalars(
            select(Category.id)
            .join(CategoryGroup, CategoryGroup.id == Category.group_id)
            .where(
                Category.household_id == household_id,
                CategoryGroup.is_income.is_(True),
            )
        )
    ).all()
    return frozenset(rows)


# What a person chose by hand, or decided by splitting. Nothing automatic may
# overwrite these — they are the only categorizations that came from a human
# looking at the transaction and deciding.
HUMAN_SOURCES = frozenset({"manual", "split"})


async def categorize_uncategorized(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    revisit_guesses: bool = False,
) -> int:
    """
    Deterministic categorization, cheapest and most trusted signal first:

        household rule  >  merchant memory  >  Plaid's category  >  keywords

    Nothing here calls a model. Whatever survives this pass is what the AI
    layer is later asked about, so the better this gets, the less there is to
    ask and the less there is to review.

    With `revisit_guesses`, rows that already carry a category are reconsidered
    as long as a *guess* put it there. This is what makes "always categorize
    Southwest like this" mean what it says: without it a new rule could only
    ever fill blanks, so every Southwest charge the AI or the keyword table had
    already labelled kept the wrong category and the rule looked broken. A
    category a person chose is still never overwritten.
    """
    db_rules = (
        await db.scalars(
            select(CategorizationRule)
            .where(
                CategorizationRule.household_id == household_id,
                CategorizationRule.is_active.is_(True),
            )
            .order_by(CategorizationRule.priority.asc())
        )
    ).all()
    rules = [
        Rule(
            category_id=item.category_id,
            match_type=item.match_type,
            pattern=item.merchant_pattern,
            min_amount=item.min_amount,
            max_amount=item.max_amount,
        )
        for item in db_rules
    ]
    categories = (
        await db.scalars(
            select(Category).where(Category.household_id == household_id)
        )
    ).all()
    name_map = {category.name.lower(): category.id for category in categories}
    income_ids = await _income_category_ids(db, household_id)
    liability_accounts = set(
        (
            await db.scalars(
                select(Account.id).where(
                    Account.household_id == household_id,
                    Account.kind == AccountKind.liability,
                )
            )
        ).all()
    )
    remembered = await memory.load(db, household_id)
    scope = [Transaction.household_id == household_id, countable()]
    if revisit_guesses:
        scope.append(
            or_(
                Transaction.category_id.is_(None),
                Transaction.categorization_source.is_(None),
                Transaction.categorization_source.not_in(HUMAN_SOURCES),
            )
        )
    else:
        scope.append(Transaction.category_id.is_(None))
    transactions = (
        # A split parent is uncategorized on purpose — its lines hold the
        # categories — and `countable()` keeps it out of both modes.
        await db.scalars(select(Transaction).where(*scope))
    ).all()

    changed = 0
    used_memories: set[str] = set()
    for transaction in transactions:
        label = transaction.merchant_name or transaction.original_description
        transaction.normalized_merchant = normalize_merchant(label)

        # Plaid can say outright that this is money moving between the
        # household's own accounts. Marking it keeps it out of cash flow and
        # budgets, where it would otherwise look like both income and spending.
        if provider_categories.is_account_transfer(transaction.provider_category):
            transaction.is_transfer = True
            transaction.excluded_from_budget = True

        category_id = match_rules(label, transaction.amount, rules)
        source = "household_rule" if category_id else None
        if category_id is None:
            key = memory.merchant_key(transaction)
            recalled = remembered.get(key)
            if recalled:
                category_id, decided_by = recalled
                # A remembered AI guess is still an AI guess. Labelling it as
                # such keeps it visibly unreviewed rather than laundering it
                # into something that looks settled.
                source = (
                    "ai" if decided_by == memory.AI_SOURCE else "merchant_memory"
                )
                used_memories.add(key)
        if category_id is None and transaction.provider_category:
            category_id = provider_categories.resolve(
                transaction.provider_category,
                name_map,
                income_ids,
                is_inflow=transaction.amount > 0,
            )
            source = "provider_category" if category_id else None
        if category_id is None:
            category_id, source = keyword_category(label, name_map)

        # The sign has to agree with the category, whatever chose it.
        #
        # This guard existed only in the AI path, and the deterministic paths
        # went without it — so "INTERNET PAYMENT - THANK YOU", a +$342.40 card
        # payment, matched the word "internet" and was filed as Utilities. A
        # positive amount in a spending category subtracts from that budget
        # every month, silently.
        #
        # A rule a person wrote by hand is exempt: if they say these belong
        # there, that is their ledger and their decision.
        if category_id is not None and source != "household_rule":
            inflow = transaction.amount > 0
            if (category_id in income_ids) != inflow:
                category_id, source = None, None
            elif inflow and transaction.account_id in liability_accounts:
                # Money arriving on a credit card is a payment or a refund.
                # Nobody is paid a wage into a card, so an income category
                # there is always wrong — and it was the most visible symptom
                # of the whole transfer problem, because the row kept saying
                # "Income" long after the totals had been fixed.
                if category_id in income_ids:
                    category_id, source = None, None

        if category_id and category_id != transaction.category_id:
            transaction.category_id = category_id
            transaction.categorization_source = source
            changed += 1
        elif category_id:
            # Same answer as before: keep the row, but let the source reflect
            # that a rule now backs it.
            transaction.categorization_source = source
    await memory.record_hits(db, household_id, used_memories)
    await db.commit()
    return changed
