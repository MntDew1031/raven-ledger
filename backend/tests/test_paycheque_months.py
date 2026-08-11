"""
A month is not one twelfth of a year, and the old budget logic treated it as one.

The representative fixture pays $2,049.70 every two weeks. An annual average
is $4,441.02 a month, but only $4,099.40 lands in a two-paycheque month. Ten
months of the year the old calculation over-planned by $341.62.

These call the arithmetic rather than reading its source, so they fail when the
answer changes rather than when the code moves.
"""

from datetime import date
from decimal import Decimal

from app.models import PayCadence as C
from app.services.income import (
    baseline_payments,
    monthly_equivalent,
    payments_in_month,
)

BIWEEKLY_INCOME = Decimal("2049.70")
ANCHOR = date(2026, 1, 2)


class TestTheYearStillAddsUp:
    """
    The safety property. Whatever the month-by-month counts are, they have to
    sum to the cadence's payments per year — otherwise the new month figure
    disagrees with the average it replaces, and one of them is wrong.
    """

    def test_biweekly_sums_to_twenty_six(self):
        counts = [
            payments_in_month(C.biweekly, ANCHOR, date(2026, m, 1))
            for m in range(1, 13)
        ]
        assert sum(counts) == 26
        assert sorted(set(counts)) == [2, 3]
        assert counts.count(3) == 2, "two months a year carry a third cheque"

    def test_weekly_sums_to_fifty_two(self):
        counts = [
            payments_in_month(C.weekly, ANCHOR, date(2026, m, 1))
            for m in range(1, 13)
        ]
        assert sum(counts) == 52
        assert counts.count(5) == 4

    def test_semimonthly_needs_no_anchor_and_sums_to_twenty_four(self):
        counts = [
            payments_in_month(C.semimonthly, None, date(2026, m, 1))
            for m in range(1, 13)
        ]
        assert counts == [2] * 12

    def test_it_holds_across_a_leap_year(self):
        counts = [
            payments_in_month(C.biweekly, date(2028, 1, 7), date(2028, m, 1))
            for m in range(1, 13)
        ]
        assert sum(counts) == 26


class TestBiweeklyIncomeExample:
    def test_two_cheque_month_uses_actual_count(self):
        count = payments_in_month(C.biweekly, ANCHOR, date(2026, 8, 1))
        assert count == 2
        assert BIWEEKLY_INCOME * count == Decimal("4099.40")

    def test_annual_average_is_distinct(self):
        assert monthly_equivalent(BIWEEKLY_INCOME, C.biweekly) == Decimal("4441.02")

    def test_and_the_gap_is_what_the_budget_was_over_planning(self):
        gap = monthly_equivalent(BIWEEKLY_INCOME, C.biweekly) - BIWEEKLY_INCOME * 2
        assert gap == Decimal("341.62")

    def test_a_three_cheque_month_exists_and_is_bigger(self):
        assert payments_in_month(C.biweekly, ANCHOR, date(2026, 7, 1)) == 3
        assert BIWEEKLY_INCOME * 3 == Decimal("6149.10")


class TestWithoutAnAnchorItSaysSoRatherThanGuessing:
    """
    A household that has not given a pay date gets the average, and the caller
    is told the figure is not a count. Returning a plausible number with no way
    to know it was invented is how a wrong figure survives.
    """

    def test_biweekly_without_an_anchor_is_unknowable(self):
        assert payments_in_month(C.biweekly, None, date(2026, 8, 1)) is None

    def test_weekly_without_an_anchor_is_unknowable(self):
        assert payments_in_month(C.weekly, None, date(2026, 8, 1)) is None

    def test_but_monthly_is_always_once(self):
        assert payments_in_month(C.monthly, None, date(2026, 8, 1)) == 1


class TestAnchorsPointingEitherWay:
    """
    People will type the *next* pay date as readily as a past one. Modular
    arithmetic handles both; a loop forward from the anchor would return zero
    for every month before it.
    """

    def test_a_future_anchor_still_counts_a_past_month(self):
        counts = [
            payments_in_month(C.biweekly, date(2026, 12, 25), date(2026, m, 1))
            for m in range(1, 13)
        ]
        assert sum(counts) == 26

    def test_an_anchor_years_ago_agrees_with_a_recent_one(self):
        old = payments_in_month(C.biweekly, date(2006, 1, 6), date(2026, 8, 1))
        recent = payments_in_month(C.biweekly, date(2026, 7, 31), date(2026, 8, 1))
        assert old == recent


class TestBaselines:
    def test_the_two_states_of_the_toggle_are_named_correctly(self):
        assert baseline_payments(C.biweekly) == 2
        assert baseline_payments(C.weekly) == 4
        assert baseline_payments(C.semimonthly) == 2
        assert baseline_payments(C.monthly) == 1
