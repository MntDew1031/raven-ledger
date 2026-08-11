"""
Rent is funded by the previous month's pay.

Alex: "rent is due at the first of the month so it technically comes out of
the July budget/paycheck but the transaction goes through in August and makes
it look like we don't have to budget for next month's rent, which is not true."

August's Housing line read $1,279.87 of $1,280.50 planned — satisfied — while
the money had left in July and nothing told him to set September's aside.
"""

from datetime import date

from sqlalchemy.dialects import postgresql


def _sql(expression) -> str:
    return str(
        expression.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class TestTheBudgetMonthExpression:
    """
    Asserted on the compiled SQL rather than on the source text. A string match
    would pass on an expression that cannot run, and this project has shipped
    four releases of exactly that.
    """

    def test_it_falls_back_to_the_month_it_posted_in(self):
        from app.services.spending_scope import budget_month_of

        sql = _sql(budget_month_of())
        assert "coalesce" in sql.lower()
        assert "budget_month" in sql
        assert "posted_date" in sql

    def test_every_source_is_truncated_to_a_month(self):
        """
        Comparing a raw date against a month start would drop every row
        assigned mid-month, and nothing would say so.

        Asserted per source rather than by counting `date_trunc`, which was the
        original test and broke the moment a third source was added — a count
        says nothing about *which* one is unwrapped.
        """
        from app.services.spending_scope import budget_month_of

        sql = _sql(budget_month_of()).lower()
        for column in (
            "transactions.budget_month",       # the row's own assignment
            "transactions_1.budget_month",     # the split parent it belongs to
            "transactions.posted_date",        # where it actually landed
        ):
            assert f"date_trunc('month', {column})" in sql, (
                f"{column} is compared without being truncated to a month"
            )

    def test_a_split_line_inherits_the_charge_it_belongs_to(self):
        """
        The parent is excluded from every total by `countable()`, so the lines
        are what the budget counts. Setting the month on the charge did nothing
        at all until the lines looked at it.

        Alex pays his father several things in one Venmo charge, splits it
        five ways, and needs the whole charge in the previous month — he cannot
        do that line by line.
        """
        from app.services.spending_scope import budget_month_of

        sql = _sql(budget_month_of()).lower()
        assert "parent_transaction_id" in sql, (
            "a split line must fall back to its parent's assignment"
        )
        # Order is the rule: own assignment, then the parent's, then posted.
        own = sql.index("transactions.budget_month")
        inherited = sql.index("transactions_1.budget_month")
        posted = sql.index("transactions.posted_date")
        assert own < inherited < posted, (
            "the specific must beat the general at every step"
        )


class TestOnlyTheBudgetOptsIn:
    def test_the_parameter_defaults_to_off(self):
        """
        Every other caller of `/reports/spending` must keep the answer it
        already had. Reports are history; only the budget is a plan.
        """
        import inspect

        from app.api.reports import spending_by_category

        default = inspect.signature(spending_by_category).parameters[
            "use_budget_month"
        ].default
        assert default is False

    def test_posted_date_is_still_what_history_filters_on(self):
        """
        The blast radius was the reason to be careful: every money query in
        this codebase filters on `posted_date`, and this had to touch exactly
        one of them.
        """
        import pathlib

        api = pathlib.Path(__file__).resolve().parents[1] / "app"
        # Matched on the call, not the bare name: `budget_month_offset`
        # contains `budget_month_of` as a substring, and a looser check
        # reports the category column as a second caller of the function.
        users = [
            path
            for path in api.rglob("*.py")
            if "budget_month_of(" in path.read_text()
        ]
        names = sorted(p.name for p in users)
        # Defined in one place, used by the two questions that are genuinely
        # about a *plan*: what a month's categories were budgeted to carry,
        # and which side of a statement's two budget months a card charge
        # falls on. Everything else — net worth, cash flow, the Sankey,
        # reconciliation — is history and must keep filtering on posted_date.
        # If this list grows, check the new caller is asking about a plan.
        assert names == ["cards.py", "reports.py", "spending_scope.py"], names


class TestNormalisingToTheFirst:
    def test_a_month_is_stored_as_its_first_day(self):
        """
        The column names a month. Storing the 14th would make every comparison
        depend on which day somebody happened to pick in the date control.
        """
        import inspect

        from app.api.transactions import update_transaction

        assert "replace(day=1)" in inspect.getsource(update_transaction)

    def test_clearing_it_is_possible(self):
        """
        Explicit null means "back to the month it posted in". Checking
        truthiness instead of `model_fields_set` would make it one-way.
        """
        import inspect

        from app.api.transactions import update_transaction

        source = inspect.getsource(update_transaction)
        assert '"budget_month" in payload.model_fields_set' in source


class TestASandboxCopiesIt:
    def test_the_clone_carries_the_assignment(self):
        """
        A household-scoped column that `create_sandbox` does not copy makes a
        what-if diverge from the ledger it was cloned from. That has happened
        here before with income sources and goals.
        """
        import inspect

        from app.services.sandbox import create_sandbox

        assert "budget_month=transaction.budget_month" in inspect.getsource(
            create_sandbox
        )


class TestACategoryCanAlwaysCountInTheMonthBefore:
    """
    Setting it per transaction is a monthly chore, and Alex asked for it to be
    automatic. `categories.budget_month_offset` of -1 means "this category's
    spending counts against the previous month's plan" — rent, exactly.
    """

    def test_the_offset_shifts_the_month(self):
        from app.models import Category
        from app.services.spending_scope import budget_month_of

        sql = _sql(budget_month_of(category=Category))
        assert "budget_month_offset" in sql
        assert "INTERVAL" in sql.upper()

    def test_a_transaction_assignment_still_wins(self):
        """
        The specific beats the general: one odd month must be correctable
        without switching the category rule off. `coalesce` puts the
        per-transaction value first.
        """
        from app.models import Category
        from app.services.spending_scope import budget_month_of

        sql = _sql(budget_month_of(category=Category))
        assert sql.index("budget_month") < sql.index("budget_month_offset")

    def test_a_row_with_no_category_survives_an_outer_join(self):
        """
        `cards.py` reaches this through an **outer** join, because an
        uncategorized charge is still a charge and dropping it would make the
        card figures quietly optimistic. On the unmatched side every category
        column is NULL, and `concat(NULL, ' months')` is the string ' months',
        which fails to cast to an interval — the whole statement query would
        raise at request time, not at import.

        A row with no category simply has no standing rule, which is an offset
        of zero.
        """
        from app.models import Category
        from app.services.spending_scope import budget_month_of

        sql = _sql(budget_month_of(category=Category)).lower()
        # The guard must wrap the offset itself, not merely appear somewhere in
        # an expression that has several coalesces for other reasons.
        assert "coalesce(categories.budget_month_offset, 0)" in sql, sql

    def test_without_a_category_the_expression_is_unchanged(self):
        """
        Callers that do not join categories must keep the old behaviour rather
        than fail — the offset is an optional refinement, not a requirement.
        """
        from app.services.spending_scope import budget_month_of

        assert "budget_month_offset" not in _sql(budget_month_of())

    def test_the_offset_is_bounded(self):
        """
        A month either way is the case this exists for. An unbounded integer
        invites a typo that silently moves a year of spending.
        """
        import pathlib

        migration = (
            pathlib.Path(__file__).resolve().parents[1]
            / "migrations/versions/20260804_03_category_budget_offset.py"
        ).read_text()
        assert "BETWEEN -1 AND 1" in migration

    def test_it_is_applied_on_read_not_written_into_rows(self):
        """
        Materialising it at save time would leave every past row holding the
        old answer the moment he changed his mind, with nothing to say so.
        That staleness trap has produced silently wrong figures here before.
        """
        import inspect

        from app.api.transactions import update_transaction

        # The transaction write path knows nothing about category offsets.
        assert "budget_month_offset" not in inspect.getsource(update_transaction)


class TestASplitCanBeMovedToo:
    """
    Alex pays his father several things in one Venmo charge — insurance, loans,
    phone, medical, Spotify — splits it five ways, and needs the whole charge to
    count against the previous month.

    Three separate refusals stood in the way, and the first two both reported
    something he had not touched.
    """

    def test_a_split_parent_may_be_saved_when_the_category_is_unchanged(self):
        """
        The dialog sends `category_id` on every submit, so testing for its
        *presence* made a split parent unsavable in every respect: changing the
        budget month came back as "this transaction is split across
        categories", which is a true sentence about a field he did not touch.
        """
        import inspect

        from app.api.transactions import update_transaction

        source = inspect.getsource(update_transaction)
        assert "payload.category_id != transaction.category_id" in source, (
            "a split parent must refuse a category *change*, not every save"
        )

    def test_a_split_parent_does_not_need_a_category_to_be_reviewed(self):
        """
        Its category is None on purpose — the lines carry them, and
        `countable()` keeps the parent out of every total. Demanding one is the
        1.53.4 transfer bug in a new costume: a row that can never satisfy the
        rule can never be cleared.
        """
        from app.api.transactions import _review_needs_a_category

        assert _review_needs_a_category(False, False, False), "ordinary spending"
        assert not _review_needs_a_category(False, False, True), "a split parent"
        assert not _review_needs_a_category(True, False, False), "a transfer"
        assert not _review_needs_a_category(False, True, False), "excluded"

    def test_both_review_paths_pass_the_split_flag(self):
        """
        `PATCH` and `POST /review` share the predicate, and when they disagreed
        before, the tick refused while "approve all" silently skipped — which
        is indistinguishable from a save that did not persist.
        """
        import inspect

        from app.api.transactions import bulk_review, update_transaction

        for fn in (bulk_review, update_transaction):
            source = inspect.getsource(fn)
            assert "is_split" in source.split("_review_needs_a_category", 1)[1][:120], (
                f"{fn.__name__} does not tell the predicate about splits"
            )
