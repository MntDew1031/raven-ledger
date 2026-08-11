"""Assistant conversations that persist, and the memories behind them."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AssistantMemory,
    AssistantProposal,
    AssistantThread,
    HouseholdRole,
    MemorySource,
)
from app.schemas import (
    ChatReply,
    ChatRequest,
    MemoryCreate,
    MemoryResponse,
    MemoryUpdate,
    AssistantProposalResponse,
    ThreadDetail,
    ThreadMessage,
    ThreadRename,
    ThreadSummary,
)
from app.security import AuthContext, current_auth, enforce_rate_limit
from app.services import conversations, proposals
from app.services.ai import ai_configured
from app.services.assistant import answer

router = APIRouter(prefix="/assistant", tags=["assistant"])


async def _own_thread(
    db: AsyncSession, thread_id: uuid.UUID, auth: AuthContext
) -> AssistantThread:
    thread = await db.get(AssistantThread, thread_id)
    # Threads belong to a person, not the household: a shared ledger does not
    # mean shared half-finished questions about money.
    if (
        thread is None
        or thread.household_id != auth.household_id
        or thread.user_id != auth.user.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such conversation")
    return thread


@router.get("/threads", response_model=list[ThreadSummary])
async def list_threads(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    rows = await conversations.list_threads(db, auth.household_id, auth.user.id)
    return [ThreadSummary(**row) for row in rows]


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def read_thread(
    thread_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    thread = await _own_thread(db, thread_id, auth)
    messages = await conversations.get_messages(db, thread.id)
    return ThreadDetail(
        id=thread.id,
        title=thread.title,
        messages=[
            ThreadMessage(
                role=item.role, content=item.content, created_at=item.created_at
            )
            for item in messages
        ],
    )


@router.patch("/threads/{thread_id}", response_model=ThreadSummary)
async def rename_thread(
    thread_id: uuid.UUID,
    payload: ThreadRename,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    thread = await _own_thread(db, thread_id, auth)
    thread.title = payload.title.strip()[:160]
    await db.commit()
    messages = await conversations.get_messages(db, thread.id)
    return ThreadSummary(
        id=thread.id,
        title=thread.title,
        last_message_at=thread.last_message_at,
        created_at=thread.created_at,
        message_count=len(messages),
    )


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    thread = await _own_thread(db, thread_id, auth)
    await db.delete(thread)
    await db.commit()


@router.post("/ask", response_model=ChatReply)
async def ask(
    payload: ChatRequest,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Ask a question, in a conversation that is kept.

    Read-only with respect to the ledger: the model is handed a snapshot and
    the household's confirmed memories, and its answer is text.
    """
    if not ai_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No local AI endpoint is configured. Set LLM_BASE_URL on the "
            "backend and worker.",
        )
    # A local GPU is a shared household resource: keep one person from
    # queueing dozens of long generations at once.
    await enforce_rate_limit(
        "assistant", str(auth.user.id), limit=40, window_seconds=10 * 60
    )

    if payload.thread_id is None:
        thread = await conversations.start_thread(
            db, auth.household_id, auth.user.id, payload.question
        )
        history: list[dict] = []
    else:
        thread = await _own_thread(db, payload.thread_id, auth)
        history = await conversations.context_messages(db, thread.id)

    await conversations.append(db, thread, "user", payload.question)
    memories = await conversations.active_memories(db, auth.household_id)

    result = await answer(
        db,
        auth.household_id,
        [*history, {"role": "user", "content": payload.question}],
        memory_block=conversations.render_memories(memories),
    )
    if not result.get("ok"):
        # The question is still saved: a failed generation should not lose what
        # was asked, and retrying should not mean retyping.
        await db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            result.get("error") or "The assistant could not answer.",
        )

    await conversations.append(db, thread, "assistant", result["reply"])

    # A proposal is stored pending, never applied here. The reply and the offer
    # arrive together; the ledger is untouched until somebody approves it.
    proposal_out = None
    raw_proposal = result.get("proposal")
    if raw_proposal:
        proposal = await proposals.create(
            db, auth.household_id, auth.user.id, thread.id, raw_proposal
        )
        if proposal is not None:
            proposal_out = await _render_proposal(db, proposal)

    await db.commit()
    return ChatReply(
        thread_id=thread.id,
        title=thread.title,
        reply=result["reply"],
        suggested_memory=result.get("suggested_memory"),
        proposal=proposal_out,
    )


