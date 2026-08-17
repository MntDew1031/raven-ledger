from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_SECRET = "development-only-change-me-32-characters"  # nosec B105


class Settings(BaseSettings):
    app_name: str = "Raven Ledger API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    secret_key: str = Field(default=DEVELOPMENT_SECRET, min_length=24)
    encryption_key: str | None = None
    database_url: str = "postgresql+asyncpg://raven:raven@postgres:5432/raven"
    redis_url: str = "redis://redis:6379/0"
    frontend_url: str = "http://localhost:3000"
    cookie_secure: bool = False
    # The backend is normally reachable only through the Next.js container.
    # Forwarded client addresses are trusted only when the immediate peer is
    # inside one of these explicitly configured networks.
    trusted_proxy_cidrs: str = "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12"
    max_request_body_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=64 * 1024,
        le=64 * 1024 * 1024,
    )
    # Security activity is useful only while it is intentional. A bounded,
    # documented window avoids turning IP addresses and user agents into a
    # forever-log. The worker removes older rows once a day.
    security_event_retention_days: int = Field(default=365, ge=30, le=3650)
    session_ttl_seconds: int = 60 * 60 * 24 * 30
    plaid_client_id: str | None = None
    plaid_secret: str | None = None
    plaid_environment: Literal["sandbox", "production"] = "sandbox"
    plaid_webhook_url: str | None = None
    # Must exactly match an "Allowed redirect URI" in the Plaid dashboard.
    # Required for OAuth institutions in a mobile browser.
    plaid_redirect_uri: str | None = None
    # Local AI (llama.cpp llama-server or any OpenAI-compatible endpoint).
    # Suggestions only: the model can pick from existing category names and
    # nothing else, and it never marks a transaction reviewed.
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    # This default is overridable from Settings or the deployment environment.
    # Gateways that route by model name must receive a name they actually expose.
    llm_model: str = "SP-gemma4:26b"
    llm_timeout_seconds: int = 120
    # Merchants per categorization request. Bigger is fewer round trips;
    # smaller is more accurate on a small model, and the difference is large.
    # Small local models are generally more accurate with smaller batches,
    # while larger models can reduce round trips with a higher value.
    llm_batch_size: int = 40
    # The floor. Raise it for a large model, drop it to 2 for a small one.
    llm_min_batch_size: int = 4
    # How many bank connections this Plaid plan allows. Unset means "do not
    # enforce a limit" — deliberately, because Plaid's tiers change and a
    # hardcoded guess would either block a legitimate link or quietly fail to
    # warn. Set it to whatever the billing dashboard says.
    plaid_connection_limit: int | None = None
    # Backups. `backup_dir` must be a volume that outlives the container;
    # anything else is a backup that dies with the thing it protects.
    backup_dir: str = "/backups"
    backup_keep: int = 14
    # Kept under the worker's 600s job timeout so a hung pg_dump reports a
    # real error instead of being killed anonymously by arq.
    backup_timeout_seconds: int = 300
    # Who may operate the server, as a comma-separated list of email
    # addresses. A database dump contains every household on the instance, so
    # that authority cannot come from a household role — any owner could then
    # read every other household, and an invitation could hand it out.
    # Authority lives in the deployment environment instead, where only the
    # person who runs the server can set it. Empty means nobody, and the
    # instance-wide backup endpoints stay closed.
    #
    # Both spellings are accepted, and that is not tidiness. The container has
    # always read `OPERATOR_EMAILS`, while `docker-compose.yml`, `.env.example`
    # and the README all name `RAVEN_OPERATOR_EMAILS` — the host-side variable
    # compose maps *from*. Set the documented name anywhere compose is not
    # doing that mapping (a TrueNAS app's env, a k3s ConfigMap) and the backend
    # never sees it: no operator, backups closed, model picker read-only, and
    # nothing anywhere saying why.
    operator_emails: str = ""
    # The fallback, and it has to be a separate field rather than an alias on
    # the one above. `AliasChoices` takes the first name that is *present*,
    # and `docker-compose.yml` writes `OPERATOR_EMAILS: ${RAVEN_OPERATOR_EMAILS:-}`
    # — so the primary name is always present, empty, and always wins. The
    # alias would fall through only on a deployment that sets neither, which is
    # exactly the deployment that has nothing to fall through to.
    #
    # Emptiness is the signal, not absence. See the validator below.
    raven_operator_emails: str = ""
    # Open registration is only ever meant to bootstrap the very first
    # household. Once a user exists, joining requires an invitation unless this
    # is deliberately turned back on.
    allow_public_registration: bool = False

    @field_validator("plaid_connection_limit", mode="before")
    @classmethod
    def _blank_limit_means_unenforced(cls, value):
        """
        An empty `PLAID_CONNECTION_LIMIT` means "no limit", not a broken one.

        `docker-compose.yml` writes `PLAID_CONNECTION_LIMIT:
        ${PLAID_CONNECTION_LIMIT:-}` and the k3s ConfigMap carries
        `PLAID_CONNECTION_LIMIT: ""`, so the variable is *always present and
        usually empty* — and `int | None` cannot parse `""`. Settings then
        raise during import, alembic exits non-zero, and **the backend and the
        worker both refuse to start**, on a fresh install that followed
        `.env.example` exactly.

        Same shape as the `OPERATOR_EMAILS` fault below and worth stating once
        more: in a Compose deployment the interesting state of a variable is
        empty, never absent. Any optional non-string setting added here needs
        this treatment.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _accept_either_operator_name(self) -> "Settings":
        """
        Fall back to `RAVEN_OPERATOR_EMAILS` when `OPERATOR_EMAILS` is blank.

        Alex set the documented name on his TrueNAS app and the picker stayed
        read-only, because that name is the one Compose maps *from* and nothing
        was doing the mapping. Deciding on emptiness rather than absence is the
        point: the primary name is almost always present and empty, so a
        presence check never fires on the deployment that needs it.

        A value in `OPERATOR_EMAILS` always wins — an install that sets both
        deliberately keeps the specific one.
        """
        if not self.operator_emails.strip():
            self.operator_emails = self.raven_operator_emails

        if self.environment == "production":
            problems: list[str] = []
            if self.secret_key == DEVELOPMENT_SECRET or len(self.secret_key) < 32:
                problems.append(
                    "SECRET_KEY must be a unique value of at least 32 characters"
                )
            if not self.encryption_key:
                problems.append("ENCRYPTION_KEY must be a dedicated Fernet key")
            if self.plaid_environment == "production":
                if not self.plaid_client_id or not self.plaid_secret:
                    problems.append(
                        "PLAID_CLIENT_ID and PLAID_SECRET are required for "
                        "production Plaid"
                    )
                for name, value in (
                    ("PLAID_WEBHOOK_URL", self.plaid_webhook_url),
                    ("PLAID_REDIRECT_URI", self.plaid_redirect_uri),
                ):
                    if not value or urlsplit(value).scheme != "https":
                        problems.append(f"{name} must be an https URL")

            if problems:
                rendered = "; ".join(problems)
                raise ValueError(f"Unsafe production configuration: {rendered}")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
