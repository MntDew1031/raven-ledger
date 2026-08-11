"""
The assistant may suggest a change. It may not make one.

Alex chose propose → approve → act, so the interesting cases are all about
what a model can and cannot talk Raven into doing.
"""

import json

from app.services.proposals import MAX_AFFECTED, split_proposal


class TestPullingTheProposalOutOfAReply:
    def test_a_clean_proposal_is_parsed_and_hidden(self):
        reply, proposal = split_proposal(
            'You have six uncategorized Chipotle charges.\n'
            'PROPOSE: {"action": "categorize", "merchant": "Chipotle", '
            '"category": "Dining"}'
        )
        assert proposal == {
            "action": "categorize",
            "merchant": "Chipotle",
            "category": "Dining",
        }
        # The marker must never reach the person reading the answer.
        assert "PROPOSE" not in reply
        assert reply == "You have six uncategorized Chipotle charges."

    def test_a_fenced_proposal_still_parses(self):
        """Models wrap JSON in fences however firmly they are told not to."""
        _, proposal = split_proposal(
            'PROPOSE: ```json {"action": "create_rule", "merchant": "Netflix", '
            '"category": "Subscriptions"} ```'
        )
        assert proposal is not None
        assert proposal["action"] == "create_rule"

    def test_unparseable_json_is_dropped_rather_than_shown(self):
        """
        A half-parsed proposal is worse than none — it would put a card on
        screen offering a change nobody can describe.
        """
        reply, proposal = split_proposal(
            "Here you go.\nPROPOSE: {action: categorize, merchant:}"
        )
        assert proposal is None
        assert "PROPOSE" not in reply
        assert reply == "Here you go."

    def test_a_reply_with_no_proposal_is_untouched(self):
        reply, proposal = split_proposal("You spent $412.55 at Costco.")
        assert proposal is None
        assert reply == "You spent $412.55 at Costco."

    def test_only_the_first_proposal_is_taken(self):
        """
        One approval, one change. Two cards from one reply would make it
        ambiguous which one the button applied to.
        """
        _, proposal = split_proposal(
            'PROPOSE: {"action": "categorize", "merchant": "A", "category": "X"}\n'
            'PROPOSE: {"action": "categorize", "merchant": "B", "category": "Y"}'
        )
        assert proposal["merchant"] == "A"

    def test_a_json_array_is_not_a_proposal(self):
        _, proposal = split_proposal('PROPOSE: ["categorize", "Chipotle"]')
        assert proposal is None


class TestTheCeiling:
    def test_one_approval_cannot_rewrite_a_whole_ledger(self):
        """
        Above this a proposal stops being a suggestion and becomes a migration.
        The number matters less than that there is one.
        """
        assert 0 < MAX_AFFECTED <= 500


class TestWhatTheModelIsToldToSend:
    """
    The prompt and the parser have to agree about the shape, and they are
    written in different files — so this pins the contract rather than trusting
    that whoever edits one remembers the other.
    """

    def test_the_prompt_documents_the_exact_keys_the_parser_reads(self):
        from app.services.assistant import SYSTEM_PROMPT

        for key in ("action", "merchant", "category"):
            assert f'\\"{key}\\"' in SYSTEM_PROMPT or f'"{key}"' in SYSTEM_PROMPT

    def test_the_prompt_forbids_transaction_ids(self):
        """
        The one instruction that matters most: a model asked for row ids will
        invent them, and an invented id either matches nothing or matches
        something unrelated.
        """
        from app.services.assistant import SYSTEM_PROMPT

        assert "never include transaction ids" in SYSTEM_PROMPT.lower()

    def test_both_kinds_the_parser_accepts_are_offered(self):
        from app.services.assistant import SYSTEM_PROMPT
        from app.services.proposals import KINDS

        for kind in KINDS:
            assert kind in SYSTEM_PROMPT

    def test_an_example_from_the_prompt_round_trips_through_the_parser(self):
        """
        End to end on the literal shape the model is shown, because a prompt
        that documents a shape the parser rejects produces a proposal that
        silently never appears.
        """
        example = {
            "action": "categorize",
            "merchant": "Chipotle",
            "category": "Dining",
        }
        _, parsed = split_proposal("Sure.\nPROPOSE: " + json.dumps(example))
        assert parsed == example


class TestASubstringIsABluntInstrument:
    """
    Found by running it, not by reading it. A proposal for "Costco" matched
    `COSTCO VISA PAYMENT` — the leg that pays the card off — and filed $702.69
    of moving money between his own accounts as groceries.

    Card names contain merchant names, which makes this the default outcome
    rather than a corner case. `is_transfer` does not save it: that flag is set
    by the transfer pass on the *next* sync, and a proposal approved before
    then has already done the damage.
    """

    def _row(self, merchant, description):
        import types

        return types.SimpleNamespace(
            merchant_name=merchant, original_description=description
        )

    def test_a_card_payment_is_recognised_by_its_descriptor(self):
        from app.services.transfers import looks_like_a_payment

        assert looks_like_a_payment(
            self._row("Costco Visa", "COSTCO VISA PAYMENT")
        )

    def test_an_ordinary_shop_at_the_same_merchant_is_not(self):
        from app.services.transfers import looks_like_a_payment

        assert not looks_like_a_payment(self._row("Costco", "COSTCO WHSE #219"))

    def test_the_resolver_applies_that_filter(self):
        import inspect

        from app.services.proposals import matching_transactions

        source = inspect.getsource(matching_transactions)
        assert "looks_like_a_payment(row)" in source, (
            "without this a proposal for a merchant whose name appears in a "
            "card's name will categorise the card payment"
        )
