"""
API keys are a long-lived credential handed to software, so the boundaries
matter more than the feature. Each test below pins a boundary that was checked
against the running application before being written down.
"""

import pathlib

from app.security import API_KEY_PREFIX, READ_METHODS, new_api_key, token_hash


class TestSecrets:
    def test_the_secret_is_never_stored_in_a_recoverable_form(self):
        secret, hashed, prefix = new_api_key()
        assert hashed == token_hash(secret)
        assert secret not in hashed
        # A copy of the database must not yield a working key.
        assert len(hashed) == 64

    def test_two_keys_never_collide(self):
        secrets = {new_api_key()[0] for _ in range(200)}
        assert len(secrets) == 200

    def test_the_prefix_identifies_without_revealing(self):
        secret, _, prefix = new_api_key()
        assert secret.startswith(f"{API_KEY_PREFIX}_")
        assert prefix and secret.startswith(prefix)
        # Short enough to be useless on its own.
        assert len(prefix) < len(secret) / 2


class TestScopes:
    def test_only_reads_are_free(self):
        assert READ_METHODS == frozenset({"GET", "HEAD", "OPTIONS"})
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            assert method not in READ_METHODS

    def test_the_scope_check_is_central_not_per_route(self):
        """
        One forgotten decorator would be a silent write hole, so the check
        lives in the single place every authenticated request passes through.
        """
        source = (
            pathlib.Path(__file__).resolve().parents[1] / "app/security.py"
        ).read_text()
        assert "request.method not in READ_METHODS and not record.can_write" in source


class TestKeysCannotEscalate:
    def test_backups_refuse_api_keys_outright(self):
        """
        Even when the key's creator is the operator. That authority comes from
        a person at a browser who has just re-entered their password.

        Exercised rather than grepped for. This assertion used to match the
        refusal's exact wording, so rewording the message — which is all that
        happened when the guard learned to name what it was refusing — failed
        a test about authority.
        """
        import types

        import pytest
        from fastapi import HTTPException

        from app.api.system import _require_operator

        operator = types.SimpleNamespace(email="operator@example.com")
        auth = types.SimpleNamespace(user=operator, via_api_key=True)
        with pytest.raises(HTTPException) as refused:
            _require_operator(auth)
        assert refused.value.status_code == 403
        assert "API key" in refused.value.detail

    def test_a_key_cannot_mint_another_key(self):
        """Otherwise revoking one would mean nothing — it could reissue itself."""
        source = (
            pathlib.Path(__file__).resolve().parents[1] / "app/api/households.py"
        ).read_text()
        assert "API keys cannot manage other API keys." in source


class TestOneSettingWithTwoNames:
    """
    The container has always read `OPERATOR_EMAILS`. `docker-compose.yml`,
    `.env.example` and the README all name `RAVEN_OPERATOR_EMAILS` — the
    host-side variable Compose maps *from*.

    Set the documented name anywhere Compose is not doing that mapping — a
    TrueNAS app's environment, a k3s ConfigMap — and the backend never sees it:
    no operator, backups closed, model picker read-only, and nothing anywhere
    saying why. Alex hit exactly this. Both spellings work now.

    These build a `Settings` directly rather than clearing the `get_settings`
    cache. Modules hold the singleton by reference, so replacing it mid-suite
    leaves them pointing at the old object — which broke an unrelated
    registration test that mutates the cached instance.
    """

    def _settings_with(self, monkeypatch, **env):
        from app.config import Settings

        for candidate in ("OPERATOR_EMAILS", "RAVEN_OPERATOR_EMAILS"):
            monkeypatch.delenv(candidate, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return Settings(_env_file=None)

    def test_the_shape_every_real_deployment_has(self, monkeypatch):
        """
        The case that actually bit, and the one an alias cannot cover.

        `docker-compose.yml` writes `OPERATOR_EMAILS: ${RAVEN_OPERATOR_EMAILS:-}`
        and the k3s ConfigMap carries the key too, so the name the container
        reads is *always present and usually empty*. `AliasChoices` takes the
        first name present, so it would pick the empty one every time and fall
        through only on a deployment that sets neither — which is exactly the
        deployment with nothing to fall through to. Emptiness has to be the
        signal, not absence.
        """
        settings = self._settings_with(
            monkeypatch,
            OPERATOR_EMAILS="",
            RAVEN_OPERATOR_EMAILS="owner@example.com",
        )
        assert settings.operator_emails == "owner@example.com"

    def test_a_deliberate_value_is_not_overridden(self, monkeypatch):
        """An install that sets both meant the specific one."""
        settings = self._settings_with(
            monkeypatch,
            OPERATOR_EMAILS="specific@example.com",
            RAVEN_OPERATOR_EMAILS="host-side@example.com",
        )
        assert settings.operator_emails == "specific@example.com"

    def test_both_present_and_both_empty_still_means_nobody(self, monkeypatch):
        """
        The closed default has to survive the fallback. This is the shape of a
        stock deployment that has simply never configured an operator.
        """
        settings = self._settings_with(
            monkeypatch, OPERATOR_EMAILS="", RAVEN_OPERATOR_EMAILS=""
        )
        assert settings.operator_emails == ""

    def test_whitespace_is_not_a_configured_operator(self, monkeypatch):
        settings = self._settings_with(
            monkeypatch,
            OPERATOR_EMAILS="   ",
            RAVEN_OPERATOR_EMAILS="owner@example.com",
        )
        assert settings.operator_emails == "owner@example.com"

    def test_the_name_the_container_reads(self, monkeypatch):
        settings = self._settings_with(
            monkeypatch, OPERATOR_EMAILS="owner@example.com"
        )
        assert settings.operator_emails == "owner@example.com"

    def test_the_name_every_document_gives(self, monkeypatch):
        settings = self._settings_with(
            monkeypatch, RAVEN_OPERATOR_EMAILS="owner@example.com"
        )
        assert settings.operator_emails == "owner@example.com"

    def test_neither_set_still_means_nobody(self, monkeypatch):
        """The closed default is the one thing that must not drift."""
        import app.security

        settings = self._settings_with(monkeypatch)
        assert settings.operator_emails == ""
        monkeypatch.setattr(app.security, "settings", settings)
        assert app.security.operator_emails() == frozenset()

    def test_the_list_is_parsed_and_folded(self, monkeypatch):
        import app.security

        settings = self._settings_with(
            monkeypatch,
            RAVEN_OPERATOR_EMAILS=" Owner@Example.com , member@example.com ",
        )
        monkeypatch.setattr(app.security, "settings", settings)
        assert app.security.operator_emails() == frozenset(
            {"owner@example.com", "member@example.com"}
        )

    def test_a_page_can_tell_no_operator_from_not_you(self):
        """
        "You are not the operator" and "this server has no operator" call for
        opposite actions. Telling a self-hoster who is plainly the operator
        that they are not one sends them looking in the wrong place.
        """
        import inspect

        from app.services import runtime_settings

        assert "operator_configured" in inspect.getsource(
            runtime_settings.snapshot
        )
