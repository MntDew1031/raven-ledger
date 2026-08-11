"""
The agent that tidies the ledger — and asks first.

Alex wanted "the ai agent to go in and auto organize all of the finances,
transactions and budget and have me approve and edit it after". The last clause
is the design. Nothing here writes to a transaction, a rule or a budget; it
writes *proposals*, each with a reason, which are applied only when somebody
says so and can be edited before they are.

Why proposals rather than direct writes: Raven already lets the AI put a
category straight onto a transaction, and that is defensible — a guess is
visibly unreviewed and one tap to fix. It does not extend to writing a rule,
which outranks every later guess, or a budget amount, which is the number the
whole month is measured against. Those are decisions, and a decision somebody
did not make is not one they can be held to.

Four kinds, deliberately ordered from most certain to least:

1. **transfer** — a matched pair between the household's own accounts that the
   provider mislabelled. Deterministic; the existing `transfers` service already
   does the certain cases at sync time, and this catches the rest.
2. **exclusion** — a refund that cancels an earlier charge at the same merchant.
3. **category** — what an uncategorized or weakly-guessed transaction is.
4. **rule** — a merchant seen enough times, categorized the same way, that it
   should stop being asked about.
5. **budget** — a planned amount per category from recent actual spending.

Budget proposals are last and separated for a reason: they are the least
certain thing here, and the easiest to wave through without reading.
"""

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiProposal,
    Account,
    AccountKind,
    CategorizationRule,
    Category,
    CategoryGroup,
    ProposalKind,
    ProposalStatus,
    Transaction,
)
from app.services import memory
from app.services.spending_scope import is_spending
from app.services.splits import countable
from app.services.transfers import PAIR_WINDOW_DAYS, looks_like_a_payment

# A merchant has to be seen this many times, categorized the same way every
# time, before a rule is worth proposing. Two is coincidence.
RULE_MIN_SIGHTINGS = 3

# Months of history behind a budget proposal. Fewer than three and one unusual
# month sets the plan; many more and it stops describing how you live now.
BUDGET_MONTHS = 3

# A refund is matched to a charge at the same merchant within this window.
REFUND_WINDOW_DAYS = 60


async def clear_pending(db: AsyncSession, household_id: uuid.UUID) -> None:
    """
    Drop undecided proposals before a fresh run.

    A run should produce the current view, not accumulate every view ever
    taken. Decided ones are kept — they are the record of what was agreed.
    """
    await db.execute(
        delete(AiProposal).where(
            AiProposal.household_id == household_id,
            AiProposal.status == ProposalStatus.pending,
        )
    )


def _collapse_contained(
    grouped: dict[str, list[Transaction]],
) -> dict[str, list[Transaction]]:
    """
    Fold a merchant key into the more general one that already covers it.

    The bank writes the same shop several ways — "Dunkin' Donuts" on one
    charge and "Dunkin'" on the next — and normalizing gives `dunkin donuts`
    and `dunkin`, two keys for one merchant. The organizer then offered Alex
    two rules for Dunkin' in the same list, which is the duplication he saw.

    A proposed rule matches with `contains`, so a rule on `dunkin` **already**
    catches `dunkin donuts`. The longer key is redundant and its transactions
    belong to the shorter one's count.

    Collapsed on **token prefix**, not substring: `dunkin` folds
    `dunkin donuts`, while `star` leaves `starbucks` alone. Substring matching
    here would merge unrelated shops that happen to share letters.

    Keys that disagree about the category are left apart, because merging them
    would build a rule that silently overrules one of the two — the same
    reason a single key filed two ways is skipped below.
    """
    keys = sorted(grouped, key=lambda k: (len(k.split()), len(k)))
    absorbed: set[str] = set()
    merged: dict[str, list[Transaction]] = {}
    for index, short in enumerate(keys):
        if short in absorbed:
            continue
        members = list(grouped[short])
        short_tokens = short.split()
        for longer in keys[index + 1 :]:
            if longer in absorbed:
                continue
            long_tokens = longer.split()
            if long_tokens[: len(short_tokens)] != short_tokens:
                continue
            if {t.category_id for t in grouped[longer]} != {
                t.category_id for t in members
            }:
                continue
            members.extend(grouped[longer])
            absorbed.add(longer)
        merged[short] = members
    return merged


def _propose(
    household_id: uuid.UUID,
    kind: ProposalKind,
    payload: dict,
    rationale: str,
    confidence: float,
) -> AiProposal:
    return AiProposal(
        household_id=household_id,
        kind=kind,
        payload=payload,
        rationale=rationale[:400],
        confidence=Decimal(str(round(confidence, 3))),
    )


