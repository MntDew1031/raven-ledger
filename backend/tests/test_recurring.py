from datetime import date, timedelta
from decimal import Decimal

from app.services.recurring import classify_cadence, evaluate_group


def monthly_dates(count, start=date(2026, 1, 5)):
    result = []
    current = start
    for _ in range(count):
        result.append(current)
        current = current + timedelta(days=30)
    return result


def test_cadence_classification_bands():
    assert classify_cadence(7) == "weekly"
    assert classify_cadence(14) == "biweekly"
    assert classify_cadence(30) == "monthly"
    assert classify_cadence(91) == "quarterly"
    assert classify_cadence(365) == "yearly"
    assert classify_cadence(3) is None
    assert classify_cadence(45) is None


def test_monthly_subscription_is_detected():
    dates = monthly_dates(6)
    amounts = [Decimal("-15.99")] * 6
    outcome = evaluate_group(dates, amounts)
    assert outcome is not None
    cadence, next_due, average = outcome
    assert cadence == "monthly"
    assert next_due == dates[-1] + timedelta(days=30)
    assert average == Decimal("15.99")


def test_varying_utility_bill_is_detected():
    dates = monthly_dates(5)
    amounts = [
        Decimal("-118.40"),
        Decimal("-131.02"),
        Decimal("-125.77"),
        Decimal("-140.00"),
        Decimal("-122.13"),
    ]
    assert evaluate_group(dates, amounts) is not None


def test_frequent_but_irregular_merchant_is_not_recurring():
    dates = [
        date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4),
        date(2026, 2, 20), date(2026, 2, 21),
        date(2026, 4, 2),
    ]
    amounts = [Decimal("-6.50")] * 6
    assert evaluate_group(dates, amounts) is None


def test_wildly_varying_amounts_are_not_recurring():
    dates = monthly_dates(5)
    amounts = [
        Decimal("-20"), Decimal("-400"), Decimal("-35"),
        Decimal("-900"), Decimal("-60"),
    ]
    assert evaluate_group(dates, amounts) is None


def test_two_occurrences_are_not_enough():
    assert (
        evaluate_group(
            [date(2026, 1, 1), date(2026, 2, 1)], [Decimal("-9.99")] * 2
        )
        is None
    )


def test_biweekly_paycheck_is_detected_as_inflow_pattern():
    dates = [date(2026, 1, 2) + timedelta(days=14 * n) for n in range(6)]
    amounts = [Decimal("2450.00")] * 6
    outcome = evaluate_group(dates, amounts)
    assert outcome is not None
    assert outcome[0] == "biweekly"
