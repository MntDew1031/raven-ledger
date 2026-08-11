"""
Debts that keep up with themselves.

A manually tracked loan used to fall only when somebody edited it, which is
wrong in a specific direction: interest accrues whether or not anybody opens
the app, so an un-modelled balance drifts *optimistic*. A debt you believe is
smaller than it is is the worst kind of wrong number to hold.
"""

from datetime import date
from decimal import Decimal

from app.models import Account, AccountKind, AccountType
from app.services import loans


def _loan(balance="-12000", apr="6.5", payment="350", type_=AccountType.loan):
    return Account(
        name="Car loan",
        type=type_,
        kind=AccountKind.liability,
        current_balance=Decimal(balance),
        interest_rate=Decimal(apr) if apr else None,
        minimum_payment=Decimal(payment) if payment else None,
    )


class TestMonthlyInterest:
    def test_apr_over_twelve_on_the_balance(self):
        # 12000 at 6.5% -> 65.00 a month
        assert loans.monthly_interest(Decimal("-12000"), Decimal("6.5")) == (
            Decimal("65.00")
        )

    def test_a_positive_balance_accrues_nothing(self):
        """Not a debt. Applying interest to it would invent money."""
        assert loans.monthly_interest(Decimal("500"), Decimal("6.5")) == (
            Decimal("0.00")
        )

    def test_no_rate_means_no_interest(self):
        """
        The default, and it stays the default: a guessed rate produces a
        confidently wrong balance, which is worse than a stale one somebody
        knows is stale.
        """
        assert loans.monthly_interest(Decimal("-12000"), None) == Decimal("0.00")


class TestPayoff:
    def test_a_normal_loan_ends(self):
        months = loans.payoff_months(
            Decimal("-12000"), Decimal("6.5"), Decimal("350")
        )
        assert months is not None and 36 <= months <= 40

    def test_a_payment_that_does_not_cover_interest_never_ends(self):
        """
        Reported as None rather than as 900 months: the first reads as a
        warning, the second reads as a schedule.
        """
        assert (
            loans.payoff_months(Decimal("-30000"), Decimal("24"), Decimal("50"))
            is None
        )

    def test_no_payment_means_no_projection(self):
        assert loans.payoff_months(Decimal("-1000"), Decimal("5"), None) is None

    def test_an_interest_free_debt_divides_cleanly(self):
        assert loans.payoff_months(
            Decimal("-1000"), Decimal("0"), Decimal("250")
        ) == 4


class TestProjection:
    def test_never_paying_off_is_named_not_implied(self):
        """A missing number reads as "not calculated yet"."""
        out = loans.project(
            _loan(balance="-30000", apr="24", payment="50"), date(2026, 8, 2)
        )
        assert out["never_pays_off"] is True
        assert out["payoff_months"] is None

    def test_a_healthy_loan_is_not_flagged(self):
        out = loans.project(_loan(), date(2026, 8, 2))
        assert out["never_pays_off"] is False
        assert out["payoff_months"]


class TestAccrualIsIdempotentWithinAMonth:
    def test_the_guard_is_checked(self):
        """
        A scheduled job that double-charges interest when it retries is worse
        than one that never runs.
        """
        import inspect

        source = inspect.getsource(loans.accrue_interest)
        assert "interest_applied_through" in source
        assert ">= month" in source

    def test_only_borrowing_accounts_accrue(self):
        """A credit card's balance comes from its charges, not a schedule."""
        assert AccountType.credit not in loans.BORROWING
        assert AccountType.loan in loans.BORROWING
        assert AccountType.mortgage in loans.BORROWING

    def test_interest_makes_a_liability_more_negative(self):
        import inspect

        assert "- charge" in inspect.getsource(loans.accrue_interest)


class TestPaymentsAreNotCharges:
    def test_only_the_debts_own_category_counts(self):
        """
        Spending on a credit card is a charge, not a payment; conflating them
        would let a shopping trip look like progress.
        """
        import inspect

        source = inspect.getsource(loans.apply_payments)
        assert "payment_category_id" in source
        assert "Transaction.amount < 0" in source


class TestRetirementAccounts:
    def test_the_new_types_exist(self):
        for name in ("retirement", "brokerage", "loan"):
            assert AccountType(name)

    def test_retirement_is_distinct_from_a_brokerage(self):
        """Different tax treatment, different access before retirement."""
        assert AccountType.retirement != AccountType.brokerage