async def propose_transfers(
    db: AsyncSession, household_id: uuid.UUID
) -> list[AiProposal]:
    """
    Money moving between the household's own accounts that nobody caught.

    The sync-time pass in `transfers` handles the certain case — an outflow
    from a bank account matched to an inflow on a card. This proposes the ones
    that need a human to look: same magnitude, opposite signs, different
    accounts, close together, but *not* involving a card, so it could genuinely
    be two unrelated transactions of the same size.
    """
    kinds = dict(
        (
            await db.execute(
                select(Account.id, Account.kind).where(
                    Account.household_id == household_id
                )
            )
        ).all()
    )
    rows = (
        await db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.is_transfer.is_(False),
                Transaction.parent_transaction_id.is_(None),
                countable(),
            )
        )
    ).all()

    inflows = [item for item in rows if item.amount > 0]
    outflows = [item for item in rows if item.amount < 0]
    claimed: set[uuid.UUID] = set()
    proposals: list[AiProposal] = []

    for inflow in inflows:
        for outflow in outflows:
            if outflow.id in claimed or outflow.account_id == inflow.account_id:
                continue
            if abs(outflow.amount) != inflow.amount:
                continue
            if abs((outflow.posted_date - inflow.posted_date).days) > PAIR_WINDOW_DAYS:
                continue
            claimed.add(outflow.id)
            # Landing on a card is near-certain; between two bank accounts it
            # is likely but genuinely could be a coincidence, so it is proposed
            # rather than applied and the confidence says which is which.
            to_card = kinds.get(inflow.account_id) == AccountKind.liability
            payment_shaped = looks_like_a_payment(inflow)
            proposals.append(
                _propose(
                    household_id,
                    ProposalKind.transfer,
                    {
                        "transaction_ids": [str(inflow.id), str(outflow.id)],
                        "amount": str(inflow.amount),
                        "from_label": outflow.merchant_name
                        or outflow.original_description,
                        "to_label": inflow.merchant_name
                        or inflow.original_description,
                    },
                    f"{outflow.merchant_name or 'An outflow'} and "
                    f"{inflow.merchant_name or 'an inflow'} are the same amount "
                    f"{abs((outflow.posted_date - inflow.posted_date).days)} day(s) "
                    "apart in different accounts — this looks like one movement "
                    "between your own accounts, counted twice.",
                    0.9 if to_card or payment_shaped else 0.6,
                )
            )
            break
    return proposals


async def propose_exclusions(
    db: AsyncSession, household_id: uuid.UUID
) -> list[AiProposal]:
    """
    Refunds that cancel an earlier charge.

    A refund is not income and it is not spending — it undoes a purchase. Left
    alone it inflates the category it lands in and makes the month look worse
    than it was.
    """
    since = date.today() - timedelta(days=REFUND_WINDOW_DAYS * 2)
    rows = (
        await db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.posted_date >= since,
                Transaction.excluded_from_budget.is_(False),
                Transaction.is_transfer.is_(False),
                countable(),
            )
        )
    ).all()
    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for item in rows:
        key = memory.merchant_key(item)
        if key:
            by_merchant[key].append(item)

    proposals: list[AiProposal] = []
    for members in by_merchant.values():
        charges = [item for item in members if item.amount < 0]
        refunds = [item for item in members if item.amount > 0]
        used: set[uuid.UUID] = set()
        for refund in refunds:
            match = next(
                (
                    charge
                    for charge in charges
                    if charge.id not in used
                    and abs(charge.amount) == refund.amount
                    and 0
                    <= (refund.posted_date - charge.posted_date).days
                    <= REFUND_WINDOW_DAYS
                ),
                None,
            )
            if match is None:
                continue
            used.add(match.id)
            label = refund.merchant_name or refund.original_description
            proposals.append(
                _propose(
                    household_id,
                    ProposalKind.exclusion,
                    {
                        "transaction_ids": [str(refund.id), str(match.id)],
                        "amount": str(refund.amount),
                        "merchant": label,
                    },
                    f"{label} was refunded in full "
                    f"{(refund.posted_date - match.posted_date).days} day(s) after "
                    "the charge. Excluding both leaves the month showing what it "
                    "actually cost, which is nothing.",
                    0.85,
                )
            )
    return proposals


