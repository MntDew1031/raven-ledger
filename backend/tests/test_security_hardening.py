import asyncio

import pytest
from app.config import Settings
from app.main import request_origin_error, verify_production_web_config
from app.middleware import RequestSizeLimitMiddleware
from cryptography.fernet import Fernet
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import security


def secure_production_settings(**overrides) -> dict:
    values = {
        "environment": "production",
        "secret_key": "s" * 48,
        "encryption_key": Fernet.generate_key().decode(),
        "frontend_url": "https://ledger.example.com",
        "cookie_secure": True,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "override",
    [
        {"secret_key": "development-only-change-me-32-characters"},
        {"encryption_key": None},
    ],
)
def test_production_configuration_fails_closed(override):
    with pytest.raises(ValidationError, match="Unsafe production configuration"):
        Settings(_env_file=None, **secure_production_settings(**override))


def test_secure_production_configuration_is_accepted():
    configured = Settings(_env_file=None, **secure_production_settings())

    assert configured.environment == "production"


@pytest.mark.parametrize("days", [29, 3651])
def test_security_event_retention_is_bounded(days):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, security_event_retention_days=days)


def test_security_event_retention_defaults_to_one_year():
    assert Settings(_env_file=None).security_event_retention_days == 365


@pytest.mark.parametrize(
    "override",
    [
        {"cookie_secure": False},
        {"frontend_url": "http://ledger.example.com"},
    ],
)
def test_production_web_configuration_fails_closed(override):
    configured = Settings(
        _env_file=None,
        **secure_production_settings(**override),
    )

    with pytest.raises(RuntimeError, match="Unsafe production web configuration"):
        verify_production_web_config(configured)


def make_request(
    method: str = "POST",
    path: str = "/api/v1/transactions",
    *,
    peer: str = "127.0.0.1",
    headers: dict[str, str] | None = None,
) -> Request:
    encoded = [
        (name.lower().encode(), value.encode())
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": encoded,
            "client": (peer, 12345),
            "server": ("testserver", 80),
        }
    )


def test_cookie_write_requires_matching_origin():
    cookie = {"cookie": "raven_session=session-token"}

    assert request_origin_error(make_request(headers=cookie)) == (
        "Request origin is required"
    )
    assert (
        request_origin_error(
            make_request(headers={**cookie, "origin": "https://wrong.example"})
        )
        == "Request origin is not allowed"
    )
    assert (
        request_origin_error(
            make_request(headers={**cookie, "origin": "http://localhost:3000"})
        )
        is None
    )


def test_scoped_api_key_and_signed_webhook_do_not_require_browser_origin():
    assert (
        request_origin_error(
            make_request(headers={"authorization": "Bearer rvn_synthetic"})
        )
        is None
    )
    assert request_origin_error(make_request(path="/api/v1/plaid/webhook")) is None


def test_forwarded_client_address_is_used_only_from_a_trusted_proxy():
    original = security.settings.trusted_proxy_cidrs
    security.settings.trusted_proxy_cidrs = "10.0.0.0/8"
    try:
        trusted = make_request(
            peer="10.1.2.3", headers={"cf-connecting-ip": "203.0.113.9"}
        )
        untrusted = make_request(
            peer="198.51.100.4", headers={"cf-connecting-ip": "203.0.113.9"}
        )
        assert security.client_ip(trusted) == "203.0.113.9"
        assert security.client_ip(untrusted) == "198.51.100.4"
    finally:
        security.settings.trusted_proxy_cidrs = original


async def run_limited_request(
    messages: list[dict], max_bytes: int, content_length: int | None = None
) -> list[dict]:
    sent: list[dict] = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        await JSONResponse({"ok": True})(scope, receive, send)

    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    middleware = RequestSizeLimitMiddleware(app, max_bytes=max_bytes)
    await middleware(scope, receive, send)
    return sent


def response_status(messages: list[dict]) -> int:
    return next(
        item["status"] for item in messages if item["type"] == "http.response.start"
    )


def test_content_length_over_limit_is_rejected_before_parsing():
    sent = asyncio.run(
        run_limited_request(
            [{"type": "http.request", "body": b"", "more_body": False}],
            max_bytes=10,
            content_length=11,
        )
    )

    assert response_status(sent) == 413


def test_streamed_body_over_limit_is_rejected():
    sent = asyncio.run(
        run_limited_request(
            [
                {"type": "http.request", "body": b"123456", "more_body": True},
                {"type": "http.request", "body": b"789012", "more_body": False},
            ],
            max_bytes=10,
        )
    )

    assert response_status(sent) == 413


def test_security_event_retention_job_commits_the_purge(monkeypatch):
    from app import worker

    class Result:
        rowcount = 4

    class Session:
        committed = False
        statement = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            self.statement = statement
            return Result()

        async def commit(self):
            self.committed = True

    session = Session()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        worker.settings, "security_event_retention_days", 90, raising=False
    )

    result = asyncio.run(worker.purge_security_events({}))

    assert result == {"deleted": 4, "retention_days": 90}
    assert session.statement is not None
    assert session.committed is True
