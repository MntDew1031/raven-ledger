"""
The organizer proposes; a person decides.

The design constraint Alex set: "have me approve and edit it after". So the
tests that matter are less about what it suggests than about what it refuses to
do without being told.
"""

import inspect

from app.services import organizer, organizer_apply


class TestNothingIsAppliedWithoutApproval:
    def test_the_generator_never_writes_to_a_transaction(self):
        """
        Every proposal builder returns AiProposal objects. If one of them ever
        assigns to a Transaction field directly, the review step is a fiction.
        """
        for name in (
            "propose_transfers",
            "propose_exclusions",
            "propose_rules",
            "propose_budget",
            "propose_categories",
        ):
            source = inspect.getsource(getattr(organizer, name))
            for forbidden in (
                "transaction.category_id =",
                "transaction.is_transfer =",
                "transaction.excluded_from_budget =",
                "db.add(CategorizationRule",
                "db.add(BudgetLine",
            ):
                assert forbidden not in source, f"{name} writes: {forbidden}"

    def test_only_the_apply_module_changes_the_ledger(self):
        source = inspect.getsource(organizer_apply)
        assert "transaction.is_transfer = True" in source
        assert "db.add(" in source


class TestApplyingIsGuarded:
    def test_every_kind_has_a_handler(self):
        from app.models import ProposalKind

        source = inspect.getsource(organizer_apply.apply_proposal)
        for kind in ProposalKind:
            assert f"ProposalKind.{kind.value}" in source

    def test_a_vanished_target_is_refused_not_forced(self):
        source = inspect.getsource(organizer_apply._load_transactions)
        assert "StaleProposal" in source

    def test_transfers_set_both_flags(self):
        """
        One without the other hides a row from one screen and leaves it on
        another, which is worse than being wrong consistently.
        """
        source = inspect.getsource(organizer_apply._apply_transfer)
        assert "is_transfer = True" in source
        assert "excluded_from_budget = True" in source

    def test_an_approved_category_becomes_a_human_decision(self):
        """
        Otherwise the next deterministic pass would overwrite the thing the
        person just agreed to.
        """
        source = inspect.getsource(organizer_apply._apply_category)
        assert 'categorization_source = "manual"' in source

    def test_an_accepted_rule_never_outranks_a_hand_written_one(self):
        source = inspect.getsource(organizer_apply._apply_rule)
        assert "highest" in source and "+ 1" in source

    def test_a_hand_written_rule_wins_a_collision(self):
        source = inspect.getsource(organizer_apply._apply_rule)
        assert "already a rule" in source

    def test_budget_targets_the_month_it_was_run_for(self):
        """
        Approving a week later must not retarget the plan at whatever month it
        happens to be now.
        """
        assert '"month"' in inspect.getsource(organizer.propose_budget)
        assert 'payload.get("month")' in inspect.getsource(
            organizer_apply._apply_budget
        )


class TestProposalsAreConservative:
    def test_a_rule_needs_more_than_a_coincidence(self):
        assert organizer.RULE_MIN_SIGHTINGS >= 3

    def test_a_merchant_filed_two_ways_gets_no_rule(self):
        """A rule there would pick a side in an argument it did not witness."""
        source = inspect.getsource(organizer.propose_rules)
        assert "len(categories) != 1" in source

    def test_budget_needs_more_than_one_month(self):
        source = inspect.getsource(organizer.propose_budget)
        assert "len(values) < 2" in source

    def test_budget_uses_the_median_not_the_mean(self):
        """One holiday should not become the monthly plan."""
        source = inspect.getsource(organizer.propose_budget)
        assert "median" in source
        assert "sum(" not in source

    def test_transfers_between_bank_accounts_are_less_confident(self):
        source = inspect.getsource(organizer.propose_transfers)
        assert "0.9 if to_card or payment_shaped else 0.6" in source


class TestRunReplacesRatherThanAccumulates:
    def test_pending_proposals_are_cleared_first(self):
        assert "clear_pending" in inspect.getsource(organizer.run)

    def test_decided_proposals_are_kept(self):
        source = inspect.getsource(organizer.clear_pending)
        assert "ProposalStatus.pending" in source


class TestDuplicates:
    """
    Providers occasionally post the same charge twice when it settles. It
    silently corrupts every total, because a duplicate of a real purchase looks
    exactly like a real purchase.
    """

    def test_the_window_is_narrow(self):
        """Wider and genuinely repeated purchases start being flagged."""
        assert organizer.DUPLICATE_WINDOW_DAYS <= 3

    def test_it_matches_on_account_amount_and_merchant(self):
        source = inspect.getsource(organizer.propose_duplicates)
        assert "item.account_id, item.amount, key" in source

    def test_only_the_later_one_is_excluded(self):
        """Dropping both would understate the month by the whole amount."""
        source = inspect.getsource(organizer.propose_duplicates)
        assert '"transaction_ids": [str(later.id)]' in source
        assert "kept_transaction_id" in source

    def test_a_duplicate_is_excluded_not_deleted(self):
        """
        The row is real and the provider really sent it. Destroying bank data
        to tidy a total is not a trade worth making.
        """
        source = inspect.getsource(organizer_apply.apply_proposal)
        assert "ProposalKind.duplicate: _apply_exclusion" in source

    def test_closer_together_means_more_confident(self):
        source = inspect.getsource(organizer.propose_duplicates)
        assert "0.75 if gap <= 1 else 0.6" in source


class TestOneMerchantIsOneProposal:
    """
    The organizer offered Alex two rules for Dunkin' in the same list:
    "Dunkin' Donuts · 3 transactions" and "Dunkin' · 3 transactions". The bank
    writes the shop both ways, normalizing keeps both, and each cleared the
    three-sighting bar on its own.

    A proposed rule matches with `contains`, so a rule on `dunkin` already
    catches `dunkin donuts`. The longer key is redundant.
    """

    def _tx(self, category):
        import types

        return types.SimpleNamespace(category_id=category)

    def test_the_general_key_absorbs_the_specific_one(self):
        from app.services.organizer import _collapse_contained

        out = _collapse_contained({
            "dunkin donuts": [self._tx("dining")] * 3,
            "dunkin": [self._tx("dining")] * 3,
        })
        assert set(out) == {"dunkin"}
        assert len(out["dunkin"]) == 6, "both spellings count toward one rule"

    def test_collapsing_is_by_token_not_substring(self):
        """
        `star` must not swallow `starbucks`. Substring matching would merge
        shops that merely share letters, which is a worse failure than the
        duplicate it fixes.
        """
        from app.services.organizer import _collapse_contained

        out = _collapse_contained({
            "star": [self._tx("fun")] * 3,
            "starbucks": [self._tx("dining")] * 3,
        })
        assert set(out) == {"star", "starbucks"}

    def test_keys_that_disagree_about_the_category_stay_apart(self):
        """
        Merging them would build a rule that silently overrules one of the
        two — the same reason a single key filed two ways is skipped.
        """
        from app.services.organizer import _collapse_contained

        out = _collapse_contained({
            "amazon": [self._tx("shopping")] * 3,
            "amazon prime": [self._tx("subscriptions")] * 3,
        })
        assert set(out) == {"amazon", "amazon prime"}

    def test_an_unrelated_merchant_is_untouched(self):
        from app.services.organizer import _collapse_contained

        out = _collapse_contained({
            "dunkin": [self._tx("dining")] * 3,
            "bodyalive": [self._tx("fun")] * 4,
        })
        assert set(out) == {"dunkin", "bodyalive"}
        assert len(out["bodyalive"]) == 4
