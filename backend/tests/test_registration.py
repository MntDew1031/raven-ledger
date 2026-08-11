import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.auth import _registration_status
from app.config import get_settings
from app.models import HouseholdInvite, HouseholdRole
from app.schemas import RegisterRequest
from app.services.invites import validate_invite

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def build_invite(**overrides) -> HouseholdInvite:
    defaults = {
        "invited_email": "partner@example.com",
        "token_hash": "0" * 64,
        "role": HouseholdRole.member,
        "expires_at": NOW + timedelta(days=7),
        "accepted_at": None,
    }
    defaults.update(overrides)
    return HouseholdInvite(**defaults)


def test_open_invite_is_accepted_for_the_invited_email():
    invite = build_invite()

    assert (
        validate_invite(invite, email="partner@example.com", now=NOW) is invite
    )


def test_invite_email_comparison_ignores_case():
    invite = build_invite()

    assert validate_invite(invite, email="Partner@Example.com", now=NOW)


def test_missing_invite_is_rejected():
    with pytest.raises(HTTPException) as failure:
        validate_invite(None, now=NOW)

    assert failure.value.status_code == 404


def test_expired_invite_is_rejected():
    invite = build_invite(expires_at=NOW - timedelta(seconds=1))

    with pytest.raises(HTTPException) as failure:
        validate_invite(invite, email="partner@example.com", now=NOW)

    assert failure.value.status_code == 404


def test_already_accepted_invite_cannot_be_reused():
    invite = build_invite(accepted_at=NOW - timedelta(days=1))

    with pytest.raises(HTTPException) as failure:
        validate_invite(invite, email="partner@example.com", now=NOW)

    assert failure.value.status_code == 404


def test_invite_cannot_be_redeemed_by_another_email():
    invite = build_invite()

    with pytest.raises(HTTPException) as failure:
        validate_invite(invite, email="stranger@example.com", now=NOW)

    assert failure.value.status_code == 403


def test_registration_requires_a_household_name_or_an_invite():
    payload = RegisterRequest(
        email="owner@example.com",
        display_name="Owner",
        password="correct horse battery",
    )

    assert payload.household_name is None
    assert payload.invite_token is None


def test_registration_rejects_short_passwords():
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="owner@example.com",
            display_name="Owner",
            password="short",
            household_name="Home",
        )


def test_registration_rejects_truncated_invite_tokens():
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="partner@example.com",
            display_name="Partner",
            password="correct horse battery",
            invite_token="tiny",
        )


class FakeSession:
    """Minimal stand-in that answers the single 'does any user exist' query."""

    def __init__(self, has_user: bool):
        self.has_user = has_user

    async def scalar(self, _query):
        return self.has_user


def status_for(has_user: bool, allow_public: bool):
    settings = get_settings()
    original = settings.allow_public_registration
    settings.allow_public_registration = allow_public
    try:
        return asyncio.run(_registration_status(FakeSession(has_user)))
    finally:
        settings.allow_public_registration = original


def test_registration_is_open_to_bootstrap_an_empty_server():
    status = status_for(has_user=False, allow_public=False)

    assert status.open is True
    assert status.reason == "bootstrap"


def test_registration_closes_once_a_user_exists():
    status = status_for(has_user=True, allow_public=False)

    assert status.open is False
    assert status.reason == "closed"


def test_registration_can_be_deliberately_reopened():
    status = status_for(has_user=True, allow_public=True)

    assert status.open is True
    assert status.reason == "enabled"


class FakeAuth:
    def __init__(self, role: str):
        self.role = role


def test_only_the_owner_can_manage_bank_connections():
    from app.api.plaid import _require_owner

    _require_owner(FakeAuth("owner"))

    for role in ("member", "viewer"):
        with pytest.raises(HTTPException) as failure:
            _require_owner(FakeAuth(role))
        assert failure.value.status_code == 403
