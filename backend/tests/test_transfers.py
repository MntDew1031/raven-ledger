"""
Credit-card payments are not income, and not spending either.

Reconstructed from a regression fixture: paying $702.69 off a card showed
up twice, once as a bill leaving SoFi Checking and once as recurring income
arriving on the Costco Visa. Both accounts were connected, so Plaid reported
both legs and the ledger believed both.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.models import AccountKind, Transaction
from app.services import provider_categories
from app.services.transfers import (
    PAIR_WINDOW_DAYS,
    looks_like_a_payment,
)


def _txn(amount, account_id, day, merchant="X", description="X"):
    return Transaction(
        id=uuid.uuid4(),
        account_id=account_id,
        amount=amount,
        posted_date=day,
        merchant_name=merchant,
        original_description=description,
        is_transfer=False,
        excluded_from_budget=False,
    )


class TestPlaidCode:
    def test_card_payment_is_an_account_transfer(self):
        """
        The absent code that caused all of it. It fell through to the
        LOAN_PAYMENTS primary and resolved to "Debt Payments", so paying a card
        off was recorded as spending.
        """
        assert provider_categories.is_account_transfer(
            "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"
        )

    def test_the_original_two_codes_still_count(self):
        for code in (
            "TRANSFER_IN_ACCOUNT_TRANSFER",
            "TRANSFER_OUT_ACCOUNT_TRANSFER",
        ):
            assert provider_categories.is_account_transfer(code)

    def test_an_ordinary_loan_payment_is_not_a_transfer(self):
        """A car payment leaves the household. Only the card case is internal."""
        assert not provider_categories.is_account_transfer(
            "LOAN_PAYMENTS_CAR_PAYMENT"
        )
        assert not provider_categories.is_account_transfer(
            "LOAN_PAYMENTS_MORTGAGE_PAYMENT"
        )

    def test_a_real_deposit_is_not_a_transfer(self):
        assert not provider_categories.is_account_transfer("INCOME_WAGES")
        assert not provider_categories.is_account_transfer("TRANSFER_IN_DEPOSIT")


class TestPaymentDescriptors:
    @pytest.mark.parametrize(
        "text",
        [
            "ONLINE PAYMENT, THANK YOU",  # his, verbatim
            "AUTOPAY PAYMENT",
            "CITI CARD ONLINE PAYMENT",
            "BILL PAY TRANSFER",
        ],
    )
    def test_recognises_a_card_payment(self, text):
        assert looks_like_a_payment(_txn(700, uuid.uuid4(), date.today(), text, text))

    @pytest.mark.parametrize(
        "text", ["AMAZON REFUND", "COSTCO RETURN", "INTEREST EARNED"]
    )
    def test_leaves_other_inflows_alone(self, text):
        """
        A refund is not a payment. It stays visible and is kept out of income
        by spending_scope instead, because it reduces spending rather than
        earning anything.
        """
        assert not looks_like_a_payment(
            _txn(40, uuid.uuid4(), date.today(), text, text)
        )


class TestPairingIsDeliberatelyConservative:
    """
    The asymmetry that matters: wrongly hiding a real paycheque is far worse
    than leaving one transfer to be marked by hand. So pairing requires the
    inflow to land on a *liability* account — two unrelated transactions of the
    same size days apart is an ordinary coincidence, but nobody is paid income
    into a credit card.
    """

    def test_window_is_days_not_weeks(self):
        assert 1 <= PAIR_WINDOW_DAYS <= 7

    def test_the_module_requires_a_liability_destination(self):
        import inspect

        from app.services import transfers

        source = inspect.getsource(transfers.link_transfer_pairs)
        assert "AccountKind.liability" in source
        assert "AccountKind.asset" in source

    def test_both_legs_are_marked_together(self):
        """
        A transfer flagged on one screen and not another is worse than being
        wrong consistently: the reports read is_transfer, older queries read
        excluded_from_budget.
        """
        import inspect

        from app.services import transfers

        source = inspect.getsource(transfers._mark)
        assert "is_transfer = True" in source
        assert "excluded_from_budget = True" in source


class TestRecurringAndIncomeConsequences:
    def test_recurring_skips_transfers(self):
        """Which is what removes card payments from Bills and subscriptions."""
        import inspect

        from app.services import recurring

        assert "is_transfer.is_(False)" in inspect.getsource(
            recurring.detect_recurring
        )

    def test_dashboard_income_excludes_inflows_to_cards(self):
        """Against the predicate, not against where it happens to be written."""
        import uuid

        from app.services.spending_scope import is_income

        sql = str(is_income(uuid.uuid4()).compile(
            compile_kwargs={"literal_binds": True}
        ))
        assert "accounts.kind" in sql and "NOT IN" in sql

    def test_sync_links_transfers_before_categorizing(self):
        """
        Order matters: a transfer leg that gets a spending category first lands
        in a budget and is believed.
        """
        import inspect

        from app import worker

        source = inspect.getsource(worker.sync_plaid_item)
        assert source.index("link_transfer_pairs") < source.index(
            "categorize_uncategorized"
        )


class TestTheSignMustAgreeWithTheCategory:
    """
    Representative fixture: "INTERNET PAYMENT - THANK YOU", a +$342.40
    payment onto a Discover card, matched the word "internet" and was filed as
    Utilities. A positive amount in a spending category subtracts from that
    budget every month, quietly.

    The guard existed in the AI path and nowhere else.
    """

    def test_the_keyword_table_alone_has_no_idea_about_sign(self):
        """Which is why the check cannot live there."""
        from app.services.categorizer import keyword_category

        category, _ = keyword_category(
            "INTERNET PAYMENT - THANK YOU", {"utilities": "U"}
        )
        assert category == "U"

    def test_the_categorizer_checks_it_centrally(self):
        import inspect

        from app.services.categorizer import categorize_uncategorized

        source = inspect.getsource(categorize_uncategorized)
        assert "(category_id in income_ids) != inflow" in source

    def test_a_hand_written_rule_is_exempt(self):
        """If somebody says these belong there, it is their ledger."""
        import inspect

        from app.services.categorizer import categorize_uncategorized

        assert 'source != "household_rule"' in inspect.getsource(
            categorize_uncategorized
        )

    def test_running_rules_also_links_transfers(self):
        """
        A newly connected card arrives with a year of payments. Until they are
        recognised they are inflows looking for a category, and this used to
        run only on sync.
        """
        import inspect

        from app import worker

        assert "link_transfer_pairs" in inspect.getsource(
            worker.categorize_household
        )


class TestALabelledTransferLosesTheLabel:
    """
    1.39.0 stopped these being *counted* as income, and Alex reported the same
    bug again when Jordan imported her cards — because each row still displayed
    "Income", the label the model gave it before anything knew it was a
    transfer. Being right in the totals and wrong on the screen is not being
    right.
    """

    def test_marking_a_transfer_clears_a_guessed_category(self):
        import types

        from app.services.transfers import _mark

        for guess in ("ai", "provider_category", "keyword_model", "merchant_memory"):
            row = types.SimpleNamespace(
                is_transfer=False,
                excluded_from_budget=False,
                category_id="income-uuid",
                categorization_source=guess,
                # Nobody has looked at it: see
                # TestApprovingASuggestionIsAPersonDeciding for why that
                # distinction is the whole of it.
                reviewed=False,
            )
            _mark(row)
            assert row.is_transfer and row.excluded_from_budget
            assert row.category_id is None, guess
            assert row.categorization_source is None, guess

    def test_a_category_a_person_chose_survives(self):
        """
        They may well want their card payments filed somewhere, and this is not
        the place to argue with them.
        """
        import types

        from app.services.transfers import _mark

        row = types.SimpleNamespace(
            is_transfer=False,
            excluded_from_budget=False,
            category_id="their-choice",
            categorization_source="manual",
            reviewed=False,
        )
        _mark(row)
        assert row.is_transfer and row.excluded_from_budget
        assert row.category_id == "their-choice"

    def test_a_reward_loses_its_category_too(self):
        """
        "CASHBACK BONUS REDEMPTION PYMT/STMT CRDT" filed as Income was the
        exact line he pointed at. It is a rebate, not earnings.
        """
        import inspect

        from app.services.transfers import link_transfer_pairs

        rewards = inspect.getsource(link_transfer_pairs).split(
            "looks_like_a_reward(inflow)", 1
        )[1]
        assert "inflow.category_id = None" in rewards.split("continue", 1)[0]


class TestMoneyNeverArrivesAsIncomeOnACard:
    """
    The rule that should have existed from the start. A payment onto a credit
    card is money moving between the household's own accounts, or somebody
    else paying the bill — it is never earnings.
    """

    def test_the_categorizer_refuses_it(self):
        import inspect

        from app.services.categorizer import categorize_uncategorized

        source = inspect.getsource(categorize_uncategorized)
        assert "liability_accounts" in source
        assert "inflow and transaction.account_id in liability_accounts" in source


class TestRowsFlaggedBeforeTheFixExisted:
    """
    Alex reported "payments show as income" twice, and the second report was
    not a regression — it was the same rows.

    Clearing the category happens when a row is *marked*. Everything marked by
    an earlier release still carries whatever the model called it, and
    `link_transfer_pairs` cannot reach those rows: it selects on
    `is_transfer = false`, so a marked row is invisible to it by design. The
    stale label would survive every future run of "Run rules" forever.
    """

    def test_the_sweep_runs_before_the_pass_that_cannot_see_them(self):
        import inspect

        from app.services.transfers import link_transfer_pairs

        source = inspect.getsource(link_transfer_pairs)
        assert "_clear_stale_guesses" in source
        assert source.index("_clear_stale_guesses") < source.index(
            "Transaction.is_transfer.is_(False)"
        )

    def test_it_reports_how_many_it_relabelled(self):
        """Silent repair of somebody's ledger is not repair anybody can check."""
        import inspect

        from app.services.transfers import link_transfer_pairs

        assert '"relabelled": relabelled' in inspect.getsource(link_transfer_pairs)

    def test_a_hand_chosen_category_is_out_of_scope(self):
        """
        Decided per row rather than in the query, because a row carrying a
        hand-set category still has to be considered for the review queue —
        it keeps its label and stays queued, since it has an answer somebody
        can approve.
        """
        import inspect

        from app.services.transfers import _clear_stale_guesses

        source = inspect.getsource(_clear_stale_guesses)
        assert "if not _person_decided(transaction):" in source
        assert "Transaction.reviewed.is_(False)" in source

    def test_a_manually_hidden_row_keeps_its_category(self):
        """
        `excluded_from_budget` is also how a person hides an ordinary
        transaction by hand. Sweeping every excluded row would take the
        category they chose for it, so the rebate half is narrowed to inflows
        on a card whose descriptor still reads like a reward.
        """
        import inspect

        from app.services.transfers import _clear_stale_guesses

        source = inspect.getsource(_clear_stale_guesses)
        assert "Transaction.amount > 0" in source
        assert "account_id.in_(liabilities)" in source
        assert "looks_like_a_reward(item)" in source


