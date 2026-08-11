from decimal import Decimal

from app.api.accounts import _normalized_balance, _normalized_kind
from app.models import AccountKind, AccountType


def test_asset_balance_is_positive():
    assert _normalized_balance(Decimal("-120.50"), AccountKind.asset) == Decimal(
        "120.50"
    )


def test_liability_balance_is_negative():
    assert _normalized_balance(Decimal("120.50"), AccountKind.liability) == Decimal(
        "-120.50"
    )


def test_zero_balance_is_stable():
    assert _normalized_balance(Decimal("0"), AccountKind.liability) == Decimal("0")


def test_known_account_types_determine_financial_kind():
    assert (
        _normalized_kind(AccountType.credit, AccountKind.asset)
        == AccountKind.liability
    )
    assert (
        _normalized_kind(AccountType.savings, AccountKind.liability)
        == AccountKind.asset
    )
    assert (
        _normalized_kind(AccountType.other, AccountKind.liability)
        == AccountKind.liability
    )