async def _render_proposal(
    db: AsyncSession, proposal: AssistantProposal
) -> AssistantProposalResponse:
    view = await proposals.preview(
        db, proposal.household_id, proposal.kind, proposal.payload or {}
    )
    return AssistantProposalResponse(
        id=proposal.id,
        kind=proposal.kind,
        summary=proposal.summary,
        status=proposal.status,
        affected=view["affected"],
        examples=view["examples"],
        result=proposal.result,
        created_at=proposal.created_at,
    )


@router.get("/proposals", response_model=list[AssistantProposalResponse])
async def list_proposals(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Everything still waiting on a decision, newest first."""
    rows = (
        await db.scalars(
            select(AssistantProposal)
            .where(
                AssistantProposal.household_id == auth.household_id,
                AssistantProposal.status == "pending",
            )
            .order_by(AssistantProposal.created_at.desc())
            .limit(20)
        )
    ).all()
    return [await _render_proposal(db, row) for row in rows]


async def _own_proposal(
    db: AsyncSession, proposal_id: uuid.UUID, auth: AuthContext
) -> AssistantProposal:
    proposal = await db.get(AssistantProposal, proposal_id)
    if proposal is None or proposal.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such proposal")
    return proposal


@router.post("/proposals/{proposal_id}/approve", response_model=AssistantProposalResponse)
async def approve_proposal(
    proposal_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply it, having been looked at.

    **Rows are resolved again here**, never taken from the preview: a sync or a
    hand edit between suggesting and approving must not be overwritten by a
    stale count.
    """
    _require_editor(auth)
    proposal = await _own_proposal(db, proposal_id, auth)
    if proposal.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"That proposal is already {proposal.status}.",
        )
    await proposals.apply(db, proposal)
    await db.commit()
    await db.refresh(proposal)
    return await _render_proposal(db, proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=AssistantProposalResponse)
async def reject_proposal(
    proposal_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    proposal = await _own_proposal(db, proposal_id, auth)
    if proposal.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"That proposal is already {proposal.status}.",
        )
    proposal.status = "rejected"
    await db.commit()
    await db.refresh(proposal)
    return await _render_proposal(db, proposal)


# ---- Memories -------------------------------------------------------------


def _require_editor(auth: AuthContext) -> None:
    if auth.role == HouseholdRole.viewer.value:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Viewers cannot change memories"
        )


def _render(item: AssistantMemory) -> MemoryResponse:
    return MemoryResponse(
        id=item.id,
        fact=item.fact,
        source=item.source,
        is_active=item.is_active,
        confirmed_at=item.confirmed_at,
        created_at=item.created_at,
    )


@router.get("/memories", response_model=list[MemoryResponse])
async def list_memories(
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Everything Raven has been told, confirmed or not.

    Readable with an API key, which is how mem0 or Open WebUI can pull these
    into their own context without a second copy of the household's finances
    living outside this database.
    """
    rows = (
        await db.scalars(
            select(AssistantMemory)
            .where(AssistantMemory.household_id == auth.household_id)
            .order_by(AssistantMemory.created_at.desc())
        )
    ).all()
    return [_render(item) for item in rows]


@router.post("/memories", response_model=MemoryResponse, status_code=201)
async def create_memory(
    payload: MemoryCreate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    memory = await conversations.remember(
        db,
        auth.household_id,
        payload.fact,
        source=MemorySource.person,
        user_id=auth.user.id,
        confirmed=True,
    )
    if memory is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Raven already remembers that."
        )
    await db.commit()
    await db.refresh(memory)
    return _render(memory)


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: uuid.UUID,
    payload: MemoryUpdate,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Edit the wording, switch it off, or confirm a suggested one."""
    _require_editor(auth)
    memory = await db.get(AssistantMemory, memory_id)
    if memory is None or memory.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such memory")
    if payload.fact is not None:
        memory.fact = payload.fact.strip()[:400]
    if payload.is_active is not None:
        memory.is_active = payload.is_active
    if payload.confirmed is not None:
        from datetime import datetime, timezone

        memory.confirmed_at = (
            datetime.now(timezone.utc) if payload.confirmed else None
        )
    await db.commit()
    await db.refresh(memory)
    return _render(memory)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: uuid.UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    memory = await db.get(AssistantMemory, memory_id)
    if memory is None or memory.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such memory")
    await db.delete(memory)
    await db.commit()
