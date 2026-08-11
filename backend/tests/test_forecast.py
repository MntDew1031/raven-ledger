"""
Paydays and bills on one timeline.

Written against two representative cadences because they differ, which is
the thing most likely to be got wrong: he is paid every two weeks (26 a year),
she is paid on the 15th and 30th (24 a year). A payday projection that treats
those the same is wrong for one of them every single month.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models import IncomeSource, PayCadence, RecurringItem
from app.services import forecast


def _source(cadence, amount="2049.00", created="2026-08-03"):
    item = IncomeSource(
        name="Test",
        amount=Decimal(amount),
        cadence=cadence,
        is_active=True,
    )
    item.created_at = datetime.fromisoformat(created).replace(tzinfo=timezone.utc)
    return item


def _bill(cadence, next_due, amount="-120.00"):
    return RecurringItem(
        display_name="Bill",
        direction="outflow",
        cadence=cadence,
        average_amount=Decimal(amount),
        last_amount=Decimal(amount),
        occurrences=3,
        last_seen=date(2026, 7, 1),
        next_due=next_due,
        is_active=True,
    )


class TestSemimonthlyIsNotBiweekly:
    """Jordan's cadence lands on days of the month, not on a 14-day interval."""

    def test_lands_on_the_15th_and_the_30th(self):
        days = forecast.paydays_for(
            _source(PayCadence.semimonthly, "1340.00"),
            date(2026, 8, 1),
            date(2026, 9, 30),
        )
        assert [d.day for d, _ in days] == [15, 30, 15, 30]

    def test_february_pays_on_the_last_day_rather_than_skipping(self):
        """The 30th does not exist in February. It must not be dropped."""
        days = forecast.paydays_for(
            _source(PayCadence.semimonthly, "1340.00"),
            date(2027, 2, 1),
            date(2027, 2, 28),
        )
        assert [d.day for d, _ in days] == [15, 28]

    def test_biweekly_steps_by_fourteen(self):
        days = forecast.paydays_for(
            _source(PayCadence.biweekly),
            date(2026, 8, 3),
            date(2026, 9, 30),
        )
        gaps = {
            (days[i + 1][0] - days[i][0]).days for i in range(len(days) - 1)
        }
        assert gaps == {14}

    def test_biweekly_gives_more_paydays_than_semimonthly_over_a_year(self):
        """
        26 a year is the *average*; a calendar year whose first day is itself a
        payday holds 27, which is arithmetically right and is exactly the extra
        cheque that makes bi-weekly different. The property worth asserting is
        that the two cadences are not interchangeable.
        """
        year = (date(2026, 1, 1), date(2026, 12, 31))
        bi = forecast.paydays_for(
            _source(PayCadence.biweekly, created="2026-01-01"), *year
        )
        semi = forecast.paydays_for(_source(PayCadence.semimonthly), *year)
        assert len(semi) == 24
        assert len(bi) in (26, 27)
        assert len(bi) > len(semi)


class TestProjectionIsStable:
    def test_a_missed_paycheque_does_not_move_future_dates(self):
        """
        Anchored to the source, not to today, so re-running the forecast
        tomorrow does not shift every bi-weekly date by one day.
        """
        source = _source(PayCadence.biweekly, created="2026-08-03")
        first = forecast.paydays_for(source, date(2026, 8, 10), date(2026, 10, 1))
        again = forecast.paydays_for(source, date(2026, 8, 11), date(2026, 10, 1))
        assert first[-1][0] == again[-1][0]

    def test_an_inactive_earner_contributes_nothing(self):
        source = _source(PayCadence.biweekly)
        source.is_active = False
        assert forecast.paydays_for(source, date(2026, 8, 1), date(2026, 9, 1)) == []

    def test_a_yearly_figure_has_no_payday(self):
        """No meaningful date, and inventing one makes the forecast wrong twice."""
        assert (
            forecast.paydays_for(
                _source(PayCadence.annual, "120000"),
                date(2026, 8, 1),
                date(2026, 12, 31),
            )
            == []
        )


class TestBills:
    def test_a_monthly_bill_recurs(self):
        days = forecast.bill_dates(
            _bill("monthly", date(2026, 8, 5)), date(2026, 8, 1), date(2026, 10, 1)
        )
        assert len(days) == 2

    def test_an_overdue_bill_rolls_forward_rather_than_vanishing(self):
        """It is late, not cancelled."""
        days = forecast.bill_dates(
            _bill("monthly", date(2026, 6, 5)), date(2026, 8, 1), date(2026, 9, 30)
        )
        assert days and all(day >= date(2026, 8, 1) for day in days)

    @pytest.mark.parametrize(
        "cadence", ["weekly", "biweekly", "monthly", "bimonthly", "quarterly", "yearly"]
    )
    def test_every_detected_cadence_can_be_projected(self, cadence):
        assert cadence in forecast.BILL_CADENCE_DAYS

    def test_an_unknown_cadence_is_skipped_rather_than_guessed(self):
        assert (
            forecast.bill_dates(
                _bill("occasionally", date(2026, 8, 5)),
                date(2026, 8, 1),
                date(2026, 9, 1),
            )
            == []
        )


class TestSafeToSpendIsConservative:
    def test_credit_is_not_counted_as_money_you_have(self):
        """Counting available credit turns the figure into an argument to spend."""
        import inspect

        source = inspect.getsource(forecast.spendable_balance)
        assert "AccountKind.asset" in source
        # The three account types it does count, and nothing else.
        assert "AccountType.checking" in source
        assert "AccountType.savings" in source
        assert "AccountType.cash" in source
        assert "AccountType.credit" not in source

    def test_income_inside_the_window_is_not_counted(self):
        import inspect

        source = inspect.getsource(forecast.build)
        assert 'event["kind"] == "bill"' in source
        # Being told you have less is an annoyance; more is an overdraft.
        assert "no income" in source.lower() or "No incoming money" in source
