import uuid

from app.services.ai import _parse_assignments, bind_category
from app.services.provider_categories import (
    hints_for,
    is_account_transfer,
    resolve,
)


def _categories(*names: str) -> dict[str, uuid.UUID]:
    return {name.lower(): uuid.uuid4() for name in names}


class TestBindCategory:
    """
    Small local models are right about the category and careless about the
    string. Every case here was a correct answer the old exact-match binding
    threw away.
    """

    def test_exact_match(self):
        catalog = _categories("Dining", "Housing")
        assert bind_category("Dining", catalog) == catalog["dining"]

    def test_case_and_whitespace_are_irrelevant(self):
        catalog = _categories("Fun Money")
        assert bind_category("  fun money  ", catalog) == catalog["fun money"]

    def test_trailing_punctuation_is_stripped(self):
        catalog = _categories("Utilities")
        assert bind_category("Utilities.", catalog) == catalog["utilities"]

    def test_group_prefix_is_dropped(self):
        catalog = _categories("Dining")
        assert bind_category("Wants > Dining", catalog) == catalog["dining"]

    def test_ampersand_spelled_out(self):
        catalog = _categories("Food & Household")
        assert (
            bind_category("Food and Household", catalog)
            == catalog["food & household"]
        )

    def test_null_answers_mean_no_category(self):
        catalog = _categories("Dining")
        for answer in ("", "null", "None", "n/a", "  "):
            assert bind_category(answer, catalog) is None

    def test_unknown_category_is_refused(self):
        catalog = _categories("Dining", "Housing")
        assert bind_category("Cryptocurrency", catalog) is None

    def test_ambiguous_containment_is_refused(self):
        # "Fund" is inside both. Guessing between them would be a coin flip,
        # and a wrong category is worse than none.
        catalog = _categories("Emergency Fund", "College Fund")
        assert bind_category("Fund", catalog) is None

    def test_unambiguous_containment_is_accepted(self):
        catalog = _categories("Emergency Fund", "Dining")
        assert (
            bind_category("Emergency Fund savings", catalog)
            == catalog["emergency fund"]
        )


class TestParseAssignments:
    def test_plain_json(self):
        content = '{"assignments": [{"id": "m0", "category": "Dining"}]}'
        assert _parse_assignments(content) == {"m0": "Dining"}

    def test_reasoning_block_is_stripped(self):
        content = (
            "<think>The user wants { braces } in my thoughts</think>"
            '{"assignments": [{"id": "m1", "category": "Housing"}]}'
        )
        assert _parse_assignments(content) == {"m1": "Housing"}

    def test_code_fence_is_stripped(self):
        content = '```json\n{"assignments": [{"id": "m2", "category": "Dining"}]}\n```'
        assert _parse_assignments(content) == {"m2": "Dining"}

    def test_null_is_an_answer_not_a_failure(self):
        # An empty result would trigger the retry-in-halves path; a model
        # saying "none of these fit" must not be mistaken for one that failed.
        content = '{"assignments": [{"id": "m0", "category": null}]}'
        assert _parse_assignments(content) == {"m0": ""}

    def test_garbage_yields_nothing(self):
        assert _parse_assignments("I am afraid I cannot help with that") == {}


class TestProviderCategories:
    def test_detailed_code_beats_primary(self):
        assert "grocer" in hints_for("FOOD_AND_DRINK_GROCERIES")
        assert "dining" in hints_for("FOOD_AND_DRINK_RESTAURANT")

    def test_unknown_detailed_falls_back_to_primary(self):
        assert hints_for("FOOD_AND_DRINK_SOMETHING_NEW") == hints_for(
            "FOOD_AND_DRINK"
        )

    def test_unmapped_code_gives_no_hint(self):
        # GENERAL_SERVICES covers a haircut and a lawyer alike; guessing from
        # it would be worse than leaving the transaction for a person.
        assert hints_for("GENERAL_SERVICES_OTHER_GENERAL_SERVICES") == ()
        assert hints_for(None) == ()

    def test_resolves_against_this_households_names(self):
        catalog = _categories("Food & Household", "Dining", "Housing")
        assert (
            resolve("FOOD_AND_DRINK_GROCERIES", catalog)
            == catalog["food & household"]
        )
        assert resolve("FOOD_AND_DRINK_RESTAURANT", catalog) == catalog["dining"]

    def test_returns_nothing_when_no_category_fits(self):
        assert resolve("MEDICAL_PRIMARY_CARE", _categories("Dining")) is None

    def test_sign_disagreement_blocks_the_match(self):
        catalog = _categories("Income", "Dining")
        income = frozenset({catalog["income"]})
        assert resolve("INCOME_WAGES", catalog, income, is_inflow=True) == (
            catalog["income"]
        )
        # A negative amount coded INCOME is a payroll reversal, not a paycheck.
        assert resolve("INCOME_WAGES", catalog, income, is_inflow=False) is None

    def test_account_transfers_are_recognised_narrowly(self):
        assert is_account_transfer("TRANSFER_IN_ACCOUNT_TRANSFER")
        assert is_account_transfer("TRANSFER_OUT_ACCOUNT_TRANSFER")
        # A deposited paycheck is a TRANSFER_IN but is not an internal move.
        assert not is_account_transfer("TRANSFER_IN_DEPOSIT")
        assert not is_account_transfer(None)


class TestUnreviewedGuess:
    """
    The predicate that decides what the AI is allowed to look at.

    This exists because the AI silently did nothing for weeks. It was offered
    only rows with no category at all, while the deterministic pass — which
    runs first on every sync — had already stamped Plaid's category on very
    nearly everything. The queue said 76 to review; the run said 0 to do.

    The rules bug earlier in this project was the same mistake in a different
    file. So the assertions below are about *which sources* may be revisited,
    not about the SQL, and the last one checks the dashboard count and the job
    now read from one predicate rather than two that can drift.
    """

    def _sources(self):
        from app.services.ai import WEAK_SOURCES

        return WEAK_SOURCES

    def test_lookup_table_guesses_may_be_revisited(self):
        # The two the deterministic pass produces without any human input.
        assert self._sources() == {"provider_category", "keyword_model"}

    def test_human_and_rule_decisions_are_off_limits(self):
        for source in ("manual", "split", "household_rule", "merchant_memory"):
            assert source not in self._sources(), source

    def test_the_ai_does_not_revisit_itself(self):
        # Non-deterministic: re-asking lets identical input flip between runs.
        assert "ai" not in self._sources()

    def test_predicate_covers_uncategorized_and_weak_guesses(self):
        from app.services.ai import unreviewed_guess

        clause = str(
            unreviewed_guess().compile(compile_kwargs={"literal_binds": True})
        )
        assert "category_id IS NULL" in clause
        assert "provider_category" in clause and "keyword_model" in clause

    def test_dashboard_count_and_job_share_one_predicate(self):
        """The two used to be written out separately, and drifted."""
        import inspect

        from app.api import transactions

        source = inspect.getsource(transactions.ai_review)
        assert "unreviewed_guess()" in source
        assert "category_id.is_(None)" not in source
