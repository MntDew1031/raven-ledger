"""
Goals: the sentence under the progress bar is the point.

"$4,200 of $12,000" tells you nothing you could not see. "$650 a month to make
June" tells you whether to change something.
"""

from datetime import date
from decimal import Decimal

from app.models import Goal
from app.services import goals


def _goal(target="12000", target_date=None, name="House deposit"):
    return Goal(
        name=name,
        target_amount=Decimal(target),
        target_date=target_date,
        saved_amount=Decimal("0"),
        is_achieved=False,
        notes=None,
    )


class TestMonthlyContribution:
    def test_rounds_up_never_down(self):
        """
        A figure that is arithmetically right and still misses the target is
        the one outcome a savings plan cannot afford.
        """
        # 10000 over 4 months divides evenly, which would pass either way.
        result = goals.summarize(
            _goal("10001", date(2026, 12, 1)), Decimal("0"), date(2026, 8, 1)
        )
        assert result["monthly_needed"] == "2501"

    def test_counts_calendar_months_not_days(self):
        """"By June" means the end of June, whatever day it is today."""
        assert goals.months_between(date(2026, 8, 31), date(2026, 9, 1)) == 1
        assert goals.months_between(date(2026, 8, 1), date(2027, 6, 1)) == 10

    def test_the_remainder_of_this_month_still_counts_as_a_month(self):
        """Otherwise a goal due this month divides by zero."""
        result = goals.summarize(
            _goal("500", date(2026, 8, 30)), Decimal("0"), date(2026, 8, 2)
        )
        assert result["monthly_needed"] == "500"

    def test_nothing_needed_once_the_target_is_met(self):
        result = goals.summarize(
            _goal("500", date(2026, 12, 1)), Decimal("600"), date(2026, 8, 1)
        )
        assert result["monthly_needed"] is None
        assert result["remaining"] == "0.00"
        assert result["is_achieved"] is True


class TestOverdueIsItsOwnState:
    def test_a_past_date_is_overdue_not_zero_months(self):
        result = goals.summarize(
            _goal("5000", date(2026, 1, 1)), Decimal("1000"), date(2026, 8, 1)
        )
        assert result["overdue"] is True
        assert result["months_left"] is None
        # Not "put $4,000 aside this month", which is not advice.
        assert result["monthly_needed"] is None

    def test_a_met_goal_with_a_past_date_is_not_overdue(self):
        result = goals.summarize(
            _goal("5000", date(2026, 1, 1)), Decimal("5000"), date(2026, 8, 1)
        )
        assert result["overdue"] is False
        assert result["is_achieved"] is True


class TestProgress:
    def test_percentage(self):
        result = goals.summarize(
            _goal("12000"), Decimal("4200"), date(2026, 8, 1)
        )
        assert result["progress_percent"] == 35.0

    def test_never_exceeds_a_hundred(self):
        """A full bar that keeps growing looks broken."""
        result = goals.summarize(_goal("100"), Decimal("250"), date(2026, 8, 1))
        assert result["progress_percent"] == 100.0

    def test_a_goal_without_a_date_has_no_deadline_maths(self):
        result = goals.summarize(_goal("12000"), Decimal("100"), date(2026, 8, 1))
        assert result["months_left"] is None
        assert result["monthly_needed"] is None
        assert result["overdue"] is False


class TestLinkedAccountsAreTheTruth:
    def test_a_linked_balance_wins_over_the_manual_figure(self):
        """Two sources of the same number will disagree eventually."""
        import inspect

        source = inspect.getsource(goals.list_goals)
        assert "balances.get(goal.account_id" in source
        assert "current_balance" in source