class TestApprovingASuggestionIsAPersonDeciding:
    """
    The regression 1.53.2 shipped, in Alex's words: "the transactions I review
    and submit do not seem to be saving... once I go to a new tab and come back
    they re-appear."

    Pressing the tick to approve an AI suggestion sets `reviewed` and leaves
    `categorization_source` saying `"ai"` — accurately: a model picked it and a
    person agreed. The stale-guess sweep read only the source, saw a machine's
    guess, cleared it, and because a review requires a category the row fell
    straight back into "needs review".

    `reviewed` is what says a human decided. The source is only the fallback
    for rows nobody has looked at.
    """

    def _row(self, **kw):
        import types

        base = dict(
            is_transfer=False,
            excluded_from_budget=False,
            category_id="cat",
            categorization_source="ai",
            reviewed=False,
        )
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_an_approved_suggestion_never_returns_to_the_queue(self):
        """
        The regression stated precisely. 1.53.2's harm was not that a label was
        lost — it was that losing it put the row back in front of Alex, over
        and over, because a review demanded a category. Clearing and dismissing
        now happen together, so the round trip is structurally impossible.

        1.53.3 asserted the category itself survived, which was the right fix
        for the wrong reason on a transfer: see
        `TestReviewingATransferIsNotChoosingItsCategory`.
        """
        from app.services.transfers import _mark

        row = self._row(reviewed=True)
        _mark(row)
        assert row.is_transfer and row.excluded_from_budget
        assert row.reviewed, "the tick he pressed has to stick"

    def test_a_row_nobody_looked_at_is_still_cleared(self):
        from app.services.transfers import _mark

        row = self._row(reviewed=False)
        _mark(row)
        assert row.category_id is None

    def test_a_reviewed_reward_keeps_the_category_it_was_given(self):
        """
        The half of the sweep that is *not* a transfer. A cashback line is an
        ordinary row that happens to be excluded, so approving its suggestion
        is still a person agreeing with a category — the 1.53.3 rule, intact
        everywhere it was ever about a category.
        """
        from app.services.transfers import _person_decided

        assert _person_decided(self._row(reviewed=True, excluded_from_budget=True))

    def test_both_signals_agree(self):
        from app.services.transfers import _person_decided

        assert _person_decided(self._row(reviewed=True))
        assert _person_decided(self._row(categorization_source="manual"))
        assert _person_decided(self._row(categorization_source="household_rule"))
        assert not _person_decided(self._row())
        assert not _person_decided(self._row(categorization_source=None))


