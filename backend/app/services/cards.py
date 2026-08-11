"""
What the cards will take out of this month, and whether they have taken it yet.

**A budget month and a statement month are not the same month, and the gap is
real money.** Alex's cards close mid-month; a card that closes on the 8th
bills July's spending and collects it in August. The budget counted that
spending in July — correctly, that is when it happened — and then said nothing
at all about the cash that has to leave in August to settle it. His words: "a
card that has a statement date of the 8th, that month of spending from July
will have to be paid August."

This module answers one question per card: *how much leaves this month, and has
it gone?* It deliberately does not touch the budget's own arithmetic. Every one
of those charges is already counted as spending in the month it was made, and
adding the statement total to `spent` would count the same money twice. It sits
beside the budget, not inside it — which is exactly how he asked for it.

The household pays each card the day the statement arrives, so the statement's
closing date is also its payment date. That makes "is it paid" answerable: look
for a transfer landing on the card on or after the close.
"""

import calendar
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    AccountKind,
    AccountType,
    Category,
    Transaction,
)
from app.services.spending_scope import budget_month_of
from app.services.splits import countable


def statement_close(day: int, month: date) -> date:
    """
    The date a statement closes in a given month.

    Clamped to the length of the month, because a card that closes on the 31st
    still closes in February — on the 28th, or the 29th. Left uncorrected this
    raises `ValueError` in exactly two months a year, which is the worst
    possible frequency for a bug: rare enough to ship, certain enough to hit.
    """
    return date(month.year, month.month, min(day, calendar.monthrange(month.year, month.month)[1]))


def amount_owed(balance: Decimal | None) -> Decimal:
    """
    What a card owes, from a balance stored negative.

    Clamped at zero: a card in credit — a refund larger than the balance — owes
    nothing. Left unclamped it would return a negative amount and quietly
    reduce what the *other* cards owe, so one refunded card would understate
    the total across all seven.
    """
    return max(Decimal("0.00"), -Decimal(balance or 0))


def statement_split(
    amount: Decimal, earlier_amount: Decimal, owed: Decimal, settled: bool
) -> tuple[Decimal, Decimal]:
    """
    What is still to pay on a statement, and how much of that is older than
    this budget month.

    Two clamps, and each exists because a real figure was wrong without it.

    **You cannot still owe more on a statement than you owe on the card.**
    `amount` is a window of charges; `owed` is the bank's answer to "how much
    is on this card right now", and it already reflects every payment. The
    `settled` test in the caller only looks for payments on or after the close,
    because that is when the household normally pays — so a payment made *in
    the middle* of a cycle was invisible.

    Alex's rent is what exposed it. He charges rent to the Bilt card and pays
    that exact amount the same day:

        2026-08-03   -1,279.87   Bilt Housing Payment
        2026-08-03   +1,279.87   Payment - Bilt Housing

    The card reported $2,802.65 still to pay against a real balance of
    $1,445.95, and $1,279.87 he had already paid was subtracted from what was
    left of his month.

    **Payments settle the oldest charges first**, so whatever is still
    outstanding is the *most recent* spending. Take this month's charges out of
    what is still owed and the remainder is the genuine older carry — for Bilt,
    $1,445.95 owed less $1,249.55 charged in August leaves $196.40, where the
    unclamped arithmetic claimed $1,553.10.

    Both results are zero once the statement is settled: the money has gone,
    and it went where SPENT already says it went.
    """
    if settled:
        return Decimal("0.00"), Decimal("0.00")
    outstanding = min(amount, owed)
    current_amount = max(Decimal("0.00"), amount - earlier_amount)
    return outstanding, max(Decimal("0.00"), outstanding - current_amount)


def card_order(row: dict) -> tuple:
    """
    Sort key for the panel: dated cards first, unpaid before paid, then by
    close date.

    A card with no statement day has `closes_on` of None, and comparing that
    against a date raises `TypeError` — so this exists as a named function
    mostly so the None case can be tested rather than discovered in his
    browser.
    """
    return (
        row["closes_on"] is None,
        row["paid"],
        row["closes_on"] or date.max,
    )


def _previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


