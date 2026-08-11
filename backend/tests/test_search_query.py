"""
Plain-English search.

The model never touches the database: it returns JSON, that JSON is validated
field by field against a closed schema, and anything unrecognised is dropped.
A hallucinated filter becomes an ignored filter rather than a query.
"""

from datetime import date

import pytest

from app.services.search_query import ALLOWED, parse, resolve_period

TODAY = date(2026, 8, 2)


class TestValidation:
    def test_a_normal_reply(self):
        assert parse(
            '{"text": "costco", "min_amount": 100, "period": "spring"}', TODAY
        ) == {
            "text": "costco",
            "min_amount": 100.0,
            "start": "2026-03-01",
            "end": "2026-05-31",
        }

    def test_unknown_keys_are_dropped_not_passed_on(self):
        """A hallucinated key must not reach the query builder."""
        out = parse(
            '{"text": "x", "sql": "DROP TABLE transactions", "limit": 999}', TODAY
        )
        assert set(out) <= ALLOWED
        assert "sql" not in out

    def test_prose_around_the_json_is_tolerated(self):
        out = parse('Sure! ```json\n{"text": "netflix"}\n``` Hope that helps.', TODAY)
        assert out == {"text": "netflix"}

    @pytest.mark.parametrize("junk", ["", "no json here", "{", "[1,2,3]", "null"])
    def test_unusable_replies_yield_nothing(self, junk):
        """
        Empty means "I did not understand", which the caller shows differently
        from "no results" — they look identical on screen and mean opposite
        things.
        """
        assert parse(junk, TODAY) == {}

    def test_amounts_given_backwards_are_swapped(self):
        """Otherwise the screen is confidently empty."""
        out = parse('{"min_amount": 500, "max_amount": 100}', TODAY)
        assert out["min_amount"] == 100.0
        assert out["max_amount"] == 500.0

    def test_amounts_written_as_strings_are_accepted(self):
        out = parse('{"min_amount": "$1,200.50"}', TODAY)
        assert out["min_amount"] == 1200.50

    def test_a_nonsense_direction_is_dropped(self):
        assert "direction" not in parse('{"direction": "sideways"}', TODAY)

    def test_a_real_direction_survives(self):
        assert parse('{"direction": "in"}', TODAY)["direction"] == "in"

    def test_an_absurd_year_is_ignored(self):
        assert parse('{"period": "this_year", "year": 12026}', TODAY)["start"] == (
            "2026-01-01"
        )


class TestPeriodsAreResolvedHereNotByTheModel:
    """Models are unreliable at "last spring", and a wrong range is invisible."""

    def test_last_month_crosses_into_the_previous_year(self):
        start, end = resolve_period("last_month", None, date(2026, 1, 15))
        assert (start, end) == (date(2025, 12, 1), date(2025, 12, 31))

    def test_winter_spans_the_new_year(self):
        start, end = resolve_period("winter", 2026, TODAY)
        assert start == date(2025, 12, 1)
        assert end == date(2026, 2, 28)

    def test_a_season_still_ahead_means_last_year(self):
        """Nobody asks about spending they have not done yet."""
        start, _ = resolve_period("autumn", None, date(2026, 3, 1))
        assert start.year == 2025

    def test_a_season_already_past_means_this_year(self):
        start, _ = resolve_period("spring", None, TODAY)
        assert start == date(2026, 3, 1)

    def test_month_ends_are_real(self):
        _, end = resolve_period("last_month", None, date(2026, 3, 5))
        assert end == date(2026, 2, 28)

    def test_an_unknown_period_resolves_to_nothing(self):
        assert resolve_period("whenever", None, TODAY) == (None, None)

    def test_a_bare_year_becomes_that_whole_year(self):
        assert resolve_period(None, 2024, TODAY) == (
            date(2024, 1, 1),
            date(2024, 12, 31),
        )
