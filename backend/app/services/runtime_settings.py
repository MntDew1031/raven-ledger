"""
Settings a person can change without a redeploy.

Choosing Raven's model meant editing a Kubernetes manifest and restarting two
deployments, which is a poor fit for something you want to try three of in an
evening. Worse, the last round of benchmarking showed the **batch size** is as
decisive as the model — granite4.1:3b gets 9/10 with none wrong at a batch of
two and 8/10 with two wrong at four — so the two have to move together or the
setting is a trap.

**What is deliberately not here: `LLM_BASE_URL`.**

A model name is a harmless choice between things the configured endpoint
already offers. An endpoint is *where this household's financial data gets
sent*. Anything settable in the UI is settable by anyone who reaches the UI, and
a text box that redirects the ledger to an arbitrary server is not a feature —
it is an exfiltration path with a save button. The URL stays in the deployment
environment, where changing it requires access to the cluster.

Values fall back to the environment when unset, so an install that never opens
the settings page behaves exactly as it did before.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AppSetting
from app.security import operator_emails

AI_MODEL = "ai.model"
AI_MIN_BATCH = "ai.min_batch_size"

# Only these may be written through the API. An allowlist rather than a
# denylist: a new setting has to be considered before it becomes reachable,
# instead of becoming reachable the moment somebody adds a key.
WRITABLE = frozenset({AI_MODEL, AI_MIN_BATCH})

# A batch of one wastes a round trip per merchant; past this a small model
# starts attaching answers to the wrong ids, which was the whole finding.
MIN_BATCH_FLOOR = 1
MIN_BATCH_CEILING = 40

# Read on the hot path — every categorization batch and every chat turn — so
# the value is held rather than fetched each time. Cleared on write, and the
# process is small enough that a stale read cannot outlive a request by much.
_cache: dict[str, Any] = {}


def invalidate() -> None:
    _cache.clear()


async def get(db: AsyncSession, key: str, default: Any = None) -> Any:
    """
    A stored value, or `default` when nothing is stored.

    **What is cached is the stored value, not the resolved one.** Caching the
    resolution folded the caller's default into the cache: `effective_model`
    asks with the deployment's model as its default, so after one categoriz-
    ation run the settings page — which asks with a default of `None`
    precisely to learn whether anybody chose anything — got the deployment
    value back and reported it as "chosen here". The page then claimed a
    choice had been made that no one had made, and the deployment's own model
    could never be distinguished from a picked one.
    """
    if key in _cache:
        stored = _cache[key]
    else:
        row = await db.get(AppSetting, key)
        stored = row.value.get("value") if row else None
        _cache[key] = stored
    return default if stored is None else stored


async def put(
    db: AsyncSession, key: str, value: Any, user_id: uuid.UUID | None
) -> None:
    if key not in WRITABLE:
        raise ValueError(f"{key} is not a setting that can be changed here.")
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(
            AppSetting(
                key=key, value={"value": value}, updated_by_user_id=user_id
            )
        )
    else:
        row.value = {"value": value}
        row.updated_by_user_id = user_id
    invalidate()


async def effective_model(db: AsyncSession) -> str:
    """The model to use: the chosen one, or the deployed default."""
    return await get(db, AI_MODEL, get_settings().llm_model)


async def effective_min_batch(db: AsyncSession) -> int:
    settings = get_settings()
    value = await get(db, AI_MIN_BATCH, settings.llm_min_batch_size)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return settings.llm_min_batch_size
    # Clamped rather than rejected: a stored value that has drifted out of
    # range should degrade to something workable, not stop categorization.
    return max(MIN_BATCH_FLOOR, min(number, MIN_BATCH_CEILING))


async def snapshot(
    db: AsyncSession,
    *,
    reveal_endpoint: bool = False,
    can_change: bool = False,
) -> dict:
    """
    Everything the settings page needs, including where each value came from.

    `reveal_endpoint` is off by default. The URL is internal network topology —
    an address on the household's own LAN — and an integration token handed to
    Open WebUI has no business learning it. Operators see it because they are
    the ones who would change it.
    """
    settings = get_settings()
    stored_model = await get(db, AI_MODEL, None)
    stored_batch = await get(db, AI_MIN_BATCH, None)
    return {
        "model": stored_model or settings.llm_model,
        "model_source": "chosen here" if stored_model else "deployment",
        "min_batch_size": (
            int(stored_batch) if stored_batch else settings.llm_min_batch_size
        ),
        "min_batch_source": "chosen here" if stored_batch else "deployment",
        # Shown to operators, never editable — see the module docstring.
        "endpoint": (settings.llm_base_url or "") if reveal_endpoint else None,
        "endpoint_configured": bool(settings.llm_base_url),
        "batch_ceiling": MIN_BATCH_CEILING,
        # So the page can say "you cannot change this, and here is why" up
        # front. Letting somebody pick a model, press save and collect a 403
        # is how a working feature reads as a broken one.
        "can_change": can_change,
        # And *which* why. "You are not the operator" and "this server has no
        # operator at all" call for opposite actions — check your address
        # against the list, or go and create the list — and telling a
        # self-hoster who is plainly the operator that they are not one sends
        # them looking in the wrong place. Not the addresses themselves: who
        # runs the server is not something a member needs enumerated.
        "operator_configured": bool(operator_emails()),
    }
