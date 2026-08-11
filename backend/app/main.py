import logging
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    accounts,
    activity,
    assistant,
    auth,
    budgets,
    categories,
    conversations,
    dashboard,
    forecast,
    goals,
    households,
    income,
    onboarding,
    organizer,
    plaid,
    profile,
    recurring,
    reports,
    rules,
    system,
    transactions,
)
from app.config import get_settings
from app.database import Base, engine
from app.middleware import RequestSizeLimitMiddleware
from app.security import SESSION_COOKIE, bearer_token, verify_encryption_key
from app.version import VERSION

settings = get_settings()


def verify_production_web_config(config=None) -> None:
    """Fail closed for settings used only by the public web process."""
    configured = config or settings
    if configured.environment != "production":
        return

    problems: list[str] = []
    if not configured.cookie_secure:
        problems.append("COOKIE_SECURE must be true")
    if urlsplit(configured.frontend_url).scheme != "https":
        problems.append("FRONTEND_URL must use https")
    if problems:
        rendered = "; ".join(problems)
        raise RuntimeError(f"Unsafe production web configuration: {rendered}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    verify_production_web_config()
    verify_encryption_key()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=VERSION,
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None if settings.environment == "production" else "/redoc",
    openapi_url=(
        None if settings.environment == "production" else "/openapi.json"
    ),
)
@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """
    Any failure nobody anticipated, reported rather than swallowed.

    FastAPI's default is a bare `{"detail": "Internal Server Error"}` — the
    same six words for a missing column, a Redis outage and a typo. Alex hit
    exactly that on the assistant three separate times, and each round of
    diagnosis started from nothing: I could reproduce none of it, because the
    cause was in his data or his environment rather than in a code path a stub
    can reach.

    So the response now carries **the exception type and a reference**, and the
    log carries the traceback under that same reference. He can read the
    reference off the screen and I can find the stack without asking him to
    reproduce anything.

    The message stays deliberately thin — a type name and an id, never the
    exception's own text, which routinely contains row values. This is a
    household's financial data; a stack trace belongs in the log.
    """
    reference = uuid.uuid4().hex[:8]
    logger.exception(
        "unhandled error %s on %s %s",
        reference,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        {
            "detail": (
                f"Something failed inside Raven ({type(exc).__name__}). "
                f"Reference {reference} — the details are in the backend log."
            )
        },
        status_code=500,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_bytes=settings.max_request_body_bytes,
)


def request_origin_error(request: Request) -> str | None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if request.url.path == f"{settings.api_prefix}/plaid/webhook":
        return None

    origin = request.headers.get("origin")
    has_cookie = bool(request.cookies.get(SESSION_COOKIE))
    has_api_key = bool(bearer_token(request))
    if not has_cookie and has_api_key:
        return None
    if not origin:
        return "Request origin is required"

    expected = urlsplit(settings.frontend_url)
    allowed_origin = f"{expected.scheme}://{expected.netloc}"
    if origin.rstrip("/") != allowed_origin.rstrip("/"):
        return "Request origin is not allowed"
    if request.headers.get("sec-fetch-site") == "cross-site":
        return "Cross-site requests are not allowed"
    return None


@app.middleware("http")
async def browser_origin_and_security_headers(request: Request, call_next):
    # Browser login/registration and every cookie-authenticated mutation must
    # prove which site initiated the request. Deliberate API clients use scoped
    # bearer keys and therefore do not need browser CSRF state.
    origin_error = request_origin_error(request)
    if origin_error:
        return JSONResponse({"detail": origin_error}, status_code=403)

    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    return response


for router in (
    auth.router,
    households.router,
    accounts.router,
    activity.router,
    categories.router,
    transactions.router,
    budgets.router,
    income.router,
    organizer.router,
    dashboard.router,
    forecast.router,
    goals.router,
    reports.router,
    onboarding.router,
    assistant.router,
    conversations.router,
    recurring.router,
    rules.router,
    system.router,
    plaid.router,
    profile.router,
):
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "raven-ledger-api"}