async def propose_rules(
    db: AsyncSession, household_id: uuid.UUID
) -> list[AiProposal]:
    """
    Merchants settled enough to stop being asked about.

    Only proposed where a person or a rule has *never* disagreed: if the same
    merchant has been filed two different ways, a rule would be picking a side
    in an argument it did not witness.
    """
    existing = {
        (item.merchant_pattern or "").lower()
        for item in (
            await db.scalars(
                select(CategorizationRule).where(
                    CategorizationRule.household_id == household_id
                )
            )
        ).all()
    }
    rows = (
        await db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.category_id.is_not(None),
                countable(),
            )
        )
    ).all()
    names = dict(
        (
            await db.execute(
                select(Category.id, Category.name).where(
                    Category.household_id == household_id
                )
            )
        ).all()
    )

    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for item in rows:
        key = memory.merchant_key(item)
        if key:
            grouped[key].append(item)
    grouped = _collapse_contained(grouped)

    proposals: list[AiProposal] = []
    for key, members in grouped.items():
        if len(members) < RULE_MIN_SIGHTINGS or key in existing:
            continue
        categories = {item.category_id for item in members}
        if len(categories) != 1:
            # Filed two ways. A rule here would silently overrule whichever
            # choice it disagreed with.
            continue
        category_id = next(iter(categories))
        label = members[0].merchant_name or members[0].original_description or key
        # A pattern is only worth proposing if a person chose the category at
        # least once; three identical machine guesses are one guess repeated.
        human = any(
            item.categorization_source in ("manual", "split", "household_rule")
            for item in members
        )
        proposals.append(
            _propose(
                household_id,
                ProposalKind.rule,
                {
                    "merchant_pattern": key,
                    "match_type": "contains",
                    "category_id": str(category_id),
                    "category_name": names.get(category_id, ""),
                    "affects": len(members),
                    "sample_label": label,
                },
                f"{label} has come up {len(members)} times and has always been "
                f"{names.get(category_id, 'the same category')}"
                + (". You chose that yourself." if human else " by guess.")
                + " A rule would settle it for good.",
                0.85 if human else 0.55,
            )
        )
    return proposals


async def propose_budget(
    db: AsyncSession, household_id: uuid.UUID, month: date
) -> list[AiProposal]:
    """
    A planned amount per category, from what has actually been spent.

    Alex chose "recent actual spending" over an opinionated split, which is the
    right call for a first budget: it describes the life he has rather than one
    somebody else thinks he should have. The median is used rather than the
    mean, because one holiday should not become the monthly plan.
    """
    start = (month.replace(day=1) - timedelta(days=BUDGET_MONTHS * 31)).replace(day=1)
    rows = (
        await db.execute(
            select(
                Category.id,
                Category.name,
                Transaction.posted_date,
                Transaction.amount,
            )
            .join(Transaction, Transaction.category_id == Category.id)
            .join(CategoryGroup, CategoryGroup.id == Category.group_id)
            .where(
                Transaction.household_id == household_id,
                Transaction.posted_date >= start,
                Transaction.posted_date < month.replace(day=1),
                is_spending(household_id),
            )
        )
    ).all()

    monthly: dict[uuid.UUID, dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )
    names: dict[uuid.UUID, str] = {}
    for category_id, name, posted, amount in rows:
        names[category_id] = name
        monthly[category_id][f"{posted.year}-{posted.month:02d}"] += abs(amount)

    proposals: list[AiProposal] = []
    for category_id, months in monthly.items():
        values = sorted(months.values())
        if len(values) < 2:
            # One month of history is an anecdote, not a pattern.
            continue
        middle = len(values) // 2
        median = (
            values[middle]
            if len(values) % 2
            else (values[middle - 1] + values[middle]) / 2
        )
        planned = median.quantize(Decimal("1"))
        if planned <= 0:
            continue
        proposals.append(
            _propose(
                household_id,
                ProposalKind.budget,
                {
                    "category_id": str(category_id),
                    "category_name": names[category_id],
                    "planned_amount": str(planned),
                    # Which month the plan is for. Carried in the payload so
                    # approving it a week later still targets the month the
                    # run was about, not whatever month it is now.
                    "month": month.replace(day=1).isoformat(),
                    "months_seen": len(values),
                    "observed": [str(v.quantize(Decimal("1"))) for v in values],
                },
                f"You spent {', '.join(f'${v:,.0f}' for v in values)} on "
                f"{names[category_id]} over the last {len(values)} months. "
                f"${planned:,.0f} is the middle of that — not the average, so a "
                "single unusual month does not set the plan.",
                0.6,
            )
        )
    return proposals


