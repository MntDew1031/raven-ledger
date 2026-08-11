import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import plaid
from arq import create_pool, cron
from arq.connections import RedisSettings
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import InstitutionConnection, SecurityEvent
from app.security import verify_encryption_key
from app.services import runtime_settings
from app.services.ai import ai_configured, keep_warm, suggest_categories
from app.services.categorizer import categorize_uncategorized
from app.services.plaid_service import plaid_error_details, sync_connection
from app.services.recurring import detect_recurring
from app.services.security_audit import record_security_event
from app.services.transfers import link_transfer_pairs

settings = get_settings()

# Written by the worker so the API can report whether background jobs are
# actually being processed. Without it a dead worker looks identical to a slow
# one: the connection simply stays "syncing" forever.
WORKER_HEARTBEAT_KEY = "raven:worker:heartbeat"
WORKER_CAPABILITIES_KEY = "raven:worker:capabilities"
HEARTBEAT_TTL_SECONDS = 15 * 60
AI_CONFIG_SIGNATURE_VERSION = "2"


def normalized_ai_endpoint() -> str:
    """A trailing slash is routing syntax, not a different AI service."""
    return (settings.llm_base_url or "").strip().rstrip("/")


def ai_endpoint_signature() -> str:
    """Compare endpoints across containers without returning a private URL."""
    return hashlib.sha256(normalized_ai_endpoint().encode()).hexdigest()[:16]


def ai_config_signature(model: str | None = None) -> str:
    """
    Compare backend/worker AI config without exposing its URL or key.

    `model` is the effective one. Signing the deployed default meant the two
    sides agreed while using different models — the check reported a match it
    had not verified.
    """
    value = "|".join(
        [
            AI_CONFIG_SIGNATURE_VERSION,
            "configured" if ai_configured() else "disabled",
            normalized_ai_endpoint(),
            (model or settings.llm_model).strip(),
        ]
    )
    return hashlib.sha256(value.encode()).hexdigest()[:16]


async def enqueue_job(name: str, *args):
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        return await pool.enqueue_job(name, *args)
    finally:
        await pool.aclose()


async def _effective_model() -> str:
    """
    The model actually in use, chosen in Settings or inherited from the
    deployment. Read from the database because the choice lives there — the
    worker reported `LLM_MODEL` for weeks, so Settings showed "Worker AI
    settings: local" while every real request used the model he had picked.
    """
    try:
        async with SessionLocal() as db:
            return await runtime_settings.effective_model(db)
    except Exception:  # noqa: BLE001 - a heartbeat must never fail on this
        return settings.llm_model


async def _beat(redis) -> None:
    await redis.set(
        WORKER_HEARTBEAT_KEY,
        datetime.now(timezone.utc).isoformat(),
        ex=HEARTBEAT_TTL_SECONDS,
    )
    model = await _effective_model()
    await redis.hset(
        WORKER_CAPABILITIES_KEY,
        mapping={
            "ai_configured": "1" if ai_configured() else "0",
            "ai_model": model if ai_configured() else "",
            "ai_endpoint_signature": ai_endpoint_signature(),
            "ai_config_signature_version": AI_CONFIG_SIGNATURE_VERSION,
            "ai_config_signature": ai_config_signature(model),
        },
    )
    await redis.expire(WORKER_CAPABILITIES_KEY, HEARTBEAT_TTL_SECONDS)


async def _mark_failed(db, connection_id: uuid.UUID, code: str) -> None:
    """Record a failure on its own clean transaction."""
    await db.rollback()
    connection = await db.get(InstitutionConnection, connection_id)
    if connection:
        connection.status = "error"
        connection.error_code = code
        await record_security_event(
            db,
            "plaid.sync_failed",
            household_id=connection.household_id,
            user_id=connection.linked_by_user_id,
            success=False,
            details={"connection_id": connection.id, "error_code": code},
        )
        await db.commit()


async def sync_plaid_item(ctx, connection_id: str):
    identifier = uuid.UUID(connection_id)
    async with SessionLocal() as db:
        connection = await db.get(InstitutionConnection, identifier)
        if not connection:
            return {"error": "connection_not_found"}
        try:
            count = await sync_connection(db, connection)
            # Before anything is categorized: a leg of a transfer must not be
            # given a spending category, or it lands in a budget and is
            # believed. Runs on the whole household because the matching leg
            # may have arrived in an earlier sync of a different connection.
            await link_transfer_pairs(db, connection.household_id)
            # Rules, remembered merchants, and Plaid's own category run first,
            # so the AI layer is only ever asked about what is genuinely new.
            categorized = await categorize_uncategorized(db, connection.household_id)
            # Fresh transactions can complete a recurring pattern.
            await ctx["redis"].enqueue_job(
                "detect_recurring_household", str(connection.household_id)
            )
            return {"synced": count, "categorized": categorized}
        except plaid.ApiException as exc:
            code, _ = plaid_error_details(exc)
            await _mark_failed(db, identifier, code)
            raise
        except Exception:
            # A misconfigured encryption key, a database fault, anything at all:
            # the connection must not sit on "syncing" pretending to work.
            await _mark_failed(db, identifier, "SYNC_FAILED")
            raise


# One run is bounded so a slow model cannot exceed the job timeout, which used
# to mean a large backlog was quietly left half-finished. Chaining continues
# the work; the ceiling stops a pathological case from looping forever.
MAX_AI_CONTINUATIONS = 6