async def statement_obligations(
    db: AsyncSession, household_id: uuid.UUID, month: date, today: date
) -> dict:
    """
    Every card, what it wants this month, and what is owed across all of them.

    **Every card appears, whether or not it has a statement day.** Alex kept a
    "Credit Cards" tab in his spreadsheet listing all seven — his five and
    Jordan's two, grouped Alex / Jordan / Shared — whose current balances summed to
    one figure he then added to rent to know what he owed. Showing only the
    configured ones made that sum unobtainable, which is the number he was
    actually after.

    A card without a statement day still contributes its balance; it simply has
    no cycle figures. That distinction is kept rather than papered over — a
    wrong due date is worse than an absent one, because it puts a confident
    number on the budget page that nobody can trace.

    **`balance_total` is never added to the budget's own arithmetic**, for the
    same reason the statement totals are not: every charge is already counted as
    spending in the month it was made. This is a statement of what is owed, and
    it sits beside the plan rather than inside it.
    """
    cards = (
        await db.scalars(
            select(Account).where(
                Account.household_id == household_id,
                Account.kind == AccountKind.liability,
                # Cards only. `kind == liability` also means every student
                # loan, car loan and mortgage — ten of them here — so the
                # "no statement day" footnote was counting his loans and
                # telling him four cards needed configuring when none did.
                Account.type == AccountType.credit,
                Account.is_hidden.is_(False),
            )
        )
    ).all()

    month_first = month.replace(day=1)
    rows = []
    due_total = Decimal("0.00")
    unpaid_total = Decimal("0.00")
    unbudgeted_total = Decimal("0.00")

    balance_total = Decimal("0.00")
    for card in cards:
        # A card's balance is stored negative; what is owed is its magnitude.
        # A card in credit (a refund past the balance) owes nothing rather than
        # a negative amount, which would quietly reduce the total owed on the
        # others.
        owed = amount_owed(card.current_balance)
        balance_total += owed

        if card.statement_day is None:
            # No cycle to report, but it still counts towards what is owed.
            rows.append(
                {
                    "account_id": card.id,
                    "name": card.name,
                    "owner_name": card.owner_name,
                    "statement_day": None,
                    "closes_on": None,
                    "covers_from": None,
                    "amount": Decimal("0.00"),
                    "paid": False,
                    "paid_amount": Decimal("0.00"),
                    "outstanding": Decimal("0.00"),
                    "unbudgeted": Decimal("0.00"),
                    "provisional": False,
                    "current_balance": Decimal(card.current_balance or 0),
                    "balance_owed": owed,
                }
            )
            continue

        closes = statement_close(card.statement_day, month_first)
        opens = statement_close(card.statement_day, _previous_month(month_first))

        # What the statement is for: everything on the card in the cycle except
        # payments. Refunds and cashback belong in it — they genuinely reduce
        # what is owed — so the only exclusion is a transfer, which *is* the
        # payment and would otherwise cancel the balance it settles.
        charged = await db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.account_id == card.id,
                Transaction.posted_date > opens,
                Transaction.posted_date <= closes,
                Transaction.is_transfer.is_(False),
                countable(),
            )
        )
        # Charges are negative on a card, so the amount owed is their negation.
        # A cycle that nets positive (a big refund, no spending) owes nothing
        # rather than a negative amount, which would read as the card paying
        # *them* and would subtract from the month's obligations.
        amount = max(Decimal("0.00"), -Decimal(charged or 0))

        # **How much of this statement the budget has not already counted.**
        #
        # A statement closing on the 22nd bills roughly the 23rd of last month
        # through the 22nd of this one, so it holds charges from two budget
        # months. The ones belonging to *this* month are already inside SPENT —
        # they were counted the day they posted, in whichever category they
        # were filed. Subtracting the whole statement from what is left of the
        # plan therefore takes that money away twice, and Alex saw exactly
        # that: "$102.35 after card payments" on a month he knew had about
        # $1,655 left.
        #
        # Proven on a fixture: a $100 July charge and a $200 August charge on
        # one card, against a plan with $300 left, gave "after card payments"
        # of $0.00. The honest answer is $200 — only July's $100 is money this
        # month has to find and has not already planned for.
        #
        # Uses the shared `budget_month_of` so a charge Alex moved by hand, or
        # one shifted by a category's standing offset (rent), lands on
        # whichever side of the line it actually belongs to. The join to
        # `Category` is an outer one because an uncategorized charge is still a
        # charge — see `is_spending` for why omitting those is the one
        # direction a budget must never be wrong in.
        earlier = await db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.account_id == card.id,
                Transaction.posted_date > opens,
                Transaction.posted_date <= closes,
                Transaction.is_transfer.is_(False),
                countable(),
                budget_month_of(category=Category)
                != func.date_trunc("month", cast(month_first, Date)),
            )
        )
        earlier_amount = max(Decimal("0.00"), -Decimal(earlier or 0))

        paid = await db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.account_id == card.id,
                Transaction.posted_date >= closes,
                Transaction.amount > 0,
                Transaction.is_transfer.is_(True),
                countable(),
            )
        )
        paid_amount = Decimal(paid or 0)
        # A payment for anything at all counts as "they have paid it". They pay
        # the statement in full the day it arrives, so a partial match is far
        # more likely to be a rounding or timing difference than a part payment.
        settled = paid_amount > 0
        outstanding, unbudgeted = statement_split(
            amount, earlier_amount, owed, settled
        )

        due_total += amount
        unpaid_total += outstanding
        unbudgeted_total += unbudgeted
        rows.append(
            {
                "account_id": card.id,
                "name": card.name,
                "statement_day": card.statement_day,
                "closes_on": closes,
                "covers_from": opens,
                "amount": amount,
                "paid": settled,
                "paid_amount": paid_amount,
                "outstanding": outstanding,
                "unbudgeted": unbudgeted,
                # The cycle has not finished yet, so the figure is what has
                # been charged so far and will grow. Saying so is the
                # difference between an estimate and a wrong number.
                "provisional": closes > today,
                "current_balance": Decimal(card.current_balance or 0),
                "balance_owed": owed,
                # Whose card, so the panel can group Alex / Jordan / Shared the
                # way his spreadsheet did. None means shared.
                "owner_name": card.owner_name,
            }
        )

    # Unconfigured cards last, then unpaid before paid, then by close date.
    # `closes_on` is None for those, which no comparison would survive.
    rows.sort(key=card_order)
    return {
        "cards": rows,
        "due_total": due_total,
        "unpaid_total": unpaid_total,
        # **The only one of these three totals that may be subtracted from what
        # is left of the plan.** `due_total` and `unpaid_total` both include
        # charges this month has already counted as spending; this one holds
        # back only what the plan has not seen.
        "unbudgeted_total": unbudgeted_total,
        # What is owed across every card right now — the figure his spreadsheet
        # totalled. Never folded into the budget: see the docstring.
        "balance_total": balance_total,
        # Cards still missing a statement day, so the panel can say what it
        # cannot date rather than quietly leaving it out.
        "unconfigured": sum(1 for row in rows if row["statement_day"] is None),
    }
