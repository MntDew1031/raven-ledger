import time
import uuid
from datetime import date
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Account, Category, Tag, Transaction
from app.schemas import (
    AiProgressResponse,
    AiReviewResponse,
    BulkReviewRequest,
    BulkReviewResponse,
    BulkTransactionActionRequest,
    BulkTransactionActionResponse,
    ImportCommit,
    SplitRequest,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from app.security import AuthContext, current_auth, enforce_rate_limit
from app.services import memory
from app.services import splits as split_service
from app.services.ai import (
    ai_configured,
    read_progress,
    unreviewed_guess,
    write_progress,
)
from app.services.security_audit import record_security_event
from app.worker import enqueue_job

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _require_editor(auth: AuthContext) -> None:
    if auth.role == "viewer":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "View-only household members cannot change transactions",
        )


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(
    start: date | None = None,
    end: date | None = None,
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    search: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    reviewed: bool | None = None,
    include_split_lines: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Transaction)
        .options(
            selectinload(Transaction.tags),
            selectinload(Transaction.splits).selectinload(Transaction.tags),
        )
        .where(Transaction.household_id == auth.household_id)
    )
    if not include_split_lines:
        # One row per bank charge by default. The lines travel inside their
        # parent's `splits`, so nothing is hidden — but a ledger that listed
        # both would show the same money twice.
        query = query.where(Transaction.parent_transaction_id.is_(None))
    if start:
        query = query.where(Transaction.posted_date >= start)
    if end:
        query = query.where(Transaction.posted_date <= end)
    if account_id:
        query = query.where(Transaction.account_id == account_id)
    if category_id:
        query = query.where(Transaction.category_id == category_id)
    if search:
        query = query.where(
            Transaction.normalized_merchant.ilike(f"%{search.lower()}%")
            | Transaction.original_description.ilike(f"%{search}%")
        )
    if min_amount is not None:
        query = query.where(Transaction.amount >= min_amount)
    if max_amount is not None:
        query = query.where(Transaction.amount <= max_amount)
    if reviewed is not None:
        query = query.where(Transaction.reviewed.is_(reviewed))
    return (
        await db.scalars(
            query.order_by(
                Transaction.posted_date.desc(), Transaction.created_at.desc()
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()


@router.post("", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    payload: TransactionCreate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    account = await db.scalar(
        select(Account).where(
            Account.id == payload.account_id,
            Account.household_id == auth.household_id,
            Account.is_hidden.is_(False),
        )
    )
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    if payload.category_id:
        category_exists = await db.scalar(
            select(Category.id).where(
                Category.id == payload.category_id,
                Category.household_id == auth.household_id,
            )
        )
        if not category_exists:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    transaction = Transaction(
        household_id=auth.household_id,
        account_id=account.id,
        category_id=payload.category_id,
        merchant_name=payload.merchant_name,
        original_description=payload.merchant_name,
        normalized_merchant=payload.merchant_name.lower(),
        amount=payload.amount,
        posted_date=payload.posted_date,
        notes=payload.notes,
        reviewed=payload.reviewed,
        categorization_source="manual",
    )
    requested_tag_ids = set(payload.tag_ids)
    transaction.tags = (
        (
            await db.scalars(
                select(Tag).where(
                    Tag.household_id == auth.household_id,
                    Tag.id.in_(requested_tag_ids),
                )
            )
        ).all()
        if requested_tag_ids
        else []
    )
    if len(transaction.tags) != len(requested_tag_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid tag")
    db.add(transaction)
    await db.flush()
    await record_security_event(
        db,
        "finance.transaction_created",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"transaction_id": transaction.id, "manual": True},
    )
    await db.commit()
    created = await db.scalar(
        select(Transaction)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Transaction.tags),
            selectinload(Transaction.splits).selectinload(Transaction.tags),
        )
        .where(Transaction.id == transaction.id)
    )
    if created is None:  # pragma: no cover - commit/readback invariant
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Transaction readback failed",
        )
    return created


def _review_needs_a_category(
    is_transfer: bool, excluded_from_budget: bool, is_split: bool = False
) -> bool:
    """
    Whether a row must carry a category before anybody can mark it reviewed.

    The rule exists so a spending transaction is not waved through
    uncategorised. A transfer has no category *by design* and an excluded row
    is outside every budget, so demanding one leaves them permanently stuck:
    eighteen of Alex's card payments sat in "needs review" reading
    "Uncategorized · not counted" with nothing a person could press to clear
    them. That is what "the transactions I review do not save" was — they never
    saved at all.

    **A split parent is the third case, and it took until 1.69.0 to notice.**
    Its category is None on purpose — the lines carry the categories, and
    `countable()` keeps the parent out of every total. So a five-way Venmo
    split could never be marked reviewed, and any save that carried
    `reviewed: true` was refused with a message about categories. Found while
    fixing something else entirely, which is the usual way.

    One predicate, because both `PATCH /transactions/{id}` and this router's
    `POST /transactions/review` decide it. When they disagreed, the tick
    refused and "approve all" silently skipped, which looks identical to a
    review that did not persist.
    """
    return not is_transfer and not excluded_from_budget and not is_split


@router.post("/review", response_model=BulkReviewResponse)
async def bulk_review(
    payload: BulkReviewRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a set of transactions reviewed in one step. Review is an
    organizational judgement, not a financial mutation, so it is open to
    members but still never to viewers.
    """
    _require_editor(auth)
    pending = select(Transaction).where(
        Transaction.household_id == auth.household_id,
        Transaction.reviewed.is_(False),
    )
    if payload.transaction_ids is not None:
        pending = pending.where(Transaction.id.in_(payload.transaction_ids))
    requested = (await db.scalars(pending)).all()
    approving = [
        item
        for item in requested
        if item.category_id is not None
        or not _review_needs_a_category(
            item.is_transfer, item.excluded_from_budget, item.is_split
        )
    ]

    for transaction in approving:
        transaction.reviewed = True
        # Approving a suggestion is a person agreeing with it, which is the
        # same signal as choosing it by hand. Remembering it here is what stops
        # the identical question being asked again next month.
        if transaction.category_id is not None:
            await memory.remember(db, auth.household_id, transaction)
    await record_security_event(
        db,
        "finance.transactions_reviewed",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "reviewed": len(approving),
            "skipped": len(requested) - len(approving),
        },
    )
    await db.commit()
    return BulkReviewResponse(
        reviewed=len(approving),
        skipped_uncategorized=len(requested) - len(approving),
    )


@router.post("/bulk", response_model=BulkTransactionActionResponse)
async def bulk_action(
    payload: BulkTransactionActionRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Apply one explicit, bounded action to household-scoped transactions."""
    _require_editor(auth)
    requested_ids = set(payload.transaction_ids)
    transactions = (
        await db.scalars(
            select(Transaction).where(
                Transaction.household_id == auth.household_id,
                Transaction.id.in_(requested_ids),
            )
        )
    ).all()
    if len(transactions) != len(requested_ids):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "One or more transactions were not found"
        )

    if payload.action == "categorize":
        if payload.category_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Choose a category for bulk categorization",
            )
        category_exists = await db.scalar(
            select(Category.id).where(
                Category.id == payload.category_id,
                Category.household_id == auth.household_id,
            )
        )
        if not category_exists:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
        split_parents = [item for item in transactions if item.is_split]
        if split_parents:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{len(split_parents)} of these are split across categories. "
                "Edit the split to change how they are categorized.",
            )
        for transaction in transactions:
            transaction.category_id = payload.category_id
            transaction.categorization_source = "manual"
            await memory.remember(db, auth.household_id, transaction)
    else:
        excluded = payload.action == "exclude"
        for transaction in transactions:
            transaction.excluded_from_budget = excluded

    await record_security_event(
        db,
        "finance.transactions_bulk_updated",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"action": payload.action, "transactions": len(transactions)},
    )
    await db.commit()
    return BulkTransactionActionResponse(updated=len(transactions))


