"""The AI organizer: propose changes, then let a person decide."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AiProposal, HouseholdRole, ProposalKind, ProposalStatus
from app.schemas import (
    OrganizerRunResult,
    ProposalDecision,
    ProposalEdit,
    ProposalResponse,
)
from app.security import AuthContext, current_auth
from app.services import organizer, undo
from app.services.organizer_apply import StaleProposal, apply_proposal


async def capture_targets(db: AsyncSession, proposals) -> list[dict]:
    """
    The current state of every transaction the batch is about to touch.

    Only transaction-level proposals are reversible this way. A rule that was
    created or a budget line that was written are their own objects with their
    own delete buttons, and pretending to undo them here would mean inventing
    an inverse rather than restoring a value.
    """
    from app.models import ProposalKind, Transaction

    fields_by_kind = {
        ProposalKind.category: ["category_id", "categorization_source"],
        ProposalKind.transfer: ["is_transfer", "excluded_from_budget"],
        ProposalKind.exclusion: ["excluded_from_budget"],
        ProposalKind.duplicate: ["excluded_from_budget"],
    }
    wanted: dict[uuid.UUID, list[str]] = {}
    for proposal in proposals:
        fields = fields_by_kind.get(proposal.kind)
        if not fields:
            continue
        payload = proposal.payload or {}
        ids = payload.get("transaction_ids") or (
            [payload["transaction_id"]] if payload.get("transaction_id") else []
        )
        for raw in ids:
            wanted.setdefault(uuid.UUID(str(raw)), fields)

    if not wanted:
        return []
    rows = (
        await db.scalars(
            select(Transaction).where(Transaction.id.in_(list(wanted)))
        )
    ).all()
    out: list[dict] = []
    for transaction in rows:
        out.extend(undo.capture(transaction, wanted[transaction.id]))
    return out

router = APIRouter(prefix="/organizer", tags=["organizer"])


def _require_editor(auth: AuthContext) -> None:
    if auth.role == HouseholdRole.viewer.value:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Viewers cannot organize the ledger"
        )


def _render(item: AiProposal) -> ProposalResponse:
    return ProposalResponse(
        id=item.id,
        kind=item.kind,
        status=item.status,
        payload=item.payload,
        rationale=item.rationale,
        confidence=item.confidence,
        created_at=item.created_at,
    )


@router.post("/run", response_model=OrganizerRunResult)
async def run_organizer(
    month: date | None = None,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Look over the ledger and write down what could be tidied.

    Changes nothing. Everything it finds waits for a decision.
    """
    _require_editor(auth)
    counts = await organizer.run(db, auth.household_id, month or date.today())
    return OrganizerRunResult(**counts)


@router.get("/proposals", response_model=list[ProposalResponse])
async def list_proposals(
    kind: ProposalKind | None = None,
    status_filter: ProposalStatus = Query(
        default=ProposalStatus.pending, alias="status"
    ),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    query = select(AiProposal).where(
        AiProposal.household_id == auth.household_id,
        AiProposal.status == status_filter,
    )
    if kind is not None:
        query = query.where(AiProposal.kind == kind)
    rows = (
        await db.scalars(
            # Most certain first: the queue should open on the proposals least
            # likely to need thought.
            query.order_by(
                AiProposal.confidence.desc(), AiProposal.created_at.asc()
            )
        )
    ).all()
    return [_render(item) for item in rows]


@router.patch("/proposals/{proposal_id}", response_model=ProposalResponse)
async def edit_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalEdit,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Change what a proposal would do, before agreeing to it."""
    _require_editor(auth)
    proposal = await db.get(AiProposal, proposal_id)
    if proposal is None or proposal.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such proposal")
    if proposal.status != ProposalStatus.pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That one has already been decided."
        )
    proposal.payload = {**proposal.payload, **payload.payload}
    await db.commit()
    await db.refresh(proposal)
    return _render(proposal)


@router.post("/proposals/approve")
async def approve_proposals(
    decision: ProposalDecision,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply the chosen proposals.

    Each is applied on its own and a stale one does not stop the rest — a
    single vanished transaction should not block a queue of thirty.
    """
    _require_editor(auth)
    rows = (
        await db.scalars(
            select(AiProposal).where(
                AiProposal.id.in_(decision.proposal_ids),
                AiProposal.household_id == auth.household_id,
                AiProposal.status == ProposalStatus.pending,
            )
        )
    ).all()
    # Snapshot before anything changes: afterwards the previous values are
    # gone, and an undo cannot be reconstructed from the result.
    before = await capture_targets(db, rows)

    applied, skipped = 0, []
    for proposal in rows:
        try:
            await apply_proposal(db, proposal, auth.user.id)
            applied += 1
        except StaleProposal as exc:
            proposal.status = ProposalStatus.stale
            proposal.rationale = str(exc)[:400]
            skipped.append({"id": str(proposal.id), "reason": str(exc)})

    undo_id = None
    if applied and before:
        entry = undo.record(
            auth.household_id,
            auth.user.id,
            "organizer_apply",
            f"Applied {applied} organizer suggestion"
            f"{'' if applied == 1 else 's'}",
            before,
        )
        db.add(entry)
        await db.flush()
        undo_id = str(entry.id)

    await db.commit()
    return {"applied": applied, "skipped": skipped, "undo_id": undo_id}


@router.post("/proposals/reject")
async def reject_proposals(
    decision: ProposalDecision,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    rows = (
        await db.scalars(
            select(AiProposal).where(
                AiProposal.id.in_(decision.proposal_ids),
                AiProposal.household_id == auth.household_id,
                AiProposal.status == ProposalStatus.pending,
            )
        )
    ).all()
    from datetime import datetime, timezone

    for proposal in rows:
        proposal.status = ProposalStatus.rejected
        proposal.decided_at = datetime.now(timezone.utc)
        proposal.decided_by_user_id = auth.user.id
    await db.commit()
    return {"rejected": len(rows)}
