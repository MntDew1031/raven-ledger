"""
Money moving between the household's own accounts is not income or spending.

Alex found this the way it always gets found — the same figure printed twice
with opposite signs. Paying $702.69 off a Citi card produced:

    CITI CARD ONLINE        -$702.69   SoFi Checking     → "bills"
    ONLINE PAYMENT, THANK   +$702.69   Costco Visa       → "recurring income"

Both accounts were connected, so Plaid reported both legs, and the ledger
believed both. His income read $33,552 and his spending $34,852 against a real
gap far smaller than that, and his savings rate went negative.

Three rules, because each covers a hole the others leave:

1. **Plaid's own code.** `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT` now counts as an
   account transfer (see `provider_categories`). Cheap, and right whenever
   Plaid labels the transaction correctly.

2. **Matched pairs.** An outflow from an asset account and an inflow to a
   liability account, same amount, within a few days: that is a card payment
   whatever Plaid called it. Both legs get marked, so neither the outgoing nor
   the incoming half is counted.

3. **Inflows to a card, unmatched.** If the paying account is not connected,
   there is no pair to match — but money still never *arrives* as income on a
   credit card. A payment-shaped descriptor is treated as a transfer; anything
   else (a refund, say) is left alone but is kept out of income by
   `spending_scope`, since a refund reduces spending rather than earning
   anything.

The conservatism is deliberate and asymmetric. Rule 2 requires the inflow to
land on a **liability** account rather than merely matching two amounts,
because two unrelated transactions of the same size a few days apart is an
ordinary coincidence — but being paid income into a credit card is not a thing
that happens. Wrongly hiding a real paycheque would be a far worse failure than
leaving one transfer for a person to mark by hand.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountKind, Transaction

# How far apart the two legs of one payment may post. Card payments usually
# settle same-day or next-day; a few days of slack covers weekends and the gap
# between an authorization and its posting.
PAIR_WINDOW_DAYS = 5

# Descriptors a card issuer uses for an incoming payment. Only consulted for
# money arriving on a credit card, where the alternative readings are few.
PAYMENT_WORDS = (
    "payment",
    "thank you",
    "autopay",
    "auto pay",
    "epay",
    "bill pay",
    "billpay",
)

# Rewards paid back onto a card. Alex's exact descriptor was
# "CASHBACK BONUS REDEMPTION PYMT/STMT CRDT", which the model filed as Income
# — he said it was "somewhat true", and it is the "somewhat" that matters.
#
# A reward is a **rebate**: it reduces what a purchase cost. Counting it as
# income says the household earned money it did not earn, inflates the savings
# rate, and makes a month look better than it was. Excluding it is the honest
# treatment — the spending it offsets is already recorded at full price, and
# nothing here pretends to go back and reduce it.
REWARD_WORDS = (
    "cashback",
    "cash back",
    "reward",
    "redemption",
    "statement credit",
    "stmt crdt",
    "points",
    "rebate",
)


def _descriptor(transaction: Transaction) -> str:
    return " ".join(
        filter(
            None,
            (transaction.merchant_name, transaction.original_description),
        )
    ).lower()


def looks_like_a_payment(transaction: Transaction) -> bool:
    return any(word in _descriptor(transaction) for word in PAYMENT_WORDS)


def looks_like_a_reward(transaction: Transaction) -> bool:
    """
    A cashback or points redemption landing back on a card.

    Checked before the payment test, because these descriptors often contain
    both — "CASHBACK BONUS REDEMPTION PYMT/STMT CRDT" has "pymt" in it — and a
    reward is not a transfer from another account. Nothing moved between the
    household's accounts; the card issuer simply gave some money back.
    """
    return any(word in _descriptor(transaction) for word in REWARD_WORDS)


# Words that identify nothing. Every card is a "card"; matching on them would
# make one account's name match every descriptor.
GENERIC_ACCOUNT_WORDS = frozenset(
    {
        "card", "cards", "credit", "debit", "visa", "mastercard", "amex",
        "discover", "bank", "account", "payment", "payments", "the", "and",
        "of", "my", "our", "online", "web", "pmt", "auto", "autopay",
    }
)


def _tokens(text: str) -> set[str]:
    return {word for word in re.split(r"[^a-z0-9]+", text.lower()) if word}


def names_one_of_our_cards(
    transaction: Transaction, card_names: list[str]
) -> bool:
    """
    Whether an outflow's descriptor is naming one of the household's own cards.

    **The gap this closes:** paying a card is only recognised today when the
    matching inflow has already posted on the card, or when Plaid labels it.
    Alex's `BILT CARD  -$1,279.87` from checking had neither, so it counted as
    spending — while the rent it was paying off was *also* counted, as a
    Housing charge on the Bilt card. One month's rent, twice.

    **The test is subset, not substring, and that is the whole design.** Every
    significant word in the descriptor must also appear in the account's name:

        "BILT CARD"      ⊆ "Bilt Obsidian Card"   → a payment
        "APPLE CARD"     ⊆ "Apple Card"           → a payment
        "APPLE.COM/BILL" ⊄ "Apple Card"           → a purchase, left alone

    A substring test would have swallowed that last one and filed an Apple
    purchase as moving money between his own accounts. A merchant descriptor
    carries words the account name does not; a payment descriptor does not.

    At least one shared word must also be distinctive, or a bare "CARD" would
    match every card in the house.
    """
    descriptor = _tokens(_descriptor(transaction))
    if not descriptor:
        return False
    for name in card_names:
        account = _tokens(name)
        if not account or not descriptor <= account:
            continue
        if descriptor - GENERIC_ACCOUNT_WORDS:
            return True
    return False


async def link_transfer_pairs(
    db: AsyncSession, household_id: uuid.UUID
) -> dict[str, int]:
    """
    Find and mark transfers the provider did not label.

    Returns counts rather than raising: this runs after every sync, and a
    household with nothing to fix is the normal case.
    """
    rows = (
        await db.execute(
            select(Account.id, Account.kind, Account.name).where(
                Account.household_id == household_id
            )
        )
    ).all()
    kinds = {account_id: kind for account_id, kind, _ in rows}
    account_names = {account_id: name for account_id, _, name in rows}
    if not kinds:
        return {"paired": 0, "unmatched_card_payments": 0}

    relabelled = await _clear_stale_guesses(db, household_id, kinds)

    candidates = (
        await db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.is_transfer.is_(False),
                Transaction.parent_transaction_id.is_(None),
            )
        )
    ).all()

    inflows_to_cards = [
        item
        for item in candidates
        if item.amount > 0 and kinds.get(item.account_id) == AccountKind.liability
    ]
    outflows = [item for item in candidates if item.amount < 0]

    paired = 0
    claimed: set[uuid.UUID] = set()
    for inflow in inflows_to_cards:
        match = None
        for outflow in outflows:
            if outflow.id in claimed:
                continue
            if outflow.account_id == inflow.account_id:
                continue
            if kinds.get(outflow.account_id) != AccountKind.asset:
                continue
            if abs(outflow.amount) != inflow.amount:
                continue
            gap = abs((outflow.posted_date - inflow.posted_date).days)
            if gap > PAIR_WINDOW_DAYS:
                continue
            # Nearest in time wins, so a household that pays the same amount
            # twice in a month pairs each payment with its own leg.
            if match is None or gap < abs(
                (match.posted_date - inflow.posted_date).days
            ):
                match = outflow
        if match is None:
            continue
        claimed.add(match.id)
        for leg in (inflow, match):
            _mark(leg)
        paired += 1

    # Rule 3: the paying account is not connected, so there is no second leg.
    unmatched = 0
    rewards = 0
    for inflow in inflows_to_cards:
        if inflow.is_transfer or inflow.excluded_from_budget:
            continue
        if looks_like_a_reward(inflow):
            # A rebate, not a transfer: excluded so it never counts as income,
            # but *not* flagged as a transfer, because nothing moved between
            # the household's own accounts. The guessed category goes too —
            # "Income" on a cashback line is the thing that looked wrong.
            inflow.excluded_from_budget = True
            if not _person_decided(inflow):
                inflow.category_id = None
                inflow.categorization_source = None
            rewards += 1
            continue
        if looks_like_a_payment(inflow):
            _mark(inflow)
            unmatched += 1

    # Rule 4: the outflow side, named rather than paired.
    #
    # Rules 2 and 3 both need the card's own leg to exist — a pair to match, or
    # an inflow to inspect. A payment made today against a card that posts it
    # tomorrow has neither, and until it does the money counts as spending. For
    # a card that pays the rent, that means one month's rent counted twice.
    named = 0
    card_names = [
        name
        for account_id, name in account_names.items()
        if kinds.get(account_id) == AccountKind.liability
    ]
    if card_names:
        for outflow in outflows:
            if outflow.is_transfer:
                continue
            if kinds.get(outflow.account_id) != AccountKind.asset:
                continue
            if names_one_of_our_cards(outflow, card_names):
                _mark(outflow)
                named += 1

    await db.commit()
    return {
        "paired": paired,
        "unmatched_card_payments": unmatched,
        "rewards": rewards,
        "named_card_payments": named,
        "relabelled": relabelled,
    }


async def _clear_stale_guesses(
    db: AsyncSession, household_id: uuid.UUID, kinds: dict
) -> int:
    """
    Strip a guessed category off rows that were flagged before we cleared it.

    Clearing the category happens at the moment a row is marked. Everything
    marked *before* that behaviour existed therefore still displays whatever
    the model called it — and the rest of this function cannot reach those
    rows, because it only considers `is_transfer = false`. Marked rows are
    invisible to it by design, so the stale label would survive every future
    run of "Run rules" forever.

    That is the exact shape of the bug Alex reported twice: card payments were
    excluded from the totals in 1.39.0, so the arithmetic was right, while the
    rows kept saying "Income" on screen. Fixing `_mark` in 1.53.0 fixed it only
    for payments that arrived afterwards. His ledger is mostly the ones that
    arrived before.

    Two populations, and the second is narrower on purpose:

    - **Anything already flagged as a transfer.** A transfer's category means
      nothing to any budget, so removing a machine's guess costs nothing.
    - **Rewards already excluded**, but only inflows onto a card whose
      descriptor still reads like a reward. `excluded_from_budget` is also how
      a person hides an ordinary transaction by hand, and the category they
      picked for it is theirs to keep.

    A category a person chose is never touched in either case.
    """
    unreviewed = Transaction.reviewed.is_(False)
    # Every transfer, and neither filter you would expect.
    #
    # No `category_id IS NOT NULL`: a transfer that already lost its category
    # but is still queued is the *worse* half of the complaint — it reads
    # "Uncategorized · not counted" and nothing can clear it, because reviewing
    # asks for a category it must not have. Selecting only rows that still
    # carry a label walks straight past those.
    #
    # No `reviewed IS false` either, because a reviewed transfer is not a
    # decided one — see `_person_decided`. Filtering here meant approve-all
    # took the eighteen out of reach of the sweep still wearing "Income".
    # Skipping the filter is safe: clearing a transfer's category now marks it
    # reviewed in the same breath, so it cannot fall back into the queue, which
    # is what 1.53.2 did.
    rows = (
        await db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.is_transfer.is_(True),
            )
        )
    ).all()

    liabilities = {
        account_id
        for account_id, kind in kinds.items()
        if kind == AccountKind.liability
    }
    rebates = (
        await db.scalars(
            select(Transaction).where(
                Transaction.household_id == household_id,
                Transaction.is_transfer.is_(False),
                Transaction.excluded_from_budget.is_(True),
                Transaction.amount > 0,
                Transaction.account_id.in_(liabilities) if liabilities else False,
                unreviewed,
            )
        )
    ).all()

    changed = 0
    for transaction in list(rows) + [
        item for item in rebates if looks_like_a_reward(item)
    ]:
        before = (transaction.category_id, transaction.reviewed)
        if not _person_decided(transaction):
            transaction.category_id = None
            transaction.categorization_source = None
        # Only once there is nothing left to decide. A category somebody set by
        # hand survives above, and that row stays in the queue where they can
        # approve it themselves — it has an answer, so it is not stuck.
        if transaction.category_id is None:
            transaction.reviewed = True
        if (transaction.category_id, transaction.reviewed) != before:
            changed += 1
    return changed


# Categories a machine chose. A person's choice is never overwritten here.
# `None` counts: a category with no recorded source was not chosen deliberately.
_NAMED_GUESSES = ("ai", "provider_category", "keyword_model", "merchant_memory")
_GUESSED = frozenset({*_NAMED_GUESSES, None})


def _person_decided(transaction: Transaction) -> bool:
    """
    Whether a human has signed off on this transaction's category.

    **`categorization_source` alone does not answer this**, and assuming it did
    cost Alex his review queue. Pressing the tick to approve an AI suggestion
    sets `reviewed` and leaves the source saying `"ai"` — accurately, because a
    model did pick it, and the person agreed. Reading only the source, the
    sweep below saw a machine's guess, cleared it, and dropped a transaction he
    had just approved back into "needs review". His words: they re-appear.

    So `reviewed` is the signal, and the source is the fallback for rows nobody
    has looked at yet.

    **Except on a transfer, where `reviewed` says nothing about a category.**
    Since a transfer can be reviewed without one, the tick there means "I have
    seen this, take it out of my queue" — not "Income is the right name for the
    money I moved onto my own card". Counting it as a decision froze the stale
    label on every card payment the instant Alex pressed approve-all, which
    the drill caught and reading the code did not. On a transfer only a source
    a person set by hand answers this.
    """
    if transaction.is_transfer:
        return transaction.categorization_source not in _GUESSED
    return (
        transaction.reviewed
        or transaction.categorization_source not in _GUESSED
    )


def _mark(transaction: Transaction) -> None:
    """
    Both flags, always together — and the guessed category goes with them.

    `is_transfer` is what the reports read; `excluded_from_budget` is what the
    older queries read. Setting one without the other hides a transfer from one
    screen and leaves it on another.

    Clearing the category matters just as much, and its absence was a real
    complaint: the reports stopped counting these correctly in 1.39.0, but each
    row still *displayed* "Income" — the label the AI had given it before
    anyone knew it was a transfer. Being right in the totals and wrong on the
    screen is not being right.

    A category a person chose by hand is left alone: they may well want their
    card payments filed somewhere, and this is not the place to argue.
    """
    transaction.is_transfer = True
    transaction.excluded_from_budget = True
    if not _person_decided(transaction):
        transaction.category_id = None
        transaction.categorization_source = None
    # And it leaves the review queue. Reviewing is how a person confirms a
    # *category*, and a transfer has none to confirm — so one sat there saying
    # "Uncategorized · not counted" with nothing that could clear it. Eighteen
    # of them, in Alex's case, permanently.
    transaction.reviewed = True
