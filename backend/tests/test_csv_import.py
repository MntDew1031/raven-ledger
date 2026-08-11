"""
Bringing a CSV in.

Every bank exports a different shape, and the sign is the dangerous part: read
a debit column as a credit and a whole statement inverts — rent becomes income
and the month looks wonderful.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.csv_import import (
    ImportError_,
    _clean_amount,
    _clean_date,
    detect_columns,
    parse,
)


class TestAmounts:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("$1,234.56", Decimal("1234.56")),
            ("-45.00", Decimal("-45.00")),
            # Accountancy's own notation for a negative, and easy to read as a
            # positive if nobody handles it.
            ("(45.00)", Decimal("-45.00")),
            ("45.00 DR", Decimal("-45.00")),
            ("45.00 CR", Decimal("45.00")),
            ("  12.10  ", Decimal("12.10")),
        ],
    )
    def test_shapes_banks_actually_export(self, raw, expected):
        assert _clean_amount(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", None, "n/a", "-", "."])
    def test_unreadable_amounts_are_none_not_zero(self, raw):
        """Zero would import a real row with the wrong value."""
        assert _clean_amount(raw) is None


class TestDates:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-08-02", date(2026, 8, 2)),
            ("08/02/2026", date(2026, 8, 2)),
            ("Aug 2, 2026", date(2026, 8, 2)),
            ("2 Aug 2026", date(2026, 8, 2)),
        ],
    )
    def test_common_formats(self, raw, expected):
        assert _clean_date(raw) == expected

    def test_nonsense_is_rejected_rather_than_guessed(self):
        assert _clean_date("last tuesday") is None


class TestColumnDetection:
    def test_finds_the_usual_names(self):
        found = detect_columns(["Date", "Description", "Amount", "Category"])
        assert found["date"] == "Date"
        assert found["merchant"] == "Description"
        assert found["amount"] == "Amount"

    def test_finds_a_debit_credit_pair(self):
        found = detect_columns(["Posted Date", "Details", "Debit", "Credit"])
        assert found["debit"] == "Debit"
        assert found["credit"] == "Credit"
        assert found["amount"] is None


class TestParsing:
    def test_a_single_signed_amount_column(self):
        csv = b"Date,Description,Amount\n2026-08-01,COFFEE,-4.50\n2026-08-02,PAY,1000.00\n"
        out = parse(csv)
        assert len(out["rows"]) == 2
        assert out["outflows"] == 1 and out["inflows"] == 1

    def test_a_debit_credit_pair_gets_the_sign_right(self):
        """A debit column is written positive and means money out."""
        csv = b"Date,Details,Debit,Credit\n2026-08-01,RENT,1200.00,\n2026-08-02,PAY,,1000.00\n"
        out = parse(csv)
        amounts = sorted(Decimal(r["amount"]) for r in out["rows"])
        assert amounts == [Decimal("-1200.00"), Decimal("1000.00")]

    def test_unreadable_rows_are_reported_not_silently_dropped(self):
        """A silent skip is how half a statement goes missing unnoticed."""
        csv = b"Date,Description,Amount\nnot a date,X,-1.00\n2026-08-01,Y,-2.00\n"
        out = parse(csv)
        assert len(out["rows"]) == 1
        assert len(out["skipped"]) == 1
        assert "date" in out["skipped"][0]["reason"].lower()

    def test_everything_one_direction_is_flagged(self):
        """Almost always a misread sign column rather than a real statement."""
        csv = b"Date,Description,Amount\n2026-08-01,A,10.00\n2026-08-02,B,20.00\n"
        assert parse(csv)["all_one_direction"] is True

    def test_a_mixed_statement_is_not_flagged(self):
        csv = b"Date,Description,Amount\n2026-08-01,A,-10.00\n2026-08-02,B,20.00\n"
        assert parse(csv)["all_one_direction"] is False

    def test_semicolons_and_tabs_are_handled(self):
        csv = b"Date;Description;Amount\n2026-08-01;COFFEE;-4.50\n"
        assert len(parse(csv)["rows"]) == 1

    def test_a_missing_date_column_is_refused_with_a_reason(self):
        with pytest.raises(ImportError_, match="date column"):
            parse(b"Thing,Amount\nX,-1.00\n")

    def test_a_missing_amount_column_is_refused_with_a_reason(self):
        with pytest.raises(ImportError_, match="amount column"):
            parse(b"Date,Description\n2026-08-01,X\n")

    def test_a_byte_order_mark_does_not_break_the_header(self):
        csv = "﻿Date,Description,Amount\n2026-08-01,COFFEE,-4.50\n".encode()
        assert len(parse(csv)["rows"]) == 1


class TestNothingIsWrittenWhileParsing:
    def test_the_parser_never_touches_a_session(self):
        import inspect

        from app.services import csv_import

        source = inspect.getsource(csv_import.parse)
        for write in ("db.add", "commit", "Transaction("):
            assert write not in source
