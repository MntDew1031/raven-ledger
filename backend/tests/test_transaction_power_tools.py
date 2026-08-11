import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import (
    BulkTransactionActionRequest,
    TagCreate,
    TransactionCreate,
)


def transaction_payload(**overrides):
    payload = {
        "account_id": uuid.uuid4(),
        "merchant_name": "Desert Market",
        "amount": Decimal("-42.18"),
        "posted_date": date(2026, 8, 1),
    }
    payload.update(overrides)
    return payload


def test_transaction_create_accepts_bounded_tag_assignments():
    tag_ids = [uuid.uuid4(), uuid.uuid4()]

    payload = TransactionCreate(**transaction_payload(tag_ids=tag_ids))

    assert payload.tag_ids == tag_ids


def test_transaction_create_rejects_more_than_fifty_tags():
    with pytest.raises(ValidationError):
        TransactionCreate(
            **transaction_payload(tag_ids=[uuid.uuid4() for _ in range(51)])
        )


def test_bulk_action_requires_at_least_one_transaction():
    with pytest.raises(ValidationError):
        BulkTransactionActionRequest(transaction_ids=[], action="exclude")


def test_bulk_action_is_capped_at_five_hundred_transactions():
    with pytest.raises(ValidationError):
        BulkTransactionActionRequest(
            transaction_ids=[uuid.uuid4() for _ in range(501)],
            action="include",
        )


def test_bulk_action_rejects_unknown_mutations():
    with pytest.raises(ValidationError):
        BulkTransactionActionRequest(
            transaction_ids=[uuid.uuid4()],
            action="delete",
        )


def test_tag_color_must_be_a_six_digit_hex_value():
    with pytest.raises(ValidationError):
        TagCreate(name="Wedding", color="orange")
