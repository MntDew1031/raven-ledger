"""
Conversations that survive a refresh, and things Raven carries between them.

Two related problems the assistant had. It kept its messages in the browser, so
reloading the page threw the conversation away — which makes it a toy rather
than something you can pick up a financial question in tomorrow. And it began
every conversation knowing nothing, so anything explained last week had to be
explained again.

**Why this lives in Raven's database rather than an external memory service.**
Alex runs mem0 for his AI stack and asked whether the two would conflict. They
would not — they are separate systems — but financial facts belong beside the
financial data. Here they inherit the nightly dump that proves itself by
restoring, the household scoping, and the same encryption key. In an outside
store they would be a second copy of his finances with different backup and
retention properties, and nothing would keep the two in step. The memories are
readable through the existing API keys instead, so mem0 and Open WebUI can pull
them into their own context: one source of truth, shared outward.

**Memories are proposed, not taken.** The assistant can suggest a fact worth
remembering, and it sits unconfirmed until somebody agrees — the same rule the
organizer follows. An unconfirmed memory never reaches the model's context, so
a misheard sentence cannot quietly become something Raven believes about your
money.
"""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssistantMemory,
    AssistantMessage,
    AssistantThread,
    MemorySource,
)

# Enough for the model to have context without the prompt becoming mostly
# history. The oldest turns fall off; the memories below do not, which is the
# point of having them.
MAX_CONTEXT_MESSAGES = 16

# A long conversation should not be able to crowd out the ledger snapshot.
MAX_MEMORIES_IN_CONTEXT = 40

TITLE_MAX = 60


def title_from(question: str) -> str:
    """
    A thread's name, taken from what was actually asked.

    Better than "New conversation" and better than asking the model for a
    title: it costs nothing, it is deterministic, and the first question is
    almost always what the conversation turns out to be about.
    """
    text = re.sub(r"\s+", " ", question).strip()
    if not text:
        return "New conversation"
    if len(text) <= TITLE_MAX:
        return text
    # Cut at a word boundary so a title never ends mid-word.
    clipped = text[:TITLE_MAX].rsplit(" ", 1)[0]
    return f"{clipped or text[:TITLE_MAX]}…"


async def list_threads(
    db: AsyncSession, household_id: uuid.UUID, user_id: uuid.UUID
) -> list[dict]:
    rows = (
        await db.execute(
            select(
                AssistantThread,
                func.count(AssistantMessage.id).label("message_count"),
            )
            .outerjoin(
                AssistantMessage,
                AssistantMessage.thread_id == AssistantThread.id,
            )
            .where(
                AssistantThread.household_id == household_id,
                AssistantThread.user_id == user_id,
            )
            .group_by(AssistantThread.id)
            .order_by(AssistantThread.last_message_at.desc())
        )
    ).all()
    return [
        {
            "id": thread.id,
            "title": thread.title,
            "last_message_at": thread.last_message_at,
            "created_at": thread.created_at,
            "message_count": count,
        }
        for thread, count in rows
    ]


async def get_messages(
    db: AsyncSession, thread_id: uuid.UUID
) -> list[AssistantMessage]:
    return list(
        (
            await db.scalars(
                select(AssistantMessage)
                .where(AssistantMessage.thread_id == thread_id)
                .order_by(AssistantMessage.created_at.asc())
            )
        ).all()
    )


async def start_thread(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    first_question: str,
) -> AssistantThread:
    thread = AssistantThread(
        household_id=household_id,
        user_id=user_id,
        title=title_from(first_question),
    )
    db.add(thread)
    await db.flush()
    return thread


async def append(
    db: AsyncSession, thread: AssistantThread, role: str, content: str
) -> AssistantMessage:
    message = AssistantMessage(thread_id=thread.id, role=role, content=content)
    db.add(message)
    # Sorted by real activity rather than by when the thread was started, so
    # returning to an old conversation brings it back to the top.
    thread.last_message_at = datetime.now(timezone.utc)
    return message


async def context_messages(
    db: AsyncSession, thread_id: uuid.UUID
) -> list[dict]:
    """The tail of a thread, in the shape the model expects."""
    rows = await get_messages(db, thread_id)
    return [
        {"role": item.role, "content": item.content}
        for item in rows[-MAX_CONTEXT_MESSAGES:]
        if item.role in {"user", "assistant"}
    ]


# ---- Memories -------------------------------------------------------------


async def active_memories(
    db: AsyncSession, household_id: uuid.UUID
) -> list[AssistantMemory]:
    """
    What Raven is allowed to carry into a conversation.

    Confirmed **and** active. An unconfirmed memory is a suggestion awaiting a
    decision, and a suggestion has no business shaping an answer about money.
    """
    return list(
        (
            await db.scalars(
                select(AssistantMemory)
                .where(
                    AssistantMemory.household_id == household_id,
                    AssistantMemory.is_active.is_(True),
                    AssistantMemory.confirmed_at.is_not(None),
                )
                .order_by(AssistantMemory.created_at.asc())
                .limit(MAX_MEMORIES_IN_CONTEXT)
            )
        ).all()
    )


def render_memories(memories: list[AssistantMemory]) -> str:
    """The block that goes into the system prompt."""
    if not memories:
        return ""
    lines = "\n".join(f"- {item.fact}" for item in memories)
    return (
        "What this household has told you before. Treat these as true unless "
        "the ledger plainly contradicts them, and say so if it does:\n" + lines
    )


async def remember(
    db: AsyncSession,
    household_id: uuid.UUID,
    fact: str,
    *,
    source: MemorySource = MemorySource.person,
    user_id: uuid.UUID | None = None,
    confirmed: bool = True,
) -> AssistantMemory | None:
    """
    Write a memory down.

    Returns `None` when the fact already exists, so saying the same thing twice
    does not produce two of them. Comparison is on the normalized text rather
    than an id, because the same fact arriving from the assistant and from a
    person is still one fact.
    """
    cleaned = re.sub(r"\s+", " ", fact).strip()[:400]
    if not cleaned:
        return None
    existing = await db.scalar(
        select(AssistantMemory).where(
            AssistantMemory.household_id == household_id,
            func.lower(AssistantMemory.fact) == cleaned.lower(),
        )
    )
    if existing is not None:
        return None
    memory = AssistantMemory(
        household_id=household_id,
        fact=cleaned,
        source=source,
        created_by_user_id=user_id,
        confirmed_at=datetime.now(timezone.utc) if confirmed else None,
    )
    db.add(memory)
    return memory