@router.post("/ai-review", response_model=AiReviewResponse, status_code=202)
async def ai_review(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Queue local-AI category suggestions for uncategorized transactions."""
    _require_editor(auth)
    if not ai_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No local AI endpoint is configured. Set LLM_BASE_URL on the "
            "backend and worker.",
        )
    candidates = (
        await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.household_id == auth.household_id,
                Transaction.reviewed.is_(False),
                unreviewed_guess(),
            )
        )
    ) or 0
    if candidates:
        # Publish immediately so the UI has something to show before the
        # worker picks the job up.
        await write_progress(
            auth.household_id,
            state="queued",
            total=candidates,
            processed=0,
            suggested=0,
            abstained=0,
            invalid=0,
            remaining=candidates,
            failed_batches=0,
            started_at=int(time.time()),
            updated_at=int(time.time()),
            error="",
        )
        await enqueue_job("ai_review_household", str(auth.household_id))
    await record_security_event(
        db,
        "automation.ai_review_queued",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"transactions": candidates},
    )
    await db.commit()
    return AiReviewResponse(queued=candidates)


@router.get("/ai-review/progress", response_model=AiProgressResponse)
async def ai_review_progress(auth: AuthContext = Depends(current_auth)):
    """Progress of the household's running AI categorization, if any."""
    raw = await read_progress(auth.household_id)

    def number(field: str) -> int:
        try:
            return int(raw.get(field) or 0)
        except (TypeError, ValueError):
            return 0

    return AiProgressResponse(
        state=raw.get("state") or "idle",
        total=number("total"),
        processed=number("processed"),
        suggested=number("suggested"),
        abstained=number("abstained"),
        invalid=number("invalid"),
        remaining=number("remaining"),
        failed_batches=number("failed_batches"),
        merchants=number("merchants"),
        merchants_done=number("merchants_done"),
        updated_at=number("updated_at"),
        started_at=number("started_at"),
        error=raw.get("error") or None,
    )


@router.patch("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: uuid.UUID,
    payload: TransactionUpdate,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    transaction = await db.scalar(
        select(Transaction)
        .options(
            selectinload(Transaction.tags),
            selectinload(Transaction.splits).selectinload(Transaction.tags),
        )
        .where(
            Transaction.id == transaction_id,
            Transaction.household_id == auth.household_id,
        )
    )
    if not transaction:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    # **Refuse a category *change*, not every save.** The edit dialog sends
    # `category_id` on every submit, so testing for its presence made a split
    # parent unsavable in every respect: Alex set "count in a different budget
    # month" on a split Venmo charge and got this refusal about categories,
    # which is not what he had touched. A split parent's category is already
    # None, so an unchanged field now passes through.
    if (
        transaction.is_split
        and "category_id" in payload.model_fields_set
        and payload.category_id != transaction.category_id
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This transaction is split across categories. Edit the split "
            "instead, or remove it to categorize the charge as one amount.",
        )
    if (
        transaction.is_split or transaction.is_split_line
    ) and "amount" in payload.model_fields_set:
        # Either direction would leave the lines no longer summing to the
        # charge, which is the one thing a split must always guarantee.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Amounts inside a split are changed by editing the split, so the "
            "lines always add up to the original transaction.",
        )
    # Plaid owns which account a charge belongs to, what it was called, and when
    # it happened. It does *not* get the last word on the amount: its sign is
    # not always what a household means, and a card payment, refund, or transfer
    # can arrive pointing the wrong way. Refusing the edit left no way at all to
    # fix it, so the amount is correctable and the correction is remembered.
    provider_owned = {"account_id", "merchant_name", "posted_date"}
    if (
        provider_owned.intersection(payload.model_fields_set)
        and not transaction.is_manual
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Plaid manages the account, merchant, and date for this transaction",
        )
    if "account_id" in payload.model_fields_set:
        account = await db.scalar(
            select(Account).where(
                Account.id == payload.account_id,
                Account.household_id == auth.household_id,
                Account.is_hidden.is_(False),
            )
        )
        if not account:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
        transaction.account_id = account.id
    if "category_id" in payload.model_fields_set and payload.category_id:
        category_exists = await db.scalar(
            select(Category.id).where(
                Category.id == payload.category_id,
                Category.household_id == auth.household_id,
            )
        )
        if not category_exists:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    effective_category = (
        payload.category_id
        if "category_id" in payload.model_fields_set
        else transaction.category_id
    )
    excluded = (
        payload.excluded_from_budget
        if "excluded_from_budget" in payload.model_fields_set
        else transaction.excluded_from_budget
    )
    if (
        payload.reviewed is True
        and effective_category is None
        and _review_needs_a_category(
            transaction.is_transfer, excluded, transaction.is_split
        )
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose a category before marking this transaction reviewed",
        )
    if "amount" in payload.model_fields_set and not transaction.is_manual:
        # Remember that a person decided, so the next sync stops arguing.
        transaction.amount_overridden = True
    for field in ("merchant_name", "amount", "posted_date"):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            if value is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"{field} cannot be null",
                )
            setattr(transaction, field, value)
    if "merchant_name" in payload.model_fields_set:
        transaction.original_description = payload.merchant_name
        transaction.normalized_merchant = payload.merchant_name.lower()
    if "budget_month" in payload.model_fields_set:
        # Normalised to the first of the month: it names a month, and storing
        # the 14th would make every comparison depend on which day someone
        # happened to pick.
        transaction.budget_month = (
            payload.budget_month.replace(day=1) if payload.budget_month else None
        )
    for field in (
        "category_id",
        "notes",
        "reviewed",
        "excluded_from_budget",
        "paid_by_user_id",
    ):
        if field in payload.model_fields_set:
            setattr(transaction, field, getattr(payload, field))
    if payload.tag_ids is not None:
        requested_tag_ids = set(payload.tag_ids)
        transaction.tags = (
            await db.scalars(
                select(Tag).where(
                    Tag.household_id == auth.household_id,
                    Tag.id.in_(requested_tag_ids),
                )
            )
        ).all()
        if len(transaction.tags) != len(requested_tag_ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid tag")
    if "category_id" in payload.model_fields_set:
        if payload.category_id is None:
            # Clearing a category is a person saying the remembered answer was
            # wrong. Keeping the memory would immediately reinstate it.
            await memory.forget(
                db, auth.household_id, memory.merchant_key(transaction)
            )
            transaction.categorization_source = None
        else:
            transaction.categorization_source = "manual"
            await memory.remember(db, auth.household_id, transaction)
    await record_security_event(
        db,
        "finance.transaction_updated",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={
            "transaction_id": transaction.id,
            "fields": ",".join(sorted(payload.model_fields_set)),
        },
    )
    await db.commit()
    updated = await db.scalar(
        select(Transaction)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Transaction.tags),
            selectinload(Transaction.splits).selectinload(Transaction.tags),
        )
        .where(Transaction.id == transaction.id)
    )
    if updated is None:  # pragma: no cover - commit/readback invariant
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Transaction readback failed",
        )
    return updated


