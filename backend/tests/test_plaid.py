import uuid

from app.services import plaid_service


class FakeResponse:
    def to_dict(self):
        return {"link_token": "link-test-token"}


class FakePlaidClient:
    def __init__(self):
        self.request = None

    def link_token_create(self, request):
        self.request = request.to_dict()
        return FakeResponse()


def test_link_token_uses_transactions_with_optional_financial_products(
    monkeypatch,
):
    client = FakePlaidClient()
    monkeypatch.setattr(plaid_service, "plaid_client", lambda: client)

    token = plaid_service.create_link_token(uuid.uuid4())

    assert token == "link-test-token"
    assert client.request["products"] == ["transactions"]
    assert client.request["optional_products"] == ["investments", "liabilities"]


def test_sandbox_client_supports_current_plaid_sdk(monkeypatch):
    monkeypatch.setattr(plaid_service.settings, "plaid_client_id", "client-id")
    monkeypatch.setattr(plaid_service.settings, "plaid_secret", "sandbox-secret")
    monkeypatch.setattr(plaid_service.settings, "plaid_environment", "sandbox")

    client = plaid_service.plaid_client()

    assert client is not None


def test_link_options_omit_absent_values():
    from app.services import plaid_service

    settings = plaid_service.settings
    webhook, redirect = settings.plaid_webhook_url, settings.plaid_redirect_uri
    try:
        settings.plaid_webhook_url = None
        settings.plaid_redirect_uri = None
        # Plaid rejects empty strings, so absent config must stay absent.
        assert plaid_service._link_options() == {}

        settings.plaid_webhook_url = "https://example.com/api/v1/plaid/webhook"
        settings.plaid_redirect_uri = "https://example.com/plaid/oauth"
        assert plaid_service._link_options() == {
            "webhook": "https://example.com/api/v1/plaid/webhook",
            "redirect_uri": "https://example.com/plaid/oauth",
        }

        settings.plaid_redirect_uri = None
        assert "redirect_uri" not in plaid_service._link_options()
    finally:
        settings.plaid_webhook_url = webhook
        settings.plaid_redirect_uri = redirect


def test_stale_sync_detection():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.api.plaid import _sync_is_stale

    now = datetime.now(timezone.utc)

    # A healthy connection is never stale, however old.
    assert not _sync_is_stale(
        SimpleNamespace(status="healthy", updated_at=now - timedelta(days=3))
    )
    # A sync queued moments ago is simply in progress.
    assert not _sync_is_stale(
        SimpleNamespace(status="syncing", updated_at=now - timedelta(seconds=30))
    )
    # One queued long ago is never going to land on its own.
    assert _sync_is_stale(
        SimpleNamespace(status="syncing", updated_at=now - timedelta(hours=2))
    )
    # Missing timestamps fail toward telling the user something is wrong.
    assert _sync_is_stale(SimpleNamespace(status="syncing", updated_at=None))


def test_encryption_key_validation_rejects_a_malformed_key():
    import pytest

    from app import security

    original = security.settings.encryption_key
    try:
        # 41 characters: exactly the shape that silently broke a live sync.
        security.settings.encryption_key = "a" * 41
        with pytest.raises(RuntimeError) as failure:
            security.verify_encryption_key()
        assert "44 characters" in str(failure.value)

        from cryptography.fernet import Fernet

        security.settings.encryption_key = Fernet.generate_key().decode()
        security.verify_encryption_key()

        # Blank is valid: the key is derived from SECRET_KEY instead.
        security.settings.encryption_key = None
        security.verify_encryption_key()
    finally:
        security.settings.encryption_key = original


def test_first_sync_omits_the_cursor():
    """A new institution has no cursor, and the SDK rejects None outright."""
    from app.services.plaid_service import _transactions_sync_request

    first = _transactions_sync_request("access-token", None)
    assert "cursor" not in first.to_dict()
    assert first.to_dict()["access_token"] == "access-token"

    later = _transactions_sync_request("access-token", "cursor-from-last-page")
    assert later.to_dict()["cursor"] == "cursor-from-last-page"


def test_first_sync_treats_an_empty_cursor_as_absent():
    from app.services.plaid_service import _transactions_sync_request

    assert "cursor" not in _transactions_sync_request("access-token", "").to_dict()
