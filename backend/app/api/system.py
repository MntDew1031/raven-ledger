import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.schemas import (
    AiConfigUpdate,
    AiModelsResponse,
    AiStatusResponse,
    BackupListResponse,
    BackupSummary,
    BackupVerifyResponse,
    OperatorConfirmRequest,
    WorkerStatusResponse,
)
from app.security import (
    AuthContext,
    client_ip,
    current_auth,
    enforce_rate_limit,
    grant_operator_confirmation,
    has_operator_confirmation,
    is_operator,
    redis,
    verify_password,
    verify_user_mfa,
)
from app.services import backup as backups
from app.services.ai import ai_configured, list_models
from app.services.ai import probe as ai_probe
from app.services.runtime_settings import effective_model
from app.services.security_audit import record_security_event
from app.version import VERSION
from app.worker import (
    AI_CONFIG_SIGNATURE_VERSION,
    HEARTBEAT_TTL_SECONDS,
    WORKER_CAPABILITIES_KEY,
    WORKER_HEARTBEAT_KEY,
    ai_endpoint_signature,
    ai_config_signature,
    enqueue_job,
)

settings = get_settings()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

# The worker beats every five minutes, so two missed beats means something is
# wrong rather than merely slow.
OFFLINE_AFTER = timedelta(minutes=11)


