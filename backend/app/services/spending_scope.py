"""
What counts as spending, defined once.

Every report in this application asks some version of "how much did we spend",
and each one used to spell out its own answer. They drifted, and the drift was
invisible: a report is a number, and a wrong number looks exactly like a right
one. Alex found this the ordinary way — the budget's SPENT figure disagreed
with the rows printed underneath it.

The specific failure: a **negative amount in an income category**. It happens
constantly — a payroll reversal, a refunded deposit, a Plaid transaction whose
direction was guessed wrong. `/reports/spending` joined categories and summed
outflows without ever asking whether the category was an income one, so a $250
payroll reversal was reported as $250 of spending. The budget page then made it
worse: its headline summed every row the endpoint returned, while the table
below could only render non-income categories, so the total and the rows
disagreed by exactly that $250 with nothing on screen to explain it.

This is the third time in this project one filter written out twice has caused
a bug (see `countable()` for splits and `unreviewed_guess()` for AI review), so
it gets the same treatment: one predicate, imported everywhere, and the reports
have no private opinions about what spending means.

**Spending is money that left, that you meant to spend, in a category that
counts.** Concretely, all of:

- the amount is negative;
- the transaction is not excluded by hand;
- the transaction is not a transfer between your own accounts;
- its category is neither an income category nor one excluded wholesale.

Uncategorized outflows *do* count. Money left the account whether or not
anybody has said where it went, and hiding it until it is filed would make the
totals quietly optimistic — which is the one direction a budget must never be
wrong in.
"""

import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import INTERVAL
from sqlalchemy.orm import aliased

from app.models import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    Transaction,
)
from app.services.splits import countable


def switched_off_category_ids(household_id: uuid.UUID):
    """
    Categories the household has switched off by hand.

    Kept separate from the income test below, and the separation is load
    bearing: the cash-flow diagram must drop these but must obviously *keep*
    income categories, since income is what it is a diagram of. Merging the two
    sets cost a working income total the first time this was written.
    """
    return select(Category.id).where(
        Category.household_id == household_id,
        Category.excluded_from_budget.is_(True),
    )


def uncounted_category_ids(household_id: uuid.UUID):
    """
    Categories whose transactions never count as *spending*: the ones switched
    off, plus every income category. Only for spending questions — see above
    for why the diagram cannot use this one.
    """
    return (
        select(Category.id)
        .join(CategoryGroup, CategoryGroup.id == Category.group_id)
        .where(
            Category.household_id == household_id,
            or_(
                CategoryGroup.is_income.is_(True),
                Category.excluded_from_budget.is_(True),
            ),
        )
    )


def is_spending(household_id: uuid.UUID, model: type[Transaction] = Transaction):
    """
    The predicate itself. Written as a subquery rather than a join so it can be
    dropped into any query — including the ones that never touch the categories
    table — without changing their shape or their grouping.
    """
    return and_(
        model.amount < 0,
        model.excluded_from_budget.is_(False),
        model.is_transfer.is_(False),
        or_(
            # An outflow nobody has filed yet is still an outflow.
            model.category_id.is_(None),
            model.category_id.not_in(uncounted_category_ids(household_id)),
        ),
        countable(model),
    )


def liability_account_ids(household_id: uuid.UUID):
    """
    Credit cards and loans.

    Money *arriving* on one of these is a payment or a refund — never income.
    Without this, a card payment whose paying account is not connected still
    counted as a paycheque, because an uncategorized inflow is otherwise
    treated as income.
    """
    return select(Account.id).where(
        Account.household_id == household_id,
        Account.kind == AccountKind.liability,
    )


def income_category_ids(household_id: uuid.UUID):
    """Categories that earn money. The positive counterpart of the sets above."""
    return (
        select(Category.id)
        .join(CategoryGroup, CategoryGroup.id == Category.group_id)
        .where(
            Category.household_id == household_id,
            CategoryGroup.is_income.is_(True),
        )
    )