async def ai_review_household(ctx, household_id: str, depth: int = 0):
    """Local-AI category suggestions for the household's unreviewed backlog."""
    async with SessionLocal() as db:
        result = await suggest_categories(db, uuid.UUID(household_id))
    if result.get("more_to_do") and depth < MAX_AI_CONTINUATIONS:
        await ctx["redis"].enqueue_job("ai_review_household", household_id, depth + 1)
        result["continued"] = True
    return result


async def categorize_household(ctx, household_id: str, revisit_guesses: bool = False):
    """
    Re-run deterministic categorization. `revisit_guesses` is set when a person
    presses Run rules: a rule they wrote by hand must be able to correct a
    category that a guess put there, not merely fill blanks.
    """
    async with SessionLocal() as db:
        # Before categorizing: a newly connected card brings a year of payments
        # with it, and until they are recognised as transfers they are inflows
        # looking for a category. This used to run only on sync, so importing a
        # card and then pressing Run rules left them mis-filed.
        linked = await link_transfer_pairs(db, uuid.UUID(household_id))
        count = await categorize_uncategorized(
            db, uuid.UUID(household_id), revisit_guesses=revisit_guesses
        )
        return {"categorized": count, **linked}


async def sync_all_connections(ctx):
    """
    Scheduled safety net. Plaid webhooks drive normal updates, but a missed
    delivery or an offline worker would otherwise leave balances stale until
    somebody noticed and pressed Sync now.
    """
    async with SessionLocal() as db:
        connections = (await db.scalars(select(InstitutionConnection.id))).all()
    for connection_id in connections:
        # Queued individually so one broken institution cannot stop the rest.
        await ctx["redis"].enqueue_job("sync_plaid_item", str(connection_id))
    return {"queued": len(connections)}


async def detect_recurring_household(ctx, household_id: str):
    async with SessionLocal() as db:
        return await detect_recurring(db, uuid.UUID(household_id))


async def detect_recurring_all(ctx):
    """Daily sweep so recurring items stay fresh even without new syncs."""
    from app.models import Household

    async with SessionLocal() as db:
        household_ids = (await db.scalars(select(Household.id))).all()
    for household_id in household_ids:
        await ctx["redis"].enqueue_job("detect_recurring_household", str(household_id))
    return {"queued": len(household_ids)}


async def accrue_loan_interest(ctx):
    """
    Add a month of interest to manually tracked debts.

    Runs daily but is a no-op except on the first run of a month — guarded in
    the service by `interest_applied_through`, because a job that
    double-charges interest when it retries is worse than one that never runs.
    """
    from datetime import date as _date

    from app.models import Household
    from app.services.loans import accrue_interest

    async with SessionLocal() as db:
        household_ids = (await db.scalars(select(Household.id))).all()
        total = 0
        for household_id in household_ids:
            result = await accrue_interest(db, household_id, _date.today())
            total += result["charged"]
        await db.commit()
        return {"charged": total}


async def nightly_backup(ctx):
    """
    Take a dump and immediately prove it restores.

    Verification runs here rather than on a separate schedule because an
    unverified backup is exactly as reassuring as a verified one right up to
    the moment it matters. Restoring into a scratch database costs seconds at
    this data size, so there is no reason to skip it.
    """
    from app.services.backup import BackupError, create_backup, verify_backup
    from app.version import VERSION

    try:
        info = await create_backup(app_version=VERSION)
    except BackupError as exc:
        return {"ok": False, "stage": "dump", "error": str(exc)}
    try:
        result = await verify_backup(info.name)
    except BackupError as exc:
        return {"ok": False, "stage": "verify", "name": info.name, "error": str(exc)}
    return {
        "ok": bool(result.get("ok")),
        "name": info.name,
        "bytes": info.bytes,
        "error": result.get("error"),
    }


async def warm_ai_model(ctx):
    """Keep the *chosen* model resident so user requests never cold-load."""
    if not ai_configured():
        return {"warmed": False, "reason": "not_configured"}
    return await keep_warm(await _effective_model())


async def worker_heartbeat(ctx):
    await _beat(ctx["redis"])
    return {"ok": True}


async def purge_security_events(ctx):
    """Apply the documented activity-log retention window once a day."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.security_event_retention_days
    )
    async with SessionLocal() as db:
        result = await db.execute(
            delete(SecurityEvent).where(SecurityEvent.created_at < cutoff)
        )
        await db.commit()
    return {
        "deleted": result.rowcount or 0,
        "retention_days": settings.security_event_retention_days,
    }


async def startup(ctx):
    verify_encryption_key()
    await _beat(ctx["redis"])


class WorkerSettings:
    functions = [
        sync_plaid_item,
        categorize_household,
        ai_review_household,
        detect_recurring_household,
    ]
    cron_jobs = [
        # Every five minutes, so the API can tell a dead worker from a slow job.
        cron(worker_heartbeat, minute=set(range(0, 60, 5)), run_at_startup=True),
        # Security metadata is deliberately not kept forever.
        cron(purge_security_events, hour={2}, minute={45}),
        # Four times a day, offset from the hour to avoid provider rush.
        cron(sync_all_connections, hour={0, 6, 12, 18}, minute={20}),
        # Daily recurring-merchant sweep, after the midnight sync settles.
        cron(detect_recurring_all, hour={4}, minute={40}),
        # Nightly dump and test restore, in the quiet hour before that sweep.
        cron(nightly_backup, hour={3}, minute={10}),
        # Loan interest. Daily, but a no-op except on the month's first run.
        cron(accrue_loan_interest, hour={5}, minute={5}),
        # Keep the AI model loaded. No-op when no endpoint is configured.
        cron(warm_ai_model, minute=set(range(0, 60, 10)), run_at_startup=True),
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 60 * 10
    keep_result = 60 * 60
