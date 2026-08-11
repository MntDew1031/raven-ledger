"""
Turning pay into a monthly figure.

The trap this module exists to avoid: **being paid every two weeks is not the
same as being paid twice a month.** Bi-weekly is 26 payments a year, not 24, so
the monthly equivalent is `amount * 26 / 12` — and doubling it under-counts.

Representative fixture values are used throughout so the calculations stay
concrete and regression failures remain easy to understand.
"""

from decimal import Decimal

import pytest

from app.models import PayCadence
from app.services.income import (
    CADENCE_LABELS,
    PAYMENTS_PER_YEAR,
    extra_paycheque_months,
    monthly_equivalent,
)

BIWEEKLY_INCOME_A = Decimal("2049.00")
BIWEEKLY_INCOME_B = Decimal("1340.00")


class TestBiweeklyIsNotSemimonthly:
    def test_alex(self):
        # 2049 * 26 / 12
        assert monthly_equivalent(
            BIWEEKLY_INCOME_A, PayCadence.biweekly
        ) == Decimal("4439.50")

    def test_jordan(self):
        # 1340 * 26 / 12
        assert monthly_equivalent(
            BIWEEKLY_INCOME_B, PayCadence.biweekly
        ) == Decimal("2903.33")

    def test_together(self):
        total = monthly_equivalent(
            BIWEEKLY_INCOME_A, PayCadence.biweekly
        ) + monthly_equivalent(BIWEEKLY_INCOME_B, PayCadence.biweekly)
        assert total == Decimal("7342.83")

    def test_doubling_would_have_been_wrong(self):
        """
        The mistake in plain arithmetic: $564.83 a month unaccounted for, and
        the two extra paycheques a year left looking like a windfall.
        """
        naive = (BIWEEKLY_INCOME_A + BIWEEKLY_INCOME_B) * 2
        correct = monthly_equivalent(
            BIWEEKLY_INCOME_A, PayCadence.biweekly
        ) + monthly_equivalent(BIWEEKLY_INCOME_B, PayCadence.biweekly)
        assert naive == Decimal("6778.00")
        assert correct - naive == Decimal("564.83")

    def test_semimonthly_really_is_double(self):
        assert monthly_equivalent(
            BIWEEKLY_INCOME_A, PayCadence.semimonthly
        ) == Decimal("4098.00")


class TestEveryCadence:
    @pytest.mark.parametrize(
        "cadence,per_year",
        [
            (PayCadence.weekly, 52),
            (PayCadence.biweekly, 26),
            (PayCadence.semimonthly, 24),
            (PayCadence.monthly, 12),
            (PayCadence.annual, 1),
        ],
    )
    def test_payments_per_year(self, cadence, per_year):
        assert PAYMENTS_PER_YEAR[cadence] == Decimal(per_year)

    def test_monthly_is_itself(self):
        assert monthly_equivalent(Decimal("6829.74"), PayCadence.monthly) == Decimal(
            "6829.74"
        )

    def test_annual_divides_by_twelve(self):
        assert monthly_equivalent(Decimal("120000"), PayCadence.annual) == Decimal(
            "10000.00"
        )

    def test_every_cadence_has_a_label(self):
        for cadence in PayCadence:
            assert CADENCE_LABELS[cadence]


class TestExtraPaychequeMonths:
    """
    Two months a year hold three bi-weekly paycheques. Worth naming, because
    that money looks like a windfall and is already counted in the average.
    """

    def test_biweekly_has_two(self):
        assert extra_paycheque_months(PayCadence.biweekly) == 2

    def test_weekly_has_four(self):
        assert extra_paycheque_months(PayCadence.weekly) == 4

    def test_the_regular_cadences_have_none(self):
        for cadence in (
            PayCadence.semimonthly,
            PayCadence.monthly,
            PayCadence.annual,
        ):
            assert extra_paycheque_months(cadence) == 0


class TestRounding:
    def test_rounds_to_the_cent(self):
        value = monthly_equivalent(BIWEEKLY_INCOME_B, PayCadence.biweekly)
        assert value.as_tuple().exponent == -2

    def test_sources_are_rounded_before_summing(self):
        """
        Rounding once at the end gives a total that does not equal the sum of
        the figures printed beside each name, which reads as a bug every time
        somebody checks the addition by hand.
        """
        import inspect

        from app.services import income

        assert "quantize" in inspect.getsource(income.monthly_equivalent)
        assert "monthly_equivalent(item.amount, item.cadence)" in inspect.getsource(
            income.monthly_total
        )