def is_income(household_id: uuid.UUID, model: type[Transaction] = Transaction):
    """
    The mirror of `is_spending`, and it exists for the same reason: the
    dashboard and `/reports/cash-flow` each wrote out their own answer and gave
    two different income figures for the same month. The dashboard said
    $8,914.42 and the cash-flow chart said $8,952.92, the difference being a
    $38.50 fuel refund that one of them thought was earnings.

    **Income is money that arrived somewhere that earns it.** Concretely:

    - the amount is positive;
    - not excluded by hand, not a transfer;
    - not arriving on a credit card — nobody is paid into a card, so an inflow
      there is a payment or a refund;
    - its category is an income category, or it has none yet.

    A refund filed in a spending category is deliberately *neither*. It reduces
    that category rather than earning anything, and calling it income inflates
    every savings rate on the page.

    **The `or_` around the switched-off test is load bearing.** `NULL NOT IN
    (...)` is NULL, not true, so writing that as a bare `not_in` silently drops
    every uncategorized inflow — but only once the household switches some
    category off, because `NOT IN (empty set)` *is* true. That is a bug that
    appears months later when somebody turns off a category they never use, and
    takes uncategorized income with it. It cost $100 of a $9,014.42 month in
    the audit fixture, invisibly.
    """
    return and_(
        model.amount > 0,
        model.excluded_from_budget.is_(False),
        model.is_transfer.is_(False),
        countable(model),
        or_(
            model.category_id.is_(None),
            model.category_id.in_(income_category_ids(household_id)),
        ),
        or_(
            model.category_id.is_(None),
            model.category_id.not_in(switched_off_category_ids(household_id)),
        ),
        model.account_id.not_in(liability_account_ids(household_id)),
    )


def budget_month_of(model=Transaction, category=None):
    """
    Which month's *plan* a transaction counts against.

    `COALESCE(budget_month, date_trunc('month', posted_date))` — the month a
    person assigned it to, or failing that the month it posted in, which is
    almost every row.

    **This exists so the definition is written once.** Every other money
    question in this codebase filters on `posted_date`, and must keep doing so:
    net worth, cash flow, the Sankey, statements and reconciliation are all
    statements about what happened. Only the budget asks what a month was
    *planned* to carry, and rent is why — due on the 1st, paid out of the
    previous month's pay, posting in the new month. Counted where it posts,
    August looked funded while the money left in July and nothing said to set
    September's aside.

    Defined here beside `is_spending` for the reason that module exists: the
    third bug in this project was one filter written out twice and drifting.
    """
    posted = func.date_trunc("month", model.posted_date)
    if category is not None:
        # The category's standing answer: -1 shifts Housing back a month, so
        # rent counts where the pay came from. Applied here rather than
        # written into each row, so changing it corrects the history too —
        # materialising it would leave old rows holding the old answer with
        # nothing to say so.
        # `coalesce` because this is now reached through an *outer* join too:
        # an uncategorized charge has no offset, and `concat(NULL, ' months')`
        # yields ' months', which fails to cast. A row with no category simply
        # has no standing rule.
        posted = posted + func.cast(
            func.concat(
                func.coalesce(category.budget_month_offset, 0), " months"
            ),
            INTERVAL,
        )
    # **A split line inherits its parent's assignment.** The parent is excluded
    # from every total by `countable()`, so the lines are what the budget
    # actually counts — and setting the month on the charge did nothing at all
    # until this existed. Alex pays his father several things in one Venmo
    # charge, splits it five ways and needs the whole thing to land in the
    # previous month; he cannot do that line by line, and should not have to.
    #
    # Correlated on `parent_transaction_id`, which is NULL for every ordinary
    # row, so the subquery yields NULL and coalesces away.
    parent = aliased(model)
    inherited = (
        select(func.date_trunc("month", parent.budget_month))
        .where(parent.id == model.parent_transaction_id)
        .scalar_subquery()
    )
    # Order is the whole rule: the line's own assignment, then the charge it
    # belongs to, then the category's standing offset, then where it posted.
    # The specific beats the general at every step.
    return func.coalesce(
        func.date_trunc("month", model.budget_month), inherited, posted
    )