@router.get("/worker", response_model=WorkerStatusResponse)
async def worker_status(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Whether background jobs are actually being processed. Syncs, categorization,
    and the scheduled refresh all run in the worker, so if it is down the UI
    would otherwise just show work that never finishes.
    """
    raw = await redis.get(WORKER_HEARTBEAT_KEY)
    last_seen: datetime | None = None
    if raw:
        try:
            last_seen = datetime.fromisoformat(raw)
        except ValueError:
            last_seen = None

    online = bool(last_seen and datetime.now(timezone.utc) - last_seen < OFFLINE_AFTER)
    try:
        queued = int(await redis.zcard("arq:queue"))
    except Exception:  # noqa: BLE001 - queue depth is best-effort diagnostics
        queued = 0

    capabilities = await redis.hgetall(WORKER_CAPABILITIES_KEY)
    worker_ai_configured: bool | None = None
    worker_ai_model: str | None = None
    config_matches: bool | None = None
    endpoint_matches: bool | None = None
    model_matches: bool | None = None
    if capabilities:
        worker_ai_configured = capabilities.get("ai_configured") == "1"
        worker_ai_model = capabilities.get("ai_model") or None
        backend_model = await effective_model(db)
        # A pre-1.73.1 worker used an ambiguous signature. Treat that as
        # unknown during a rolling restart rather than announcing a mismatch
        # and disabling a perfectly healthy categorization button.
        if (
            capabilities.get("ai_config_signature_version")
            == AI_CONFIG_SIGNATURE_VERSION
        ):
            endpoint_matches = (
                capabilities.get("ai_endpoint_signature")
                == ai_endpoint_signature()
            )
            model_matches = worker_ai_model == backend_model
            config_matches = (
                worker_ai_configured == ai_configured()
                and endpoint_matches
                and model_matches
                and capabilities.get("ai_config_signature")
                == ai_config_signature(backend_model)
            )

    return WorkerStatusResponse(
        online=online,
        last_seen_at=last_seen,
        queued_jobs=queued,
        heartbeat_ttl_seconds=HEARTBEAT_TTL_SECONDS,
        ai_configured=worker_ai_configured,
        ai_model=worker_ai_model,
        ai_config_matches_backend=config_matches,
        ai_endpoint_matches_backend=endpoint_matches,
        ai_model_matches_backend=model_matches,
        web_backups_enabled=is_operator(auth.user),
    )


@router.get("/ai", response_model=AiStatusResponse)
async def ai_status(
    probe: bool = False,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Whether a local AI endpoint is available for category suggestions. With
    `probe=true`, performs one live round trip so a wrong URL, key, or model
    name shows up here instead of inside a silent background job.
    """
    chosen = (await effective_model(db)) if ai_configured() else None
    result = AiStatusResponse(
        configured=ai_configured(),
        # The model actually in use, not the one the deployment shipped with.
        # Reporting the environment value made the Settings picker look broken:
        # the choice saved, and every screen carried on naming the old model.
        model=chosen,
    )
    if probe and result.configured:
        # Probe what is actually used. Probing `LLM_MODEL` tested a model
        # nobody had selected — Test connection failed with "Invalid model
        # name passed in model=local" while real requests were working.
        outcome = await ai_probe(chosen)
        result.probe_ok = outcome.get("ok")
        result.probe_latency_ms = outcome.get("latency_ms")
        result.probe_error = outcome.get("error")
    return result


@router.get("/ai/models", response_model=AiModelsResponse)
async def ai_models(auth: AuthContext = Depends(current_auth)):
    """Model names the configured endpoint reports, for choosing LLM_MODEL."""
    outcome = await list_models()
    return AiModelsResponse(
        ok=bool(outcome.get("ok")),
        models=outcome.get("models", []),
        error=outcome.get("error"),
    )


@router.get("/ai/config")
async def read_ai_config(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Which model Raven is using, and where that choice came from.

    Readable by anyone signed in — it is a diagnostic, and "which model
    answered that" is a fair question. The *endpoint* is not part of that
    answer: it is an address on the household's own network, and an API key
    given to another tool should not learn the LAN's shape. Operators see it,
    because they are who would change it.
    """
    from app.services.runtime_settings import snapshot

    operator = _is_operator_context(auth)
    return await snapshot(db, reveal_endpoint=operator, can_change=operator)


@router.put("/ai/config")
async def write_ai_config(
    payload: AiConfigUpdate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Change the model and the batch size without a redeploy.

    The endpoint URL is not settable here and will not be. A model name is a
    choice between things the configured server already offers; an endpoint is
    where this household's financial data gets sent, and a text box that
    redirects it to an arbitrary host is an exfiltration path with a save
    button. That stays in the deployment environment.
    """
    _require_operator(auth, doing="AI settings")
    from app.services.runtime_settings import (
        AI_MIN_BATCH,
        AI_MODEL,
        put,
        snapshot,
    )

    if payload.model is not None:
        await put(db, AI_MODEL, payload.model.strip(), auth.user.id)
    if payload.min_batch_size is not None:
        await put(db, AI_MIN_BATCH, int(payload.min_batch_size), auth.user.id)
    await db.commit()
    # The worker reads the shared PostgreSQL setting before every AI job. Ask
    # it to refresh its visible status now too, so Settings does not show the
    # previous model for up to five minutes after a successful save.
    try:
        await enqueue_job("refresh_worker_status")
    except Exception:  # noqa: BLE001 - saving does not depend on diagnostics
        logger.warning("could not queue the worker AI status refresh", exc_info=True)
    return await snapshot(db, can_change=True)


def _is_operator_context(auth: AuthContext) -> bool:
    """Operator authority, as a question rather than an exception."""
    try:
        _require_operator(auth)
    except HTTPException:
        return False
    return True


def _require_operator(auth: AuthContext, doing: str = "Backups") -> None:
    """
    A dump is the whole instance: every household, every password hash, every
    encrypted provider token. Household roles cannot gate it — an owner of one
    household would be able to read all the others, and an invitation could
    hand that out. Authority comes from `RAVEN_OPERATOR_EMAILS` in the
    deployment environment instead, which nothing inside the app can grant.

    `doing` names the thing being refused. The check guards more than backups
    now, and answering "Instance-wide backups are managed by the server
    operator" to somebody who just picked a model is worse than saying nothing
    — it describes a feature they were not using, so the real reason never
    reaches them. That is exactly how a saved model choice looked like a UI
    that quietly did nothing.
    """
    if auth.via_api_key:
        # Even when the key's creator is the operator. This authority comes
        # from a person at a browser who has just re-entered their password;
        # a long-lived bearer token held by a tool is the opposite of that.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{doing} cannot be reached with an API key.",
        )
    if not is_operator(auth.user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{doing} are managed by the server operator. Add this address to "
            "OPERATOR_EMAILS in the deployment environment to allow it.",
        )


async def _require_confirmation(auth: AuthContext) -> None:
    """
    Step up before anything leaves the machine or is destroyed.

    Being signed in as the operator is not enough on its own: a stolen session
    cookie would otherwise be a standing licence to export every household.
    """
    if not await has_operator_confirmation(auth.session_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Confirm your password before downloading or deleting a backup.",
        )


@router.post("/operator/confirm", status_code=204)
async def confirm_operator(
    payload: OperatorConfirmRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Re-authenticate for a few minutes of sensitive backup access."""
    _require_operator(auth)
    await enforce_rate_limit(
        "operator-confirm",
        client_ip(request),
        limit=5,
        window_seconds=300,
    )
    password_ok = verify_password(payload.password, auth.user.password_hash)
    mfa_ok = not auth.user.mfa_enabled_at
    recovery_used = False
    if password_ok and auth.user.mfa_enabled_at and payload.mfa_code:
        mfa_ok, recovery_used = verify_user_mfa(auth.user, payload.mfa_code)
    if not password_ok or not mfa_ok:
        await record_security_event(
            db,
            "operator.step_up",
            request=request,
            household_id=auth.household_id,
            user_id=auth.user.id,
            success=False,
            details={"mfa_required": bool(auth.user.mfa_enabled_at)},
        )
        await db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The password or authentication code is invalid."
            if auth.user.mfa_enabled_at
            else "That password is wrong.",
        )
    await record_security_event(
        db,
        "operator.step_up",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"recovery_code_used": recovery_used},
    )
    await db.commit()
    await grant_operator_confirmation(auth.session_id)


@router.get("/backups", response_model=BackupListResponse)
async def list_backups(auth: AuthContext = Depends(current_auth)):
    """Backups on disk, newest first, with whatever each one has been proven to be."""
    _require_operator(auth)
    directory = backups.backup_dir()
    writable = directory.is_dir() and os.access(directory, os.W_OK)
    error = None
    if not writable:
        error = (
            f"{directory} is not a writable directory in this container. "
            "Mount a persistent volume there or backups cannot be taken."
        )
    return BackupListResponse(
        backups=[BackupSummary(**vars(item)) for item in backups.list_backups()],
        keep=settings.backup_keep,
        directory=str(directory),
        encryption_fingerprint=backups.encryption_fingerprint(),
        writable=writable,
        error=error,
    )


@router.post("/backups", response_model=BackupSummary, status_code=201)
async def create_backup(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_operator(auth)
    try:
        info = await backups.create_backup(app_version=VERSION)
    except backups.BackupError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    await record_security_event(
        db,
        "backup.created",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"name": info.name, "bytes": info.bytes},
    )
    await db.commit()
    return BackupSummary(**vars(info))


@router.post("/backups/{name}/verify", response_model=BackupVerifyResponse)
async def verify_backup(
    name: str,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Prove an archive restores, by restoring it into a scratch database and
    counting what arrives. Non-destructive: the live database is never touched.
    """
    _require_operator(auth)
    try:
        result = await backups.verify_backup(name)
    except backups.BackupError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await record_security_event(
        db,
        "backup.verified",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        success=bool(result.get("ok")),
        details={"name": name, "duration_ms": result.get("duration_ms")},
    )
    await db.commit()
    return BackupVerifyResponse(**result)


@router.get("/backups/{name}/download")
async def download_backup(
    name: str,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream an archive out, so a copy can live somewhere other than the machine
    it protects. A backup that only exists on the failing host is not a backup.
    """
    _require_operator(auth)
    await _require_confirmation(auth)
    try:
        path = backups.resolve(name)
    except backups.BackupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await record_security_event(
        db,
        "backup.downloaded",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"name": name},
    )
    await db.commit()
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=name,
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/backups/{name}", status_code=204)
async def delete_backup(
    name: str,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_operator(auth)
    await _require_confirmation(auth)
    try:
        backups.delete_backup(name)
    except backups.BackupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await record_security_event(
        db,
        "backup.deleted",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"name": name},
    )
    await db.commit()
