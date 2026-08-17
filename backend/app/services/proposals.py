"""
Changes the assistant suggests, and a person approves.

Alex chose **propose → approve → act** over both a read-only assistant and one
that acts directly on "safe" things. The distinction he cared about is the
audit trail: he wants to see what was suggested, what he agreed to, and what it
actually did.

Three rules hold this together, and each exists because the obvious design is
worse:

1. **A proposal names intent, never row ids.** "Everything from Chipotle with
   no category yet", not a list of UUIDs. A model asked for ids will invent
   them, and an invented id either matches nothing or matches something
   unrelated — the second being a silent wrong edit. Naming intent means a
   nonsense proposal resolves to zero rows and is refused at validation.

2. **Rows are resolved at approval, not at suggestion.** The count shown when
   the proposal is made is a preview; the count applied is computed again from
   the ledger. Between the two, a sync can arrive or a person can categorise by
   hand, and the approval must act on what is true when the button is pressed.

3. **The summary is written by Raven, not the model.** If the model wrote its
   own description, a proposal could describe itself as one thing and do
   another. The sentence on screen is generated from the validated payload.

The marker mechanism deliberately mirrors `REMEMBER:` in `assistant.py`, which
is already proven to work on his 35B through LiteLLM. Native tool-calling would
be tidier and is not reliably available on that path.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssistantProposal,
    CategorizationRule,
    Category,
    RuleMatchType,
    Transaction,
)
from app.services.splits import countable
from app.services.transfers import looks_like_a_payment

logger = logging.getLogger(__name__)

PROPOSE_PREFIX = "PROPOSE:"

# A single proposal must never be able to rewrite a whole ledger in one press.
# Above this it is not a suggestion, it is a migration, and it should be done
# on the transactions page where every row is visible.
MAX_AFFECTED = 200

KINDS = ("categorize", "create_rule")


def split_proposal(reply: str) -> tuple[str, dict | None]:
    """
    Pull a `PROPOSE:` line out of a reply.

    Returned separately so the marker never reaches the person reading the
    answer — they see a normal reply and a card offering the change. A line
    that is not valid JSON is dropped rather than shown: a half-parsed proposal
    is worse than none.
    """
    kept: list[str] = []
    found: dict | None = None
    for line in reply.strip().splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith(PROPOSE_PREFIX):
            kept.append(line)
            continue
        body = stripped[len(PROPOSE_PREFIX) :].strip()
        # Models like to wrap JSON in fences even when told not to.
        body = re.sub(r"^```(?:json)?|```$", "", body).strip()
        try:
            candidate = json.loads(body)
        except (ValueError, TypeError):
            logger.info("assistant proposed unparsable JSON: %r", body[:200])
            continue
        if isinstance(candidate, dict) and found is None:
            found = candidate
    return "\n".join(kept).strip(), found


async def validate(
    db: AsyncSession, household_id: uuid.UUID, raw: dict
) -> tuple[dict | None, str, str]:
    """
    Turn a model's suggestion into something executable, or reject it.

    Returns `(payload, kind, summary)` with `payload` None when the proposal is
    not usable. Everything it references is checked against this household —
    a category name the model made up, or one belonging to somebody else, is
    the most likely failure and it must not become a silent no-op.
    """
    kind = str(raw.get("action") or raw.get("kind") or "").strip()
    if kind not in KINDS:
        return None, "", ""

    merchant = str(raw.get("merchant") or "").strip()
    category_name = str(raw.get("category") or "").strip()
    if not merchant or len(merchant) < 2 or len(merchant) > 120:
        return None, "", ""
    if not category_name:
        return None, "", ""

    category = await db.scalar(
        select(Category).where(
            Category.household_id == household_id,
            func.lower(Category.name) == category_name.lower(),
        )
    )
    if category is None:
        # Deliberately not "closest match". Applying a change to a category
        # nobody named is exactly the silent wrong edit this design exists to
        # prevent.
        return None, "", ""

    payload = {
        "merchant": merchant,
        "category_id": str(category.id),
        "category_name": category.name,
    }
    if kind == "categorize":
        summary = (
            f"Categorise transactions matching “{merchant}” as "
            f"{category.name}, where no category is set yet"
        )
    else:
        summary = (
            f"Create a rule: anything containing “{merchant}” is "
            f"{category.name}"
        )
    return payload, kind, summary[:400]


async def matching_transactions(
    db: AsyncSession, household_id: uuid.UUID, merchant: str
) -> list[Transaction]:
    """
    The rows a `categorize` proposal would touch.

    **Only rows with no category.** A proposal must never overwrite a category
    somebody already chose — that is a correction, and corrections are made by
    the person who disagrees, on the transactions page.

    **And never a card payment.** Found in the drill: a proposal for "Costco"
    matched `COSTCO VISA PAYMENT` — the transfer leg paying the card off — and
    filed $702.69 of moving your own money as groceries. A substring is a blunt
    instrument and card names contain merchant names. `is_transfer` catches
    these only once something has flagged them, which is *after* the next sync;
    a proposal approved before that would already have done the damage. So the
    descriptor is checked too, with the same helper the transfer pass uses.
    """
    pattern = f"%{merchant.lower()}%"
    rows = list(
        (
            await db.scalars(
                select(Transaction)
                .where(
                    Transaction.household_id == household_id,
                    Transaction.category_id.is_(None),
                    Transaction.is_transfer.is_(False),
                    countable(),
                    func.lower(
                        func.coalesce(
                            Transaction.merchant_name,
                            Transaction.original_description,
                        )
                    ).like(pattern),
                )
                .order_by(Transaction.posted_date.desc())
                .limit(MAX_AFFECTED + 1)
            )
        ).all()
    )
    return [row for row in rows if not looks_like_a_payment(row)]


async def preview(
    db: AsyncSession, household_id: uuid.UUID, kind: str, payload: dict
) -> dict:
    """How many rows this would touch, and a few of them by name."""
    if kind != "categorize":
        return {"affected": None, "examples": []}
    rows = await matching_transactions(db, household_id, payload["merchant"])
    return {
        "affected": len(rows),
        "examples": [
            {
                "posted_date": row.posted_date.isoformat(),
                "merchant": (row.merchant_name or row.original_description)[:60],
                "amount": str(row.amount),
            }
            for row in rows[:5]
        ],
    }


async def create(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID | None,
    thread_id: uuid.UUID | None,
    raw: dict,
) -> AssistantProposal | None:
    payload, kind, summary = await validate(db, household_id, raw)
    if payload is None:
        return None
    # **A proposal that matches nothing is not a proposal.** Alex was offered
    # "Categorise transactions matching 'Payment - Bilt Housing'" — a merchant
    # string that appears nowhere in his ledger, because the model wrote a
    # description rather than copying the merchant. The card rendered with
    # Approve disabled and no way to tell whether that was a bug or the point.
    # Better to say nothing and let the reply stand on its own.
    if kind == "categorize":
        if not await matching_transactions(db, household_id, payload["merchant"]):
            logger.info(
                "assistant proposed a merchant that matches nothing: %r",
                payload["merchant"],
            )
            return None
    proposal = AssistantProposal(
        household_id=household_id,
        thread_id=thread_id,
        created_by_user_id=user_id,
        kind=kind,
        payload=payload,
        summary=summary,
        status="pending",
    )
    db.add(proposal)
    await db.flush()
    return proposal


async def apply(
    db: AsyncSession, proposal: AssistantProposal
) -> dict:
    """
    Do the thing, having been approved.

    Re-resolves from the ledger; the preview count is never trusted. Raises
    nothing — a failure is recorded on the proposal so the person who approved
    it can see what happened rather than being told "something went wrong".
    """
    household_id = proposal.household_id
    payload = proposal.payload or {}
    try:
        if proposal.kind == "categorize":
            rows = await matching_transactions(
                db, household_id, payload["merchant"]
            )
            if len(rows) > MAX_AFFECTED:
                proposal.status = "failed"
                proposal.result = {
                    "error": (
                        f"{len(rows)} transactions match, which is more than "
                        f"one approval should change. Narrow it, or use the "
                        f"transactions page where every row is visible."
                    )
                }
                return proposal.result
            category_id = uuid.UUID(payload["category_id"])
            for row in rows:
                row.category_id = category_id
                # Sourced as a person's decision, because a person approved it.
                # Labelling it `ai` would let the transfer sweep treat it as a
                # guess and clear it — see `_person_decided` in transfers.py.
                row.categorization_source = "manual"
            result = {"categorized": len(rows)}
        else:
            existing = await db.scalar(
                select(CategorizationRule).where(
                    CategorizationRule.household_id == household_id,
                    func.lower(CategorizationRule.merchant_pattern)
                    == payload["merchant"].lower(),
                )
            )
            if existing is not None:
                result = {"created": 0, "note": "a rule for that already exists"}
            else:
                db.add(
                    CategorizationRule(
                        household_id=household_id,
                        name=f"Always categorize {payload['merchant']}",
                        match_type=RuleMatchType.contains,
                        merchant_pattern=payload["merchant"],
                        category_id=uuid.UUID(payload["category_id"]),
                    )
                )
                result = {"created": 1}
        proposal.status = "approved"
        proposal.applied_at = datetime.now(timezone.utc)
        proposal.result = result
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("applying proposal %s failed", proposal.id)
        proposal.status = "failed"
        proposal.result = {"error": f"{type(exc).__name__}"}
        return proposal.result
