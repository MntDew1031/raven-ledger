"""
A budget month and a statement month are not the same month.

Alex: "our credit card due dates are not hard set to the first of the month so
a card that has a statement date of the 8th, that month of spending from July
will have to be paid August."
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.services.cards import statement_close


class TestTheClosingDate:
    def test_an_ordinary_month(self):
        assert statement_close(8, date(2026, 8, 1)) == date(2026, 8, 8)

    def test_a_card_that_closes_on_the_thirty_first_still_closes_in_february(self):
        """
        Unclamped this raises `ValueError` in exactly two months a year, which
        is the worst frequency there is: rare enough to ship, certain enough to
        hit. February 2026 has 28 days.
        """
        assert statement_close(31, date(2026, 2, 1)) == date(2026, 2, 28)

    def test_and_in_a_leap_february(self):
        assert statement_close(31, date(2028, 2, 1)) == date(2028, 2, 29)

    def test_a_thirty_first_in_a_thirty_day_month(self):
        assert statement_close(31, date(2026, 9, 1)) == date(2026, 9, 30)

    @pytest.mark.parametrize("month", range(1, 13))
    def test_every_month_of_the_year_resolves(self, month):
        for day in (1, 15, 28, 29, 30, 31):
            closed = statement_close(day, date(2026, month, 1))
            assert closed.month == month
            assert closed.day <= day


class TestTheCycleTheStatementCovers:
    """
    The window is the previous close (exclusive) to this close (inclusive), so
    consecutive statements tile the calendar without a gap or an overlap. A
    charge cannot be billed twice and cannot fall between two statements.
    """

    def test_consecutive_cycles_meet_exactly(self):
        from app.services.cards import _previous_month

        for month in range(2, 13):
            this_month = date(2026, month, 1)
            closes = statement_close(8, this_month)
            opens = statement_close(8, _previous_month(this_month))
            previous_close = statement_close(8, _previous_month(this_month))
            assert opens == previous_close, "one cycle starts where the last ended"
            assert opens < closes

    def test_july_spending_is_billed_in_august(self):
        from app.services.cards import _previous_month

        august = date(2026, 8, 1)
        opens = statement_close(8, _previous_month(august))
        closes = statement_close(8, august)
        a_july_charge = date(2026, 7, 20)
        assert opens < a_july_charge <= closes, (
            "a charge made on 20 July belongs to the statement that closes "
            "on 8 August, which is the whole point"
        )


class TestWhatACardOwes:
    """
    Alex kept a "Credit Cards" tab whose seven balances summed to one figure —
    $671.52 — that he added to rent to know what he owed. That total is the
    number the panel exists to produce, so the arithmetic under it is worth
    pinning.
    """

    def test_a_balance_is_stored_negative_and_owed_positive(self):
        from decimal import Decimal

        from app.services.cards import amount_owed

        assert amount_owed(Decimal("-387.75")) == Decimal("387.75")

    def test_a_card_in_credit_owes_nothing_rather_than_less_than_nothing(self):
        """
        A refund larger than the balance would otherwise return a negative
        amount and reduce what the *other* six cards owe — one refunded card
        understating the household's total.
        """
        from decimal import Decimal

        from app.services.cards import amount_owed

        assert amount_owed(Decimal("40.00")) == Decimal("0.00")

    def test_an_empty_card_owes_nothing(self):
        from decimal import Decimal

        from app.services.cards import amount_owed

        assert amount_owed(None) == Decimal("0.00")
        assert amount_owed(Decimal("0")) == Decimal("0.00")

    def test_his_seven_balances_still_total_what_the_spreadsheet_said(self):
        from decimal import Decimal

        from app.services.cards import amount_owed

        balances = ["-4.32", "-11.32", "-24.90", "0", "0", "-387.75", "-243.23"]
        total = sum(amount_owed(Decimal(b)) for b in balances)
        assert total == Decimal("671.52")


class TestTheOrderTheCardsAppearIn:
    def test_a_card_with_no_statement_day_sorts_last_without_exploding(self):
        """
        `closes_on` is None for those, and comparing None with a date raises
        TypeError — a crash on exactly the households that have not finished
        configuring, which is all of them at first.
        """
        from datetime import date

        from app.services.cards import card_order

        rows = [
            {"closes_on": None, "paid": False},
            {"closes_on": date(2026, 8, 7), "paid": False},
            {"closes_on": date(2026, 8, 2), "paid": True},
        ]
        ordered = sorted(rows, key=card_order)
        assert ordered[0]["closes_on"] == date(2026, 8, 7)
        assert ordered[1]["closes_on"] == date(2026, 8, 2)
        assert ordered[2]["closes_on"] is None

    def test_unpaid_comes_before_paid(self):
        from datetime import date

        from app.services.cards import card_order

        rows = [
            {"closes_on": date(2026, 8, 1), "paid": True},
            {"closes_on": date(2026, 8, 25), "paid": False},
        ]
        assert sorted(rows, key=card_order)[0]["paid"] is False


class TestWhatIsStillToPay:
    """
    Alex, on the Remaining box: "I know we roughly have $2,670 left over each
    month and we had to spend roughly $1,014.95 of unplanned money, that number
    should be closer to $1,655." It read $102.35, and later $1,351.90.

    Two separate mistakes were behind it. 1.70.0 fixed the first — subtracting
    a whole statement when half of it was already inside SPENT. This is the
    second: a statement he had *already paid*, mid-cycle, still counted in
    full.
    """

    def test_a_settled_statement_owes_nothing(self):
        from app.services.cards import statement_split

        out, carried = statement_split(D("300"), D("100"), D("300"), True)
        assert (out, carried) == (D("0.00"), D("0.00"))

    def test_only_the_older_charges_are_carried(self):
        """The 1.70.0 case, unchanged: $100 in July, $200 in August."""
        from app.services.cards import statement_split

        out, carried = statement_split(D("300"), D("100"), D("300"), False)
        assert out == D("300")
        assert carried == D("100")

    def test_a_mid_cycle_payment_is_not_still_owed(self):
        """
        **The Bilt case, with his real figures.** A cycle holding $2,802.65 of
        charges, $1,553.10 of them from July, on a card whose actual balance is
        $1,445.95 — because he paid the $1,279.87 rent the day it posted.

        Payments settle oldest first, so what survives is August's $1,249.55
        plus $196.40 of July. Unclamped this reported $2,802.65 still to pay
        and $1,553.10 of carry, and took $1,279.87 he had already paid out of
        what was left of his month.
        """
        from app.services.cards import statement_split

        out, carried = statement_split(
            D("2802.65"), D("1553.10"), D("1445.95"), False
        )
        assert out == D("1445.95")
        assert carried == D("196.40")

    def test_paying_more_than_the_older_charges_clears_the_carry(self):
        from app.services.cards import statement_split

        # $500 charged, $100 of it last month, but only $250 still owed — the
        # payment covered last month's $100 and more.
        out, carried = statement_split(D("500"), D("100"), D("250"), False)
        assert out == D("250")
        assert carried == D("0.00")

    def test_a_card_in_credit_owes_nothing(self):
        from app.services.cards import statement_split

        out, carried = statement_split(D("300"), D("100"), D("0.00"), False)
        assert (out, carried) == (D("0.00"), D("0.00"))

    def test_a_balance_larger_than_the_cycle_does_not_inflate_it(self):
        """
        A card carrying an old balance owes more than this cycle billed. The
        statement is still only what the statement is — taking the balance
        would bill a month for spending it never saw.
        """
        from app.services.cards import statement_split

        out, carried = statement_split(D("300"), D("100"), D("9000"), False)
        assert out == D("300")
        assert carried == D("100")
