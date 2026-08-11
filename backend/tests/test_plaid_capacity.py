"""
Who may connect a bank, and how many are left.

Every Plaid route used to be owner-only, justified as "consumes limited
provider capacity and can drop synced history". Those are two different risks:
capacity is a shared budget, best handled by showing what remains; losing
synced history is destructive and irreversible. Jordan joining the household
made the difference matter.
"""

import inspect

from app.api import plaid


def _route_source(path: str) -> str:
    """The body of the handler declared immediately after a given decorator."""
    source = inspect.getsource(plaid)
    start = source.index(f'"{path}"')
    end = source.find("@router.", start)
    return source[start : end if end != -1 else len(source)]


class TestOnlyDisconnectingIsOwnerOnly:
    def test_disconnecting_is_owner_only(self):
        """It removes the connection's synced history with it."""
        assert "_require_owner(auth)" in _route_source(
            "/connections/{connection_id}"
        )

    def test_connecting_a_bank_is_open_to_members(self):
        assert "_require_editor(auth)" in _route_source("/link-token")

    def test_completing_the_link_is_open_to_members(self):
        assert "_require_editor(auth)" in _route_source("/exchange")

    def test_repairing_a_broken_connection_is_open_to_members(self):
        """Waiting for the owner means a broken feed stays broken."""
        assert "_require_editor(auth)" in _route_source(
            "/connections/{connection_id}/link-token"
        )

    def test_syncing_is_open_to_members(self):
        assert "_require_editor(auth)" in _route_source(
            "/connections/{connection_id}/sync"
        )

    def test_viewers_are_still_excluded(self):
        source = inspect.getsource(plaid._require_editor)
        assert "HouseholdRole.viewer" in source


class TestTheAllowanceIsShownAndEnforced:
    def test_the_limit_is_configured_not_guessed(self):
        """
        Plaid's tiers change. A hardcoded number would either block a
        legitimate link or quietly fail to warn.
        """
        from app.config import get_settings

        assert get_settings().plaid_connection_limit is None

    def test_no_limit_configured_means_no_enforcement(self):
        source = inspect.getsource(plaid._guard_capacity)
        assert "if limit is None:" in source and "return" in source

    def test_the_check_happens_before_the_link_starts(self):
        """
        Plaid's own error arrives after somebody has picked their bank and
        typed a password, and says nothing about whose plan it is.
        """
        source = _route_source("/link-token")
        assert source.index("_guard_capacity") < source.index("create_link_token")

    def test_the_refusal_offers_a_way_forward(self):
        source = inspect.getsource(plaid._guard_capacity)
        assert "CSV" in source or "manual account" in source

    def test_status_reports_the_running_count(self):
        source = _route_source("/status")
        for field in ("connections_in_use", "connection_limit", "connections_remaining"):
            assert field in source


class TestABlankLimitDoesNotKillTheContainer:
    """
    `PLAID_CONNECTION_LIMIT` is written by `docker-compose.yml` as
    `${PLAID_CONNECTION_LIMIT:-}` and by the k3s ConfigMap as `""`, so it is
    always present and usually empty. `int | None` cannot parse an empty
    string, so `Settings()` raised at import, alembic exited non-zero, and both
    the backend and the worker refused to start — on an install that followed
    `.env.example` exactly. Found by standing the stack up, not by reading it.
    """

    def test_empty_means_unenforced(self, monkeypatch):
        from app.config import Settings

        monkeypatch.setenv("PLAID_CONNECTION_LIMIT", "")
        assert Settings().plaid_connection_limit is None

    def test_whitespace_is_empty_too(self, monkeypatch):
        from app.config import Settings

        monkeypatch.setenv("PLAID_CONNECTION_LIMIT", "  ")
        assert Settings().plaid_connection_limit is None

    def test_a_real_number_still_arrives(self, monkeypatch):
        from app.config import Settings

        monkeypatch.setenv("PLAID_CONNECTION_LIMIT", "5")
        assert Settings().plaid_connection_limit == 5
