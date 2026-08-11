import json
import uuid
from datetime import datetime, timedelta, timezone

import plaid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Account, HouseholdRole, InstitutionConnection
from app.schemas import (
    PlaidConnectionResponse,
    PlaidPublicTokenRequest,
    PlaidStatusResponse,
)
from app.security import AuthContext, current_auth
from app.services.plaid_service import (
    create_link_token,
    create_update_link_token,
    exchange_public_token,
    plaid_error_details,
    remove_connection,
    verify_webhook,
)
from app.services.security_audit import record_security_event
from app.worker import enqueue_job

router = APIRouter(prefix="/plaid", tags=["plaid"])
settings = get_settings()
MAX_WEBHOOK_BYTES = 1024 * 1024
# A queued sync finishes in seconds when the worker is healthy.
STALE_SYNC_AFTER = timedelta(minutes=10)


def _sync_is_stale(connection: InstitutionConnection) -> bool:
    if connection.status != "syncing":
        return False
    queued_at = connection.updated_at
    if queued_at is None:
        return True
    return datetime.now(timezone.utc) - queued_at > STALE_SYNC_AFTER


def _require_owner(auth: AuthContext) -> None:
    """
    Disconnecting is owner-only, and only disconnecting.

    This used to gate every Plaid operation, on the grounds that they "consume
    limited provider capacity and can drop synced history". Those are two
    different risks with two different answers. Capacity is a *shared budget*,
    best handled by showing what is left rather than by letting one person
    spend it; losing synced history is destructive and irreversible, and stays
    with the owner.

    So a member can connect a bank and repair a broken connection. Only the
    owner can remove one.
    """
    if auth.role != HouseholdRole.owner.value:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the household owner can disconnect a bank. Ask them to do "
            "it — removing a connection also removes its synced history.",
        )


def _require_editor(auth: AuthContext) -> None:
    """Anyone but a viewer may connect a bank and keep it working."""
    if auth.role == HouseholdRole.viewer.value:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Viewers cannot change bank connections",
        )


async def connections_in_use(db: AsyncSession, household_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count(InstitutionConnection.id)).where(
                InstitutionConnection.household_id == household_id
            )
        )
    ) or 0


async def _guard_capacity(db: AsyncSession, household_id: uuid.UUID) -> None:
    """
    Refuse a new connection once the plan's allowance is gone.

    Better here than at Plaid: their error arrives mid-flow, after somebody has
    already picked their bank and typed a password, and says nothing about
    whose plan it is.
    """
    limit = settings.plaid_connection_limit
    if limit is None:
        return
    used = await connections_in_use(db, household_id)
    if used >= limit:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"All {limit} bank connections on this plan are in use. Disconnect "
            "one you no longer need, or import a CSV statement into a manual "
            "account instead.",
        )


