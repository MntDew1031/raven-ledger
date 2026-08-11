from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import AssistantRequest, AssistantResponse
from app.security import AuthContext, current_auth, enforce_rate_limit
from app.services.ai import ai_configured
from app.services.assistant import answer

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantResponse)
async def chat(
    payload: AssistantRequest,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Ask a question about this household's finances. Read-only: the model is
    handed a snapshot and its answer is text, never an action.
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
        "assistant",
        str(auth.user.id),
        limit=40,
        window_seconds=10 * 60,
    )
    result = await answer(
        db, auth.household_id, [m.model_dump() for m in payload.messages]
    )
    if not result.get("ok"):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            result.get("error") or "The assistant could not answer.",
        )
    return AssistantResponse(reply=result["reply"])