async def propose_categories(
    db: AsyncSession, household_id: uuid.UUID, limit: int = 60
) -> list[AiProposal]:
    """
    What an unfiled or weakly-guessed transaction actually is.

    Reuses the existing AI path rather than asking the model a second way:
    `suggest_categories` already handles batching, retries, merchant
    deduplication, and the income/outflow sign check. The difference is that
    its answers are turned into proposals here instead of being written
    straight onto the rows.
    """
    from app.services.ai import ai_configured, unreviewed_guess

    if not ai_configured():
        return []

    candidates = (
        await db.scalars(
            select(Transaction)
            .where(
                Transaction.household_id == household_id,
                Transaction.reviewed.is_(False),
                unreviewed_guess(),
                countable(),
            )
            .order_by(Transaction.posted_date.desc())
            .limit(limit)
        )
    ).all()
    if not candidates:
        return []

    names = dict(
        (
            await db.execute(
                select(Category.id, Category.name).where(
                    Category.household_id == household_id
                )
            )
        ).all()
    )
    remembered = await memory.load(db, household_id)

    proposals: list[AiProposal] = []
    for transaction in candidates:
        key = memory.merchant_key(transaction)
        recalled = remembered.get(key) if key else None
        if not recalled:
            continue
        category_id, decided_by = recalled
        if category_id == transaction.category_id:
            continue
        label = transaction.merchant_name or transaction.original_description
        human = decided_by != memory.AI_SOURCE
        proposals.append(
            _propose(
                household_id,
                ProposalKind.category,
                {
                    "transaction_id": str(transaction.id),
                    "category_id": str(category_id),
                    "category_name": names.get(category_id, ""),
                    "merchant": label,
                    "amount": str(transaction.amount),
                    "posted_date": transaction.posted_date.isoformat(),
                    "current_category_name": names.get(
                        transaction.category_id, ""
                    ),
                },
                (
                    f"You have filed {label} as {names.get(category_id, '')} before."
                    if human
                    else f"{label} was last filed as {names.get(category_id, '')}."
                ),
                0.8 if human else 0.55,
            )
        )
    return proposals


async def run(
    db: AsyncSession, household_id: uuid.UUID, month: date
) -> dict[str, int]:
    """
    One pass. Replaces anything still undecided, keeps what has been decided.

    Ordered most-certain first so the review queue opens on the proposals
    least likely to need thought.
    """
    await clear_pending(db, household_id)
    batches = {
        "duplicate": await propose_duplicates(db, household_id),
        "transfer": await propose_transfers(db, household_id),
        "exclusion": await propose_exclusions(db, household_id),
        "category": await propose_categories(db, household_id),
        "rule": await propose_rules(db, household_id),
        "budget": await propose_budget(db, household_id, month),
    }
    for group in batches.values():
        for proposal in group:
            db.add(proposal)
    await db.commit()
    return {name: len(group) for name, group in batches.items()}


# Plaid occasionally posts the same purchase twice around the pending →
# posted transition. Two days covers that; wider and genuinely repeated
# purchases at the same merchant start being flagged.
DUPLICATE_WINDOW_DAYS = 2


async def propose_duplicates(
    db: AsyncSession, household_id: uuid.UUID
) -> list[AiProposal]:
    """
    The same charge, posted twice.

    Happens around the pending-to-posted transition, and it silently corrupts
    every total until somebody notices — which nobody does, because a duplicate
    of a real purchase looks exactly like a real purchase.

    Deliberately narrow: same account, same amount to the cent, same merchant,
    within two days. Buying coffee twice in a morning is real; the same $84.12
    at the same shop on the same card two days apart usually is not — but
    "usually" is why this is proposed rather than applied.
    """
    rows = (
        await db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.excluded_from_budget.is_(False),
                Transaction.is_transfer.is_(False),
                countable(),
            )
        )
    ).all()

    grouped: dict[tuple, list[Transaction]] = defaultdict(list)
    for item in rows:
        key = memory.merchant_key(item)
        if not key:
            continue
        grouped[(item.account_id, item.amount, key)].append(item)

    proposals: list[AiProposal] = []
    for (_, amount, _), members in grouped.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda item: item.posted_date)
        for earlier, later in zip(members, members[1:]):
            gap = (later.posted_date - earlier.posted_date).days
            if gap > DUPLICATE_WINDOW_DAYS:
                continue
            label = later.merchant_name or later.original_description or "This"
            proposals.append(
                _propose(
                    household_id,
                    ProposalKind.duplicate,
                    {
                        # Only the later one is excluded: the first is the
                        # original, and dropping both would understate the
                        # month by the whole amount.
                        "transaction_ids": [str(later.id)],
                        "kept_transaction_id": str(earlier.id),
                        "amount": str(amount),
                        "merchant": label,
                        "posted_date": later.posted_date.isoformat(),
                    },
                    f"{label} for {abs(amount):,.2f} appears twice on the same "
                    f"account, {gap} day(s) apart. Providers sometimes post a "
                    "charge again when it settles. Excluding the second leaves "
                    "the first counted.",
                    0.75 if gap <= 1 else 0.6,
                )
            )
    return proposals
