import io

import pytest
from PIL import Image
from pydantic import ValidationError

from app.api.profile import MAX_AVATAR_EDGE, _process_avatar
from app.schemas import ProfileUpdate
from app.security import verify_password
from app.services.plaid_service import verify_webhook


def test_avatar_processing_normalizes_to_bounded_webp():
    source = Image.new("RGB", (1200, 700), color=(49, 90, 67))
    payload = io.BytesIO()
    source.save(payload, format="PNG")

    processed = _process_avatar(payload.getvalue())

    with Image.open(io.BytesIO(processed)) as avatar:
        assert avatar.format == "WEBP"
        assert max(avatar.size) <= MAX_AVATAR_EDGE


def test_avatar_processing_rejects_non_image_payloads():
    with pytest.raises(ValueError):
        _process_avatar(b"<svg onload=alert(1)></svg>")


def test_profile_preferences_reject_unknown_theme():
    with pytest.raises(ValidationError):
        ProfileUpdate(theme="script")


@pytest.mark.parametrize("theme", ["parchment", "aurora"])
def test_profile_preferences_accept_raven_atmosphere_themes(theme: str):
    assert ProfileUpdate(theme=theme).theme == theme


def test_malformed_password_hash_fails_closed():
    assert verify_password("password", "not-a-password-hash") is False


def test_unsigned_plaid_webhook_fails_closed():
    assert verify_webhook(b'{"webhook_type":"TRANSACTIONS"}', None) is False
