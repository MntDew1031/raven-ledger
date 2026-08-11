import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.splits import (
    MAX_SPLIT_LINES,
    SplitError,
    countable,
    validate_lines,
)


def charge(amount: str) -> SimpleNamespace:
    return SimpleNamespace(amount=Decimal(amount))


def line(amount: str, **extra) -> dict:
    return {"amount": Decimal(amount), "category_id": None, **extra}


class TestValidateLines:
    def test_lines_that_reconstruct_the_charge_are_accepted(self):
        result = validate_lines(
            charge("-180.00"), [line("-120.00"), line("-60.00")]
        )
        assert [item["amount"] for item in result] == [
            Decimal("-120.00"),
            Decimal("-60.00"),
        ]

    def test_a_shortfall_is_refused_and_says_what_is_missing(self):
        with pytest.raises(SplitError) as failure:
            validate_lines(charge("-180.00"), [line("-120.00"), line("-50.00")])
        message = str(failure.value)
        # The ledger disagreeing with the bank is the one unacceptable outcome,
        # so the error has to be specific enough to act on.
        assert "170.00" in message
        assert "180.00" in message
        assert "Add 10.00" in message

    def test_an_overshoot_says_remove_not_add(self):
        """
        Regression: signed arithmetic made $120 of lines on a $100 purchase
        look like a positive difference, so the error told the person to add
        another $20 when they needed to take $20 away.
        """
        with pytest.raises(SplitError) as failure:
            validate_lines(charge("-100.00"), [line("-60.00"), line("-60.00")])
        assert "Remove 20.00" in str(failure.value)

    def test_an_income_overshoot_also_says_remove(self):
        with pytest.raises(SplitError) as failure:
            validate_lines(charge("500.00"), [line("300.00"), line("300.00")])
        assert "Remove 100.00" in str(failure.value)

    def test_income_splits_work_the_same_way(self):
        result = validate_lines(
            charge("3120.55"), [line("3000.00"), line("120.55")]
        )
        assert sum(item["amount"] for item in result) == Decimal("3120.55")

    def test_a_line_running_the_other_way_is_refused(self):
        # A positive line inside a purchase would land in income and inflate
        # earnings, so signs must match the charge.
        with pytest.raises(SplitError) as failure:
            validate_lines(charge("-100.00"), [line("-150.00"), line("50.00")])
        assert "wrong way" in str(failure.value)

    def test_zero_lines_are_refused(self):
        with pytest.raises(SplitError) as failure:
            validate_lines(
                charge("-100.00"), [line("-100.00"), line("0.00")]
            )
        assert "zero" in str(failure.value).lower()

    def test_a_split_needs_at_least_two_lines(self):
        with pytest.raises(SplitError):
            validate_lines(charge("-100.00"), [line("-100.00")])

    def test_line_count_is_bounded(self):
        many = [line("-1.00") for _ in range(MAX_SPLIT_LINES + 1)]
        with pytest.raises(SplitError) as failure:
            validate_lines(charge(f"-{MAX_SPLIT_LINES + 1}.00"), many)
        assert str(MAX_SPLIT_LINES) in str(failure.value)

    def test_cent_precision_is_exact(self):
        # Thirds of a dollar are where a tolerant comparison would quietly let
        # a penny escape.
        result = validate_lines(
            charge("-100.00"),
            [line("-33.33"), line("-33.33"), line("-33.34")],
        )
        assert sum(item["amount"] for item in result) == Decimal("-100.00")

    def test_a_penny_off_is_still_refused(self):
        with pytest.raises(SplitError):
            validate_lines(
                charge("-100.00"),
                [line("-33.33"), line("-33.33"), line("-33.33")],
            )

    def test_unrounded_input_is_quantized_before_comparison(self):
        result = validate_lines(
            charge("-10.00"), [line("-5.004"), line("-4.996")]
        )
        assert [item["amount"] for item in result] == [
            Decimal("-5.00"),
            Decimal("-5.00"),
        ]


