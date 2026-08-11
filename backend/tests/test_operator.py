"""
The audit's Priority 0: a backup is a full-instance dump, but the endpoints
authorized any household `owner`. In a two-household test an owner of the
second household listed, saw, and downloaded the first household's data.

Authority now comes from the deployment environment, so nothing inside the
application — no role change, no invitation, no compromised owner — can grant
it.
"""

from types import SimpleNamespace

import pytest

from app.security import is_operator, operator_emails
from app.services import backup


def user(email: str) -> SimpleNamespace:
    return SimpleNamespace(email=email)


@pytest.fixture
def configured(monkeypatch):
    def apply(value: str):
        monkeypatch.setattr(
            "app.security.settings.operator_emails", value, raising=False
        )
    return apply


class TestOperatorAuthority:
    def test_nobody_is_an_operator_by_default(self, configured):
        # Fail closed: an instance that never names an operator keeps the
        # instance-wide endpoints shut.
        configured("")
        assert operator_emails() == frozenset()
        assert is_operator(user("owner@example.com")) is False

    def test_a_named_operator_is_recognised(self, configured):
        configured("owner@example.com")
        assert is_operator(user("owner@example.com")) is True

    def test_matching_ignores_case_and_padding(self, configured):
        configured("  Owner@Example.com , member@example.com ")
        assert is_operator(user("OWNER@example.com")) is True
        assert is_operator(user("member@example.com")) is True

    def test_a_household_owner_who_is_not_named_is_refused(self, configured):
        """
        The exact finding: household role must not confer instance authority.
        """
        configured("owner@example.com")
        assert is_operator(user("attacker@example.com")) is False

    def test_an_empty_email_never_matches(self, configured):
        configured("owner@example.com")
        assert is_operator(user("")) is False
        assert is_operator(user(None)) is False


class TestGatingIsWiredUp:
    def test_every_backup_endpoint_requires_the_operator(self):
        import pathlib
        import re

        source = (
            pathlib.Path(__file__).resolve().parents[1] / "app/api/system.py"
        ).read_text()
        # One guard per backup route, plus the confirm endpoint itself.
        routes = re.findall(r'@router\.(?:get|post|delete)\("/backups[^"]*"', source)
        assert len(routes) >= 4
        assert source.count("_require_operator(auth)") >= len(routes)
        assert "HouseholdRole" not in source, (
            "backup access must not depend on a household role"
        )

    def test_exfiltration_and_deletion_need_a_fresh_password(self):
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1] / "app/api/system.py"
        ).read_text()
        # A stolen session cookie must not be a standing licence to export
        # every household or destroy the archives.
        assert source.count("await _require_confirmation(auth)") >= 2


class TestBackupNamesAreNotPaths:
    """`resolve` is the only thing between a name and the filesystem."""

    @pytest.mark.parametrize(
        "name",
        [
            "../../etc/passwd",
            "/etc/passwd",
            "raven-20260801T031000Z.dump/../../secret",
            "not-a-backup.txt",
            "raven-bad.dump",
            "",
        ],
    )
    def test_traversal_and_junk_are_refused(self, name):
        with pytest.raises(backup.BackupError):
            backup.resolve(name)


class TestTheApplicationActuallyStarts:
    def test_importing_the_app_registers_the_operator_routes(self):
        """
        Regression: a missing schema class made every route module fail to
        import, and the whole suite still passed because nothing imported
        `app.main`. The container crash-looped instead. Importing the app is
        the cheapest possible guard against that class of break.
        """
        from app.api import system
        from app.main import app

        assert app.title
        paths = {route.path for route in system.router.routes}
        assert "/system/backups" in paths
        assert "/system/operator/confirm" in paths