async def _reload_with_splits(
    db: AsyncSession, transaction_id: uuid.UUID
) -> Transaction:
    """
    Return the parent with tags and lines loaded, ready to serialize.

    `populate_existing` is load-bearing: the parent is already in this
    session's identity map with its `splits` collection loaded from *before*
    the lines were written. Without it SQLAlchemy hands back that stale empty
    collection and the response claims a split with no lines in it.
    """
    return await db.scalar(
        select(Transaction)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Transaction.tags),
            selectinload(Transaction.splits).selectinload(Transaction.tags),
        )
        .where(Transaction.id == transaction_id)
    )


@router.put("/{transaction_id}/split", response_model=TransactionResponse)
async def split_transaction(
    transaction_id: uuid.UUID,
    payload: SplitRequest,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Divide one charge across several categories.

    The whole set of lines is sent every time, so the transaction is never left
    half-split: either the lines reconstruct the parent exactly or nothing is
    written.
    """
    _require_editor(auth)
    try:
        parent = await split_service.load_for_split(
            db, auth.household_id, transaction_id
        )
        await split_service.apply_split(
            db,
            auth.household_id,
            parent,
            [line.model_dump() for line in payload.lines],
        )
    except split_service.SplitError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_404_NOT_FOUND
            if "not found" in str(exc).lower()
            else status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(exc),
        ) from exc
    await record_security_event(
        db,
        "finance.transaction_split",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"transaction_id": transaction_id, "lines": len(payload.lines)},
    )
    await db.commit()
    return await _reload_with_splits(db, transaction_id)


@router.delete("/{transaction_id}/split", response_model=TransactionResponse)
async def unsplit_transaction(
    transaction_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """Fold a split back into a single uncategorized transaction."""
    _require_editor(auth)
    try:
        parent = await split_service.load_for_split(
            db, auth.household_id, transaction_id
        )
        await split_service.clear_split(db, parent)
    except split_service.SplitError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_404_NOT_FOUND
            if "not found" in str(exc).lower()
            else status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(exc),
        ) from exc
    await record_security_event(
        db,
        "finance.transaction_unsplit",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"transaction_id": transaction_id},
    )
    await db.commit()
    return await _reload_with_splits(db, transaction_id)


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: uuid.UUID,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    _require_editor(auth)
    transaction = await db.scalar(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.household_id == auth.household_id,
        )
    )
    if transaction and transaction.is_split_line:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is one line of a split. Remove the split on the original "
            "transaction instead.",
        )
    if not transaction:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    if not transaction.is_manual:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Plaid transactions cannot be deleted; exclude this transaction instead",
        )
    await db.delete(transaction)
    await record_security_event(
        db,
        "finance.transaction_deleted",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"transaction_id": transaction.id},
    )
    await db.commit()


@router.post("/search/interpret")
async def interpret_search(
    payload: dict,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Turn a sentence into transaction filters.

    The model never touches the database: it returns a small JSON object which
    is validated field by field against a closed schema, and anything
    unrecognised is dropped. A hallucinated filter becomes an ignored filter
    rather than a query.
    """
    from datetime import date as _date

    import httpx

    from app.config import get_settings
    from app.services.ai import _complete, ai_configured
    from app.services.search_query import SYSTEM_PROMPT, parse

    question = str(payload.get("query") or "").strip()[:300]
    if not question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to search for")
    if not ai_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No local AI endpoint is configured, so plain-English search is "
            "unavailable. The filters above still work.",
        )
    await enforce_rate_limit(
        "search", str(auth.user.id), limit=60, window_seconds=10 * 60
    )

    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.llm_timeout_seconds)
        ) as client:
            reply = await _complete(
                client,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                # A filter is a handful of keys. Without a cap a reasoning
                # model will happily think for a thousand tokens about
                # "costco".
                max_tokens=220,
                json_mode=True,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The model could not be reached: {exc}"
        ) from exc

    filters = parse(reply, _date.today())
    return {
        "query": question,
        "filters": filters,
        # Told apart deliberately: no filters and no results look identical on
        # screen and mean opposite things.
        "understood": bool(filters),
    }