class TestReviewingATransferIsNotChoosingItsCategory:
    """
    Caught in the 1.53.4 drill, and only because the drill pressed the buttons
    in the order a person would: approve-all first, Run rules second.

    Approve-all marked all eighteen card payments reviewed — it can now, which
    is the point of the release. The sweep then read `reviewed` as "a person
    decided this category", kept the stale "Income" label on every one, and
    skipped them forever after. The fix Alex asked for would have re-created
    the bug he was complaining about, in one gesture.

    A transfer has no category to agree with. The tick on one means "take this
    out of my queue". Only a source a person set by hand speaks for the label.
    """

    def _transfer(self, **kw):
        import types

        base = dict(
            is_transfer=True,
            excluded_from_budget=True,
            category_id="income",
            categorization_source="ai",
            reviewed=True,
        )
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_reviewing_a_transfer_does_not_bless_a_guess(self):
        from app.services.transfers import _person_decided

        assert not _person_decided(self._transfer())

    def test_a_hand_set_category_on_a_transfer_still_survives(self):
        from app.services.transfers import _person_decided

        assert _person_decided(self._transfer(categorization_source="manual"))
        assert _person_decided(
            self._transfer(categorization_source="household_rule", reviewed=False)
        )

    def test_the_sweep_does_not_filter_transfers_by_reviewed(self):
        """
        The rule has to hold in the query too, or approve-all puts the rows
        out of the sweep's reach before it ever runs.
        """
        import inspect

        from app.services.transfers import _clear_stale_guesses

        transfers = inspect.getsource(_clear_stale_guesses).split(
            "liabilities = {", 1
        )[0]
        assert "Transaction.is_transfer.is_(True)" in transfers
        assert "unreviewed" not in transfers.split("unreviewed =", 1)[1]

    def test_the_rebate_half_still_respects_a_review(self):
        import inspect

        from app.services.transfers import _clear_stale_guesses

        rebates = inspect.getsource(_clear_stale_guesses).split(
            "liabilities = {", 1
        )[1]
        assert "unreviewed" in rebates


