import re
from datetime import datetime, timezone
from pathlib import Path

from app.models import User
from app.schemas import OperatorConfirmRequest
from app.security import (
    encrypt_secret,
    generate_recovery_codes,
    recovery_code_hash,
    totp_code,
    verify_totp,
    verify_user_mfa,
)
from app.services.security_audit import _safe_details, identifier_fingerprint

RFC_6238_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_totp_matches_rfc_6238_sha1_vector():
    # RFC 6238 publishes the eight-digit value 94287082 at T=59. Raven uses
    # the standard six-digit truncation expected by authenticator apps.
    assert totp_code(RFC_6238_SECRET, at=59) == "287082"
    assert verify_totp(RFC_6238_SECRET, "287082", at=59)


def test_totp_accepts_only_a_small_time_window_and_well_formed_codes():
    code = totp_code(RFC_6238_SECRET, at=90)

    assert verify_totp(RFC_6238_SECRET, code, at=60)
    assert verify_totp(RFC_6238_SECRET, code, at=90)
    assert verify_totp(RFC_6238_SECRET, code, at=120)
    assert not verify_totp(RFC_6238_SECRET, code, at=150)
    assert verify_totp(RFC_6238_SECRET, "28 7082", at=59)
    assert not verify_totp(RFC_6238_SECRET, "287-082", at=59)
    assert not verify_totp(RFC_6238_SECRET, "not-a-code", at=59)


def test_recovery_codes_are_unique_and_stored_as_irreversible_hashes():
    codes = generate_recovery_codes()

    assert len(codes) == 8
    assert len(set(codes)) == 8
    assert all(re.fullmatch(r"[0-9A-F]{4}(?:-[0-9A-F]{4}){3}", code) for code in codes)
    assert recovery_code_hash(codes[0]) == recovery_code_hash(
        codes[0].lower().replace("-", " ")
    )
    assert codes[0].replace("-", "") not in recovery_code_hash(codes[0]).upper()


def test_user_mfa_accepts_totp_and_consumes_each_recovery_code_once():
    recovery_code = "1111-2222-3333-4444"
    user = User(
        email="mfa@example.com",
        password_hash="unused",
        display_name="MFA User",
        mfa_secret_encrypted=encrypt_secret(RFC_6238_SECRET),
        mfa_enabled_at=datetime.now(timezone.utc),
        mfa_recovery_codes=[recovery_code_hash(recovery_code)],
    )

    assert verify_user_mfa(user, totp_code(RFC_6238_SECRET)) == (True, False)
    assert verify_user_mfa(user, recovery_code.lower()) == (True, True)
    assert user.mfa_recovery_codes == []
    assert verify_user_mfa(user, recovery_code) == (False, False)


def test_disabled_mfa_does_not_block_login():
    user = User(
        email="disabled@example.com",
        password_hash="unused",
        display_name="MFA Disabled",
    )

    assert verify_user_mfa(user, "") == (True, False)


def test_failed_login_identifier_is_fingerprinted_not_retained():
    email = "Sensitive.Person@Example.com"
    fingerprint = identifier_fingerprint(email)

    assert fingerprint == identifier_fingerprint(email.lower())
    assert len(fingerprint) == 16
    assert email.lower() not in fingerprint


def test_security_event_details_are_bounded_and_stringified():
    details = _safe_details(
        {
            "x" * 100: "y" * 500,
            "safe_count": 3,
            **{f"extra_{index}": index for index in range(30)},
        }
    )

    assert len(details) == 20
    assert max(map(len, details)) <= 80
    assert max(len(str(value)) for value in details.values()) <= 240


def test_operator_step_up_schema_accepts_an_optional_mfa_code():
    assert OperatorConfirmRequest(password="password").mfa_code is None
    assert (
        OperatorConfirmRequest(password="password", mfa_code="123456").mfa_code
        == "123456"
    )


def test_sensitive_household_and_plaid_actions_are_audited():
    api = Path(__file__).resolve().parents[1] / "app" / "api"
    household_source = (api / "households.py").read_text()
    plaid_source = (api / "plaid.py").read_text()

    for event_type in (
        "household.export",
        "household.invite_created",
        "household.invite_accepted",
        "api_key.created",
        "api_key.revoked",
    ):
        assert event_type in household_source
    for event_type in (
        "plaid.connected",
        "plaid.disconnected",
        "plaid.repair_completed",
        "plaid.sync_requested",
    ):
        assert event_type in plaid_source


def test_financial_mutations_are_visible_in_the_activity_log():
    api = Path(__file__).resolve().parents[1] / "app" / "api"
    sources = {
        name: (api / name).read_text()
        for name in (
            "accounts.py",
            "budgets.py",
            "categories.py",
            "rules.py",
            "transactions.py",
        )
    }

    expected = {
        "accounts.py": (
            "finance.account_created",
            "finance.account_updated",
            "finance.account_hidden",
        ),
        "budgets.py": ("finance.budget_saved",),
        "categories.py": (
            "finance.category_created",
            "finance.category_updated",
            "finance.category_archived",
        ),
        "rules.py": (
            "finance.rule_created",
            "finance.rule_updated",
            "finance.rule_deleted",
        ),
        "transactions.py": (
            "finance.transaction_created",
            "finance.transaction_updated",
            "finance.transaction_deleted",
            "finance.transactions_imported",
        ),
    }
    for filename, event_types in expected.items():
        for event_type in event_types:
            assert event_type in sources[filename]


def test_new_invitation_links_keep_the_token_out_of_the_request_path():
    root = Path(__file__).resolve().parents[2]
    auth_source = (root / "backend" / "app" / "api" / "auth.py").read_text()
    household_source = (
        root / "backend" / "app" / "api" / "households.py"
    ).read_text()
    onboarding_source = (root / "lib" / "onboarding.ts").read_text()

    assert '@router.post("/invites/preview"' in auth_source
    assert '@router.post("/invites/accept"' in household_source
    assert "/join#${encodeURIComponent(token)}" in onboarding_source