@router.post("/import/preview")
async def preview_import(
    account_id: uuid.UUID,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Read a CSV and show what would be imported. Writes nothing.

    Separate from the import itself on purpose: a misread column turns rent
    into income, and that has to be somebody's decision rather than a heuristic
    running unattended.
    """
    _require_editor(auth)
    account = await db.get(Account, account_id)
    if account is None or account.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")

    from app.services.csv_import import ImportError_, find_duplicates, parse

    try:
        result = parse(await file.read())
    except ImportError_ as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    duplicates = await find_duplicates(db, account_id, result["rows"])
    for row in result["rows"]:
        row["duplicate"] = row["row"] in duplicates
    result["duplicates"] = len(duplicates)
    return result


@router.post("/import/commit")
async def commit_import(
    payload: ImportCommit,
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Write the rows a person accepted from the preview.

    Takes the rows back rather than re-reading the file, so what is written is
    exactly what was on screen — including any edits and any rows deselected.
    """
    _require_editor(auth)
    account = await db.get(Account, payload.account_id)
    if account is None or account.household_id != auth.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")

    from datetime import date as _date
    from decimal import Decimal as _Decimal

    from app.services.merchants import normalize_merchant

    created = 0
    for row in payload.rows:
        db.add(
            Transaction(
                household_id=auth.household_id,
                account_id=account.id,
                merchant_name=row.merchant[:255],
                original_description=row.merchant[:500],
                normalized_merchant=normalize_merchant(row.merchant),
                amount=_Decimal(str(row.amount)),
                currency=account.currency or "USD",
                posted_date=_date.fromisoformat(row.posted_date),
                pending=False,
                # Imported rows are unreviewed by design: a file somebody
                # exported is not a decision about categories.
                reviewed=False,
            )
        )
        created += 1
    await record_security_event(
        db,
        "finance.transactions_imported",
        request=request,
        household_id=auth.household_id,
        user_id=auth.user.id,
        details={"account_id": account.id, "transactions": created},
    )
    await db.commit()
    return {"imported": created}