class TestATransferCanBeCleared:
    """
    Alex, after 1.53.3: "the transactions I review and submit do not seem to
    be saving. once I go to a new tab and come back they seem to re-appear."

    Not a save that failed to persist — a save that never happened. Reviewing
    demanded a category, and a transfer has none by design: the sweep strips it
    precisely because it means nothing to any budget. Eighteen card payments
    sat in "needs review" reading "Uncategorized · not counted" with nothing a
    person could press. The tick refused client-side, "approve all" counted
    them `skipped_uncategorized`, and the PATCH 422'd.

    So marking a transfer also takes it out of the queue, and every review path
    agrees on when a category is required.
    """

    def _row(self, **kw):
        import types

        base = dict(
            is_transfer=False,
            excluded_from_budget=False,
            category_id="cat",
            categorization_source="ai",
            reviewed=False,
        )
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_marking_a_transfer_takes_it_out_of_the_queue(self):
        from app.services.transfers import _mark

        row = self._row()
        _mark(row)
        assert row.category_id is None
        assert row.reviewed, "nothing left to decide, so nothing to ask about"

    def test_the_sweep_reaches_rows_that_already_lost_their_category(self):
        """
        The worse half of the complaint, and the one a
        `category_id IS NOT NULL` filter walks straight past: 1.53.2 stripped
        the category and left the row queued.
        """
        import inspect

        from app.services.transfers import _clear_stale_guesses

        source = inspect.getsource(_clear_stale_guesses)
        assert "Transaction.category_id.is_not(None)" not in source

    def test_a_row_with_a_hand_set_category_stays_for_the_person(self):
        """
        It has an answer somebody can approve, so it is not stuck. Clearing it
        for them would be deciding on their behalf.
        """
        from app.services.transfers import _person_decided

        row = self._row(categorization_source="manual", is_transfer=True)
        assert _person_decided(row)

    def test_every_review_path_agrees_on_when_a_category_is_required(self):
        from app.api.transactions import _review_needs_a_category

        assert _review_needs_a_category(False, False), "ordinary spending"
        assert not _review_needs_a_category(True, True), "a transfer"
        assert not _review_needs_a_category(False, True), "excluded by hand"

    def test_approve_all_no_longer_skips_them(self):
        """
        `bulk_review` filtered on `category_id is not None`, so pressing
        "approve all" reported them as skipped and left every one behind.
        """
        import inspect

        from app.api.transactions import bulk_review

        assert "_review_needs_a_category" in inspect.getsource(bulk_review)

    def test_the_patch_route_uses_the_same_predicate(self):
        import inspect

        from app.api.transactions import update_transaction

        assert "_review_needs_a_category" in inspect.getsource(update_transaction)


