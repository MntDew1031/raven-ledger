"""
Disposable copies of a whole ledger.

Alex described the thing he actually wanted precisely: duplicating a sheet in
a spreadsheet, doing whatever he likes to the copy, then throwing it away. Not
a what-if budget layered over real data — a **separate ledger**, several at a
time, created and destroyed at will.

That maps onto cloning a household, which is lucky rather than clever: every
financial table here is already household-scoped, so a copy is a new household
row with copies hanging off it, and destroying one is a cascade delete rather
than a bespoke teardown that could miss a table next time somebody adds one.

**The rule that shapes everything below: a sandbox must never be able to touch
a bank.** `institution_connections` are not copied, so a clone holds no
provider tokens, cannot sync, and cannot be mistaken for the live ledger by the
worker. Its accounts arrive as manual copies of the balances at the moment of
cloning — which is exactly what a spreadsheet duplicate is.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    AssistantMemory,
    Goal,
    IncomeSource,
    Budget,
    BudgetLine,
    CategorizationRule,
    Category,
    CategoryGroup,
    Household,
    HouseholdMember,
    HouseholdRole,
    MerchantMemory,
    Tag,
    Transaction,
)

# Enough to experiment freely, few enough that a runaway loop cannot fill the
# disk with copies of a real ledger.
MAX_SANDBOXES = 8


class SandboxError(RuntimeError):
    """Something a person should be told about, in their own words."""


async def list_ledgers(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """Every ledger this person can open, real one first."""
    rows = (
        await db.execute(
            select(Household, HouseholdMember.role)
            .join(HouseholdMember, HouseholdMember.household_id == Household.id)
            .where(HouseholdMember.user_id == user_id)
            .order_by(Household.is_sandbox.asc(), Household.created_at.asc())
        )
    ).all()
    return [
        {
            "id": household.id,
            "name": household.name,
            "role": role.value if hasattr(role, "value") else str(role),
            "is_sandbox": household.is_sandbox,
            "cloned_from_id": household.cloned_from_id,
            "cloned_at": household.cloned_at,
        }
        for household, role in rows
    ]


async def create_sandbox(
    db: AsyncSession,
    source_household_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str | None = None,
) -> Household:
    """
    Copy a ledger into a new sandbox this person owns.

    Ids are remapped as we go — a category copy has to point at the copied
    group, a transaction at the copied account — so nothing in the sandbox ever
    references a row belonging to the real ledger. That is what makes deleting
    it safe.
    """
    source = await db.get(Household, source_household_id)
    if source is None:
        raise SandboxError("That ledger no longer exists.")
    if source.is_sandbox:
        raise SandboxError(
            "This is already a sandbox. Copy your real ledger instead, so the "
            "numbers start from something true."
        )

    existing = len(
        (
            await db.scalars(
                select(Household.id)
                .join(HouseholdMember, HouseholdMember.household_id == Household.id)
                .where(
                    HouseholdMember.user_id == user_id,
                    Household.is_sandbox.is_(True),
                )
            )
        ).all()
    )
    if existing >= MAX_SANDBOXES:
        raise SandboxError(
            f"You already have {existing} sandboxes. Delete one before making "
            "another."
        )

    sandbox = Household(
        name=(name or await _default_name(db, source, user_id))[:120],
        currency=source.currency,
        timezone=source.timezone,
        is_sandbox=True,
        cloned_from_id=source.id,
        cloned_at=datetime.now(timezone.utc),
    )
    db.add(sandbox)
    await db.flush()

    db.add(
        HouseholdMember(
            household_id=sandbox.id,
            user_id=user_id,
            # Whoever makes a sandbox owns it outright. It is theirs to wreck.
            role=HouseholdRole.owner,
        )
    )

    groups: dict[uuid.UUID, uuid.UUID] = {}
    for group in await _all(db, CategoryGroup, source.id):
        copy = CategoryGroup(
            household_id=sandbox.id,
            name=group.name,
            is_income=group.is_income,
            sort_order=group.sort_order,
        )
        db.add(copy)
        await db.flush()
        groups[group.id] = copy.id

    categories: dict[uuid.UUID, uuid.UUID] = {}
    for category in await _all(db, Category, source.id):
        copy = Category(
            household_id=sandbox.id,
            group_id=groups.get(category.group_id),
            name=category.name,
            color=category.color,
            icon=category.icon,
            flex_bucket=category.flex_bucket,
        )
        db.add(copy)
        await db.flush()
        categories[category.id] = copy.id

    accounts: dict[uuid.UUID, uuid.UUID] = {}
    for account in await _all(db, Account, source.id):
        copy = Account(
            household_id=sandbox.id,
            # No connection and no provider id: a sandbox holds no bank
            # credentials and must never be able to sync. The balance is a
            # snapshot of this moment, like a duplicated spreadsheet.
            connection_id=None,
            provider_account_id=None,
            is_manual=True,
            name=account.name,
            official_name=account.official_name,
            institution_name=account.institution_name,
            mask=account.mask,
            type=account.type,
            subtype=account.subtype,
            kind=account.kind,
            current_balance=account.current_balance,
            available_balance=account.available_balance,
            credit_limit=account.credit_limit,
            currency=account.currency,
            is_on_budget=account.is_on_budget,
            is_hidden=account.is_hidden,
            # Carried across so per-person figures in a sandbox match the real
            # ledger's. Without it, two identically named cards become
            # indistinguishable the moment you copy them.
            owner_user_id=account.owner_user_id,
        )
        db.add(copy)
        await db.flush()
        accounts[account.id] = copy.id

    tags: dict[uuid.UUID, uuid.UUID] = {}
    for tag in await _all(db, Tag, source.id):
        copy = Tag(household_id=sandbox.id, name=tag.name, color=tag.color)
        db.add(copy)
        await db.flush()
        tags[tag.id] = copy.id

    # Parents before their split lines, so a line always has a parent to point
    # at by the time it is written.
    originals = sorted(
        await _all(db, Transaction, source.id),
        key=lambda item: item.parent_transaction_id is not None,
    )
    transactions: dict[uuid.UUID, uuid.UUID] = {}
    for transaction in originals:
        account_id = accounts.get(transaction.account_id)
        if account_id is None:
            continue
        copy = Transaction(
            household_id=sandbox.id,
            account_id=account_id,
            category_id=categories.get(transaction.category_id),
            parent_transaction_id=transactions.get(
                transaction.parent_transaction_id
            ),
            is_split=transaction.is_split,
            # The provider id is dropped along with the connection: nothing in
            # a sandbox should look like it came from a bank.
            provider_transaction_id=None,
            merchant_name=transaction.merchant_name,
            original_description=transaction.original_description,
            normalized_merchant=transaction.normalized_merchant,
            amount=transaction.amount,
            currency=transaction.currency,
            posted_date=transaction.posted_date,
            # Carried, or a what-if copy would put rent back in the month it
            # posted and disagree with the ledger it was cloned from.
            budget_month=transaction.budget_month,
            authorized_date=transaction.authorized_date,
            pending=transaction.pending,
            excluded_from_budget=transaction.excluded_from_budget,
            is_transfer=transaction.is_transfer,
            notes=transaction.notes,
            reviewed=transaction.reviewed,
            categorization_source=transaction.categorization_source,
            provider_category=transaction.provider_category,
        )
        db.add(copy)
        await db.flush()
        transactions[transaction.id] = copy.id

    for budget in await _all(db, Budget, source.id):
        copy = Budget(
            household_id=sandbox.id, month=budget.month, mode=budget.mode
        )
        db.add(copy)
        await db.flush()
        lines = (
            await db.scalars(
                select(BudgetLine).where(BudgetLine.budget_id == budget.id)
            )
        ).all()
        for line in lines:
            category_id = categories.get(line.category_id)
            if category_id is None:
                continue
            db.add(
                BudgetLine(
                    budget_id=copy.id,
                    category_id=category_id,
                    planned_amount=line.planned_amount,
                    rollover_enabled=line.rollover_enabled,
                    rollover_amount=line.rollover_amount,
                    non_monthly_target=line.non_monthly_target,
                    non_monthly_due_date=line.non_monthly_due_date,
                )
            )

    for rule in await _all(db, CategorizationRule, source.id):
        category_id = categories.get(rule.category_id)
        if category_id is None:
            continue
        db.add(
            CategorizationRule(
                household_id=sandbox.id,
                name=rule.name,
                match_type=rule.match_type,
                merchant_pattern=rule.merchant_pattern,
                min_amount=rule.min_amount,
                max_amount=rule.max_amount,
                category_id=category_id,
                priority=rule.priority,
                is_active=rule.is_active,
            )
        )

    # Income sources and goals were added after this function was written, and
    # a sandbox that omits them is not the "full copy of your ledger" it says
    # it is: the budget opens with no expected income and the forecast has no
    # paydays, which are exactly the things a what-if is about.
    for earner in await _all(db, IncomeSource, source.id):
        db.add(
            IncomeSource(
                household_id=sandbox.id,
                name=earner.name,
                amount=earner.amount,
                cadence=earner.cadence,
                is_active=earner.is_active,
                notes=earner.notes,
            )
        )

    for goal in await _all(db, Goal, source.id):
        db.add(
            Goal(
                household_id=sandbox.id,
                name=goal.name,
                target_amount=goal.target_amount,
                target_date=goal.target_date,
                # The account it points at belongs to the real ledger. Carrying
                # the id would make a sandbox read a live balance, so the copy
                # keeps the figure and drops the link.
                account_id=None,
                saved_amount=goal.saved_amount,
                notes=goal.notes,
                is_achieved=goal.is_achieved,
            )
        )

    # Memories describe the household, not the ledger — "Southwest is
    # reimbursed work travel" is true in a copy too — so the assistant is as
    # useful inside a sandbox as outside it. Conversations are *not* copied:
    # those belong to a person and a moment, and duplicating them would leave
    # two divergent histories of the same chat.
    for note in await _all(db, AssistantMemory, source.id):
        db.add(
            AssistantMemory(
                household_id=sandbox.id,
                fact=note.fact,
                source=note.source,
                is_active=note.is_active,
                confirmed_at=note.confirmed_at,
                created_by_user_id=note.created_by_user_id,
            )
        )

    for entry in await _all(db, MerchantMemory, source.id):
        category_id = categories.get(entry.category_id)
        if category_id is None:
            continue
        db.add(
            MerchantMemory(
                household_id=sandbox.id,
                merchant_key=entry.merchant_key,
                category_id=category_id,
                sample_label=entry.sample_label,
                source=entry.source,
            )
        )

    await db.flush()
    return sandbox


async def rename_sandbox(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID, name: str
) -> Household:
    """
    Give a sandbox a name that means something.

    "Probe (sandbox)" twice over is not a list you can choose from, which is
    the whole point of keeping several. Refuses real ledgers: renaming the one
    with the bank connections attached is not something this should do by
    accident.
    """
    household = await db.get(Household, household_id)
    if household is None:
        raise SandboxError("That ledger no longer exists.")
    if not household.is_sandbox:
        raise SandboxError("That is your real ledger, not a sandbox.")
    member = await db.scalar(
        select(HouseholdMember).where(
            HouseholdMember.household_id == household_id,
            HouseholdMember.user_id == user_id,
        )
    )
    if member is None:
        raise SandboxError("That sandbox is not yours.")
    household.name = name.strip()[:120]
    return household


async def _default_name(
    db: AsyncSession, source: Household, user_id: uuid.UUID
) -> str:
    """
    Numbered, so several are told apart at a glance before anybody renames
    them. Counts what exists rather than reusing a stored counter, so deleting
    the middle one does not leave a gap that looks like a missing sandbox.
    """
    existing = len(
        (
            await db.scalars(
                select(Household.id)
                .join(HouseholdMember, HouseholdMember.household_id == Household.id)
                .where(
                    HouseholdMember.user_id == user_id,
                    Household.is_sandbox.is_(True),
                )
            )
        ).all()
    )
    return f"Sandbox {existing + 1}"


async def destroy_sandbox(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """
    Throw a sandbox away.

    Refuses anything that is not a sandbox. This is the one operation in the
    application that deletes financial records outright, so the guard is
    deliberately blunt rather than clever.
    """
    household = await db.get(Household, household_id)
    if household is None:
        raise SandboxError("That ledger no longer exists.")
    if not household.is_sandbox:
        raise SandboxError(
            "That is a real ledger, not a sandbox. Raven will not delete it."
        )
    member = await db.scalar(
        select(HouseholdMember).where(
            HouseholdMember.household_id == household_id,
            HouseholdMember.user_id == user_id,
        )
    )
    if member is None:
        raise SandboxError("That sandbox is not yours.")
    await db.execute(delete(Household).where(Household.id == household_id))


async def _all(db: AsyncSession, model, household_id: uuid.UUID) -> list:
    return list(
        (
            await db.scalars(
                select(model).where(model.household_id == household_id)
            )
        ).all()
    )