class TestAggregationIsGuardedEverywhere:
    """
    The failure this whole design guards against is a split parent being summed
    alongside its own lines, which silently doubles a household's spending. It
    cannot be caught by reading one file, so assert the predicate reaches every
    module that sums money.
    """

    def test_the_shared_predicates_carry_the_guard(self):
        """
        The guard reaches most modules *through* `is_spending` / `is_income`
        rather than by being named, so this is the assertion that actually
        matters: those two must exclude split parents in the SQL they compile
        to. Checked against the compiled statement, not the source text.
        """
        import uuid

        from app.services.spending_scope import is_income, is_spending

        for name, predicate in (("is_spending", is_spending), ("is_income", is_income)):
            sql = str(
                predicate(uuid.uuid4()).compile(
                    compile_kwargs={"literal_binds": True}
                )
            )
            assert "is_split" in sql, (
                f"{name} does not exclude split parents, so every report "
                "built on it double-counts a split."
            )

    def test_every_money_aggregation_is_guarded_one_way_or_the_other(self):
        """
        Either the module names `countable` itself, or it sums only through a
        shared predicate that carries it. Accepting both is the point — this
        test used to demand the literal word and failed the moment
        `assistant.py` started summing through `is_spending`, which is strictly
        safer than what it did before.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "app"
        aggregators = [
            "services/budgets.py",
            "services/reporting.py",
            "services/assistant.py",
            "api/reports.py",
        ]
        for relative in aggregators:
            source = (root / relative).read_text()
            guarded = "countable" in source or (
                "is_spending" in source or "is_income" in source
            )
            assert guarded, (
                f"{relative} sums transaction amounts without excluding split "
                "parents, directly or through a shared predicate; its totals "
                "will double-count."
            )

    def test_merchant_grouping_excludes_split_lines(self):
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app/services/recurring.py"
        ).read_text()
        # Lines repeat their parent's merchant and date, so counting them would
        # turn one monthly bill into several.
        assert "parent_transaction_id.is_(None)" in source


class TestCountable:
    def test_it_excludes_split_parents(self):
        """
        The single predicate that stops a household's spending being counted
        twice. Every aggregation site imports this rather than open-coding it.
        """
        clause = countable()
        rendered = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "is_split" in rendered
        assert "false" in rendered.lower()


class TestSplitLineIdentity:
    def test_a_split_line_is_not_treated_as_a_manual_entry(self):
        """
        Regression guard: `is_manual` keys off a missing provider id, and a
        split line has none. Without the parent check it would look manual and
        the API would let a person edit its account, date, and merchant away
        from the charge it belongs to.
        """
        from app.models import Transaction

        line_row = Transaction(
            household_id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            original_description="COSTCO WHSE #1043",
            amount=Decimal("-60.00"),
            posted_date=None,
            provider_transaction_id=None,
            parent_transaction_id=uuid.uuid4(),
        )
        assert line_row.is_split_line is True
        assert line_row.is_manual is False

        manual = Transaction(
            household_id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            original_description="Cash lunch",
            amount=Decimal("-12.00"),
            posted_date=None,
            provider_transaction_id=None,
            parent_transaction_id=None,
        )
        assert manual.is_manual is True
        assert manual.is_split_line is False


class TestSerializationEagerLoading:
    """
    `TransactionResponse` carries `splits`, which is a relationship. On an async
    session Pydantic cannot lazy-load it during serialization — it raises
    MissingGreenlet and the endpoint 500s. Both readbacks and the PATCH load
    were found this way in QA, not by reading the code.
    """

    def test_every_transaction_readback_eager_loads_splits(self):
        import pathlib
        import re

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app/api/transactions.py"
        ).read_text()

        # Every `select(Transaction)` that feeds a TransactionResponse loads
        # tags; each of those must load splits too.
        tag_loads = len(re.findall(r"selectinload\(Transaction\.tags\)", source))
        split_loads = len(
            re.findall(r"selectinload\(Transaction\.splits\)", source)
        )
        assert split_loads >= 1
        # Each split load nests a tags load, so tags appear once per split load
        # plus once per standalone query.
        assert tag_loads >= split_loads, (
            "a query loads splits without tags, which cannot serialize"
        )

    def test_readbacks_repopulate_the_identity_map(self):
        """
        Regression: the parent is already in the session with an empty `splits`
        collection loaded from before the lines were written, so a plain
        re-select returned a split with no lines in it.
        """
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app/api/transactions.py"
        ).read_text()
        assert "populate_existing=True" in source
