"""
Does this account add up?

Five classes of bug have corrupted numbers in this ledger — a wrong sign, both
legs of a transfer, a duplicate post, income counted as spending, a keyword
match ignoring the amount — and every one was invisible until a person noticed
a figure looked odd. They share a shape: the transactions stop agreeing with
the balance and nothing says so.
"""

import inspect
from decimal import Decimal

from app.services import reconcile


class TestItNeverCorrectsAnything:
    def test_no_writes_in_the_module(self):
        """
        A reconciliation that adjusts a balance to match its own arithmetic can
        never find anything again.
        """
        source = inspect.getsource(reconcile)
        for write in ("db.add(", "db.commit()", "current_balance =", "db.delete("):
            assert write not in source, write


class TestConnectedAccountsAreNotJudged:
    def test_a_synced_account_reports_not_checkable(self):
        """
        Plaid begins from wherever its cursor started, so the transactions are
        not the whole history. A check that cries wolf on every connected
        account is one nobody reads.
        """
        source = inspect.getsource(reconcile.check_account)
        assert "not account.is_manual" in source
        assert "not_checkable" in source


class TestTolerance:
    def test_it_is_money_not_a_percentage(self):
        """
        A dollar out on a $200 account matters as much as on a $20,000 one, and
        a percentage would hide the second.
        """
        assert isinstance(reconcile.TOLERANCE, Decimal)
        assert reconcile.TOLERANCE <= Decimal("5.00")

    def test_a_small_gap_is_not_reported_as_a_fault(self):
        source = inspect.getsource(reconcile.check_account)
        assert "abs(difference) <= TOLERANCE" in source
        assert '"balanced"' in source


class TestItSaysWhichKindOfProblem:
    def test_a_gap_matching_one_transaction_is_called_a_duplicate(self):
        """A number alone is not a diagnosis."""
        source = inspect.getsource(reconcile.check_account)
        assert "twin" in source
        assert '"duplicate"' in source

    def test_the_match_is_on_magnitude_not_sign(self):
        """
        An extra charge drifts the balance the opposite way from the charge's
        own sign, so matching signed values never fires on the case this
        exists to catch. Found by adding a duplicate and watching it be
        reported as "something missing".
        """
        source = inspect.getsource(reconcile.check_account)
        assert "func.abs(func.abs(Transaction.amount) - abs(difference))" in source

    def test_otherwise_it_names_the_two_other_possibilities(self):
        source = inspect.getsource(reconcile.check_account)
        assert "missing_or_opening" in source
        assert "opening balance" in source

    def test_it_warns_against_papering_over_the_gap(self):
        source = inspect.getsource(reconcile.check_account)
        assert "hide this rather than" in source

    def test_the_inferred_opening_balance_is_named_as_inferred(self):
        """Presenting a derived number as a fact is how this starts lying."""
        source = inspect.getsource(reconcile.check_account)
        assert "implied_opening_balance" in source


class TestSplitsAreNotDoubleCounted:
    def test_countable_guards_the_sums(self):
        source = inspect.getsource(reconcile.check_account)
        assert source.count("countable()") >= 2


class TestRouteOrder:
    """
    `/accounts/reconcile` was declared after `/accounts/{account_id}`, so
    FastAPI matched the parameterised route first and tried to parse
    "reconcile" as a UUID. Static segments have to come first.
    """

    def test_reconcile_is_declared_before_the_parameterised_route(self):
        import inspect

        from app.api import accounts

        source = inspect.getsource(accounts)
        assert source.index('@router.get("/reconcile")') < source.index(
            '@router.get("/{account_id}", response_model=AccountResponse)'
        )


class TestItDoesNotCryWolf:
    """
    The first version compared the balance to the sum of transactions and
    called any gap a fault. For a manual account that gap *is* the opening
    balance, so it fired on every account forever — the fastest way to make a
    warning worthless. Caught by running it on a freshly imported statement.
    """

    def test_without_an_opening_balance_it_says_it_cannot_tell(self):
        source = inspect.getsource(reconcile.check_account)
        assert "account.opening_balance is None" in source
        assert "needs_opening_balance" in source

    def test_and_offers_the_figure_to_use(self):
        source = inspect.getsource(reconcile.check_account)
        assert "suggested_opening_balance" in source

    def test_drift_is_measured_against_the_opening_balance(self):
        source = inspect.getsource(reconcile.check_account)
        assert "implied - Decimal(account.opening_balance)" in source

    def test_null_is_not_zero(self):
        """Zero is a claim the account was empty; most were not."""
        from app.models import Account

        assert Account.opening_balance.nullable