class TestPayingACardRavenAlreadyKnowsAbout:
    """
    From his screen, 2026-08-04. Two rows, both $1,279.87, both dated Aug 3:

        BILT CARD              -1,279.87  SoFi Checking      uncategorized
        Bilt Housing Payment   -1,279.87  Bilt Obsidian Card Housing (rule)

    The second is the rent, charged to the card. The first is paying that card
    off. Only the second is spending — but the first was not flagged, so the
    month counted his rent twice, and "Credit Card Payments" came out as his
    largest category at $3,072.65.

    Rules 2 and 3 both need the card's own leg to exist. A payment made today
    against a card that posts it tomorrow has neither.
    """

    def _row(self, merchant, description=""):
        import types

        return types.SimpleNamespace(
            merchant_name=merchant, original_description=description
        )

    CARDS = ["Bilt Obsidian Card", "Apple Card", "Costco Anywhere Visa® Card by Citi"]

    def test_his_bilt_payment_is_recognised(self):
        from app.services.transfers import names_one_of_our_cards

        assert names_one_of_our_cards(self._row("BILT CARD"), self.CARDS)

    def test_his_apple_card_payment_is_recognised(self):
        from app.services.transfers import names_one_of_our_cards

        assert names_one_of_our_cards(self._row("Apple Card"), self.CARDS)

    def test_buying_something_from_apple_is_not(self):
        """
        The reason this is a subset test and not a substring one. A substring
        match on "apple" would file an Apple purchase as moving money between
        his own accounts — the same class of silent wrong edit, in the other
        direction.
        """
        from app.services.transfers import names_one_of_our_cards

        assert not names_one_of_our_cards(
            self._row("APPLE.COM/BILL", "APPLE.COM/BILL 866-712-7753"), self.CARDS
        )
        assert not names_one_of_our_cards(
            self._row("Apple Store", "APPLE STORE #R123"), self.CARDS
        )

    def test_a_bare_generic_word_matches_nothing(self):
        """Otherwise "CARD" alone would match every card in the house."""
        from app.services.transfers import names_one_of_our_cards

        assert not names_one_of_our_cards(self._row("CARD"), self.CARDS)
        assert not names_one_of_our_cards(self._row("CREDIT CARD"), self.CARDS)

    def test_an_ordinary_merchant_is_untouched(self):
        from app.services.transfers import names_one_of_our_cards

        for merchant in ("Dunkin'", "Doggie Doos Grooming", "Dept Education"):
            assert not names_one_of_our_cards(self._row(merchant), self.CARDS)

    def test_a_household_with_no_cards_matches_nothing(self):
        from app.services.transfers import names_one_of_our_cards

        assert not names_one_of_our_cards(self._row("BILT CARD"), [])

    def test_the_rule_only_looks_at_outflows_from_asset_accounts(self):
        """
        The rent charge itself is on the *card* and must stay spending. Marking
        it would remove the very thing the payment is settling.
        """
        import inspect

        from app.services.transfers import link_transfer_pairs

        source = inspect.getsource(link_transfer_pairs)
        rule_four = source.split("# Rule 4", 1)[1]
        assert "AccountKind.asset" in rule_four
        assert "for outflow in outflows" in rule_four