@router.post("/link-token")
async def link_token(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    await _guard_capacity(db, auth.household_id)
    try:
        token = await run_in_threadpool(create_link_token, auth.user.id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except plaid.ApiException as exc:
        _, message = plaid_error_details(exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, message) from exc
    await record_security_event(
        db,
        "plaid.link_started",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
    )
    await db.commit()
    return {"link_token": token}


@router.get("/status", response_model=PlaidStatusResponse)
async def plaid_status(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    used = await connections_in_use(db, auth.household_id)
    limit = settings.plaid_connection_limit
    return PlaidStatusResponse(
        configured=bool(settings.plaid_client_id and settings.plaid_secret),
        environment=settings.plaid_environment,
        webhook_configured=bool(settings.plaid_webhook_url),
        redirect_uri_configured=bool(settings.plaid_redirect_uri),
        connections_in_use=used,
        connection_limit=limit,
        connections_remaining=(max(limit - used, 0) if limit is not None else None),
    )


@router.get("/connections", response_model=list[PlaidConnectionResponse])
async def list_connections(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(
            InstitutionConnection,
            func.count(Account.id),
        )
        .outerjoin(
            Account,
            (Account.connection_id == InstitutionConnection.id)
            & Account.is_hidden.is_(False),
        )
        .where(InstitutionConnection.household_id == auth.household_id)
        .group_by(InstitutionConnection.id)
        .order_by(InstitutionConnection.created_at.asc())
    )
    return [
        PlaidConnectionResponse(
            id=connection.id,
            institution_name=connection.institution_name or "Financial institution",
            status=connection.status,
            account_count=account_count,
            last_synced_at=connection.last_synced_at,
            error_code=connection.error_code,
            sync_stale=_sync_is_stale(connection),
        )
        for connection, account_count in rows
    ]


async def _household_connection(
    db: AsyncSession,
    household_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> InstitutionConnection:
    connection = await db.scalar(
        select(InstitutionConnection).where(
            InstitutionConnection.id == connection_id,
            InstitutionConnection.household_id == household_id,
        )
    )
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return connection


@router.post("/connections/{connection_id}/sync", status_code=202)
async def sync_connection(
    connection_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    connection = await _household_connection(db, auth.household_id, connection_id)
    connection.status = "syncing"
    connection.error_code = None
    await record_security_event(
        db,
        "plaid.sync_requested",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"connection_id": connection.id},
    )
    await db.commit()
    await enqueue_job("sync_plaid_item", str(connection.id))
    return {"status": "sync_queued"}


# Repairing a connection that has stopped working is not destructive, and
# waiting for the owner means a broken feed stays broken.
@router.post("/connections/{connection_id}/link-token")
async def update_link_token(
    connection_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    connection = await _household_connection(db, auth.household_id, connection_id)
    try:
        token = await run_in_threadpool(
            create_update_link_token,
            auth.user.id,
            connection.encrypted_access_token,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except plaid.ApiException as exc:
        code, message = plaid_error_details(exc)
        connection.status = "error"
        connection.error_code = code
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, message) from exc
    await record_security_event(
        db,
        "plaid.repair_started",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"connection_id": connection.id},
    )
    await db.commit()
    return {"link_token": token}


@router.post("/connections/{connection_id}/updated", status_code=202)
async def connection_updated(
    connection_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    connection = await _household_connection(db, auth.household_id, connection_id)
    connection.status = "syncing"
    connection.error_code = None
    await record_security_event(
        db,
        "plaid.repair_completed",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"connection_id": connection.id},
    )
    await db.commit()
    await enqueue_job("sync_plaid_item", str(connection.id))
    return {"status": "sync_queued"}


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect(
    connection_id: uuid.UUID,
    request: Request,
    force_local: bool = False,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_owner(auth)
    connection = await _household_connection(db, auth.household_id, connection_id)
    try:
        await remove_connection(
            db,
            connection,
            remove_remote=not force_local,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except plaid.ApiException as exc:
        _, message = plaid_error_details(exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"{message}. Retry, or remove the local connection only.",
        ) from exc
    await record_security_event(
        db,
        "plaid.disconnected",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "institution": connection.institution_name or "Financial institution",
            "local_only": force_local,
        },
    )
    await db.commit()


@router.post("/exchange")
async def exchange(
    payload: PlaidPublicTokenRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    try:
        connection = await exchange_public_token(
            db,
            auth.household_id,
            payload.public_token,
            payload.institution_name,
            linked_by_user_id=auth.user.id,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except plaid.ApiException as exc:
        _, message = plaid_error_details(exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, message) from exc
    await record_security_event(
        db,
        "plaid.connected",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "connection_id": connection.id,
            "institution": connection.institution_name or "Financial institution",
        },
    )
    await db.commit()
    await enqueue_job("sync_plaid_item", str(connection.id))
    return {"connection_id": connection.id, "status": "sync_queued"}


@router.post("/webhook", status_code=202)
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_WEBHOOK_BYTES:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    "Webhook body is too large",
                )
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Content-Length is invalid",
            ) from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "Webhook body is too large",
            )
    raw_body = bytes(body)
    verified = await run_in_threadpool(
        verify_webhook,
        raw_body,
        request.headers.get("plaid-verification"),
    )
    if not verified:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Webhook signature is invalid",
        )
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Webhook body is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Webhook body must be a JSON object",
        )
    item_id = payload.get("item_id")
    webhook_type = payload.get("webhook_type")
    if not item_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing item_id")
    connection = await db.scalar(
        select(InstitutionConnection).where(
            InstitutionConnection.provider_item_id == item_id
        )
    )
    if connection and webhook_type in {"TRANSACTIONS", "HOLDINGS", "LIABILITIES"}:
        await enqueue_job("sync_plaid_item", str(connection.id))
    return {"accepted": True}
