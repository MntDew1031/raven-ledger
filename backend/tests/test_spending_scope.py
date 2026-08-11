"""
What counts as spending.

The bug that produced this module: a **negative amount in an income category**
— a payroll reversal, a refunded deposit, a Plaid transaction whose direction
was guessed wrong. `/reports/spending` summed outflows without asking whether
the category earned money, so a $250 reversal was reported as $250 spent. The
budget page then disagreed with itself, because its SPENT headline summed every
row the endpoint returned while the table below could only render non-income
categories.

Verified live before the fix: headline $310.00, rows $60.00, and nothing on
screen to explain the missing $250.
"""

import uuid

from app.services.spending_scope import (
    is_spending,
    switched_off_category_ids,
    uncounted_category_ids,
)


def _sql(clause) -> str:
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


class TestIsSpending:
    def test_requires_an_outflow(self):
        assert "amount < " in _sql(is_spending(uuid.uuid4()))

    def test_honours_the_per_transaction_exclusion(self):
        assert "excluded_from_budget IS false" in _sql(is_spending(uuid.uuid4()))

    def test_ignores_transfers_between_your_own_accounts(self):
        assert "is_transfer IS false" in _sql(is_spending(uuid.uuid4()))

    def test_uncategorized_outflows_still_count(self):
        """
        Money left the account whether or not anybody has filed it. Dropping it
        until it is categorized would make every total quietly optimistic,
        which is the one direction a budget must never be wrong in.
        """
        assert "category_id IS NULL" in _sql(is_spending(uuid.uuid4()))

    def test_excludes_income_and_switched_off_categories(self):
        clause = _sql(is_spending(uuid.uuid4()))
        assert "NOT IN" in clause
        assert "is_income IS true" in clause
        assert "categories.excluded_from_budget IS true" in clause

    def test_split_parents_are_not_double_counted(self):
        # countable() keeps a split parent out; its lines carry the amounts.
        assert "is_split IS false" in _sql(is_spending(uuid.uuid4()))


class TestTheTwoExclusionSetsStaySeparate:
    """
    These were briefly one function, and merging them silently zeroed the
    cash-flow diagram's income total: the diagram must drop switched-off
    categories but obviously keep income ones, since income is what it charts.
    Caught by running it, not by reading it.
    """

    def test_switched_off_does_not_mention_income(self):
        clause = _sql(switched_off_category_ids(uuid.uuid4()))
        assert "excluded_from_budget IS true" in clause
        assert "is_income" not in clause

    def test_uncounted_covers_both_reasons(self):
        clause = _sql(uncounted_category_ids(uuid.uuid4()))
        assert "is_income IS true" in clause
        assert "excluded_from_budget IS true" in clause


class TestReportsShareOnePredicate:
    """
    Three reports had each spelled out their own version of "spending" and
    drifted. A report is a number, and a wrong number looks exactly like a
    right one — so the guard is that they all import the same predicate.
    """

    def test_spending_trends_and_anomalies_all_use_it(self):
        import inspect

        from app.api import reports

        for fn in (
            reports.spending_by_category,
            reports.category_trends,
            reports.spending_anomalies,
        ):
            source = inspect.getsource(fn)
            assert "is_spending(" in source, fn.__name__
            # The hand-written version each one used to carry.
            assert "Transaction.amount < 0" not in source, fn.__name__

    def test_the_diagram_uses_the_narrow_set(self):
        import inspect

        from app.api import reports

        source = inspect.getsource(reports.cash_flow_sankey)
        assert "switched_off_category_ids(" in source
        assert "uncounted_category_ids(" not in source


class TestTheDashboardAgreesWithTheReports:
    """
    The dashboard had its own hand-written sums, classified purely by sign, so
    a payroll reversal in an income category was reported as money spent — on
    the first screen anybody sees. Found by reading its "Spending $310.00"
    beside a ledger holding $60 of actual spending.
    """

    def test_dashboard_spending_uses_the_shared_predicate(self):
        import inspect

        from app.services import reporting

        source = inspect.getsource(reporting.dashboard_summary)
        assert "is_spending(" in source
        # The version that counted any negative amount as spending.
        assert "(Transaction.amount < 0, func.abs(Transaction.amount)), else_=0" \
            not in source

    def test_dashboard_income_only_counts_earning_categories(self):
        """
        Asserted against the compiled SQL rather than the source text. The old
        version grepped `dashboard_summary` for `income_category_ids(`, which
        stopped being true the moment the clause moved into `is_income` —
        without anything about the behaviour changing. A test that reads source
        tracks where code lives, not what it does; the same habit hid a
        `NameError` in the categorizer for four releases.
        """
        import uuid

        from app.services.spending_scope import is_income

        sql = str(is_income(uuid.uuid4()).compile(
            compile_kwargs={"literal_binds": True}
        ))
        assert "category_groups.is_income" in sql, "income categories"
        assert "categories.excluded_from_budget" in sql, "switched-off ones"
        assert "accounts.kind" in sql, "nobody is paid into a credit card"
        assert "amount > 0" in sql

    def test_uncategorized_income_survives_switching_a_category_off(self):
        """
        `NULL NOT IN (...)` is NULL, so a bare `not_in` drops every
        uncategorized inflow — but only once some category is switched off,
        because `NOT IN (empty set)` is true. Nothing changes about the
        transaction; somebody turns off a category they never use and their
        uncategorized income quietly stops counting. Measured in the audit
        fixture: a $100 deposit vanished from a $9,014.42 month.

        Both `IN` tests therefore have to be NULL-tolerant, so this checks the
        shape rather than trusting a fixture that happens to have none.
        """
        import uuid

        from app.services.spending_scope import is_income

        sql = str(is_income(uuid.uuid4()).compile(
            compile_kwargs={"literal_binds": True}
        ))
        assert sql.count("category_id IS NULL") >= 2, (
            "each category-set test needs its own IS NULL escape hatch:\n" + sql
        )
