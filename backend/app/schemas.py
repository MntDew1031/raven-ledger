import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    AccountKind,
    AccountType,
    BudgetMode,
    FlexBucket,
    HouseholdRole,
    MemorySource,
    PayCadence,
    ProposalKind,
    ProposalStatus,
    RuleMatchType,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)
    household_name: str | None = Field(default=None, min_length=1, max_length=120)
    invite_token: str | None = Field(default=None, min_length=16, max_length=256)


class RegistrationStatus(BaseModel):
    open: bool
    reason: Literal["bootstrap", "enabled", "closed"]


class InvitePreview(BaseModel):
    household_name: str
    invited_email: EmailStr
    role: HouseholdRole
    expires_at: datetime


class InviteTokenRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=32)


class UserResponse(ApiModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    avatar_url: str | None = None
    theme: Literal["system", "light", "parchment", "dark", "midnight", "aurora"] = (
        "system"
    )
    accent: Literal["obsidian", "green", "orange", "red", "blue", "plum"] = "obsidian"
    density: Literal["comfortable", "compact"] = "comfortable"
    # How buttons are drawn. Separate from `theme` so any treatment works
    # under any colour scheme.
    button_style: Literal["iris", "solid", "flat", "duotone", "restrained"] = "iris"
    start_page: Literal["/", "/accounts", "/transactions", "/budgets", "/reports"] = "/"
    mfa_enabled: bool = False


class SessionResponse(BaseModel):
    user: UserResponse
    household_id: uuid.UUID
    household_name: str
    role: HouseholdRole


class InviteRequest(BaseModel):
    email: EmailStr
    role: HouseholdRole = HouseholdRole.member


class InviteResponse(BaseModel):
    invite_token: str
    expires_at: datetime


class InviteSummary(BaseModel):
    id: uuid.UUID
    invited_email: EmailStr
    role: HouseholdRole
    expires_at: datetime
    created_at: datetime


class OnboardingStep(BaseModel):
    key: Literal["household", "account", "transactions", "budget", "bank", "partner"]
    complete: bool


class OnboardingStatus(BaseModel):
    household_name: str
    role: HouseholdRole
    dismissed: bool
    steps: list[OnboardingStep]


class HouseholdMemberResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str
    role: HouseholdRole
    joined_at: datetime
    avatar_url: str | None = None


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    theme: (
        Literal["system", "light", "parchment", "dark", "midnight", "aurora"] | None
    ) = None
    accent: Literal["obsidian", "green", "orange", "red", "blue", "plum"] | None = None
    density: Literal["comfortable", "compact"] | None = None
    button_style: Literal["iris", "solid", "flat", "duotone", "restrained"] | None = (
        None
    )
    start_page: (
        Literal["/", "/accounts", "/transactions", "/budgets", "/reports"] | None
    ) = None


class ProfileResponse(UserResponse):
    avatar_size: int | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class MfaSetupRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    expires_in_seconds: int


class MfaEnableRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=32)


class MfaEnableResponse(BaseModel):
    recovery_codes: list[str]


class MfaDisableRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=32)


class MfaStatusResponse(BaseModel):
    enabled: bool
    enabled_at: datetime | None = None
    recovery_codes_remaining: int = 0


class SecurityEventResponse(ApiModel):
    id: uuid.UUID
    event_type: str
    success: bool
    ip_address: str | None = None
    user_agent: str | None = None
    details: dict[str, object]
    created_at: datetime


class SessionInfoResponse(BaseModel):
    id: str
    current: bool
    created_at: datetime
    last_seen_at: datetime
    user_agent: str


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    type: AccountType
    kind: AccountKind
    current_balance: Decimal
    is_on_budget: bool = True
    institution_name: str | None = Field(default=None, max_length=255)
    credit_limit: Decimal | None = Field(default=None, ge=0)
    # None means shared, which is right for a joint account.
    owner_user_id: uuid.UUID | None = None
    # APR as a percentage: 6.25 means 6.25%. None means do not model interest,
    # which is the default — a guessed rate gives a confidently wrong balance.
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    minimum_payment: Decimal | None = Field(default=None, ge=0)
    # Day of the month a card's statement closes, 1-31. None leaves the card
    # out of the budget's obligations panel rather than guessing at it.
    statement_day: int | None = Field(default=None, ge=1, le=31)
    # What the account held before the first recorded transaction.
    opening_balance: Decimal | None = None


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    type: AccountType | None = None
    kind: AccountKind | None = None
    current_balance: Decimal | None = None
    is_on_budget: bool | None = None
    institution_name: str | None = Field(default=None, max_length=255)
    credit_limit: Decimal | None = Field(default=None, ge=0)
    owner_user_id: uuid.UUID | None = None
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    minimum_payment: Decimal | None = Field(default=None, ge=0)
    # Day of the month a card's statement closes, 1-31. None leaves the card
    # out of the budget's obligations panel rather than guessing at it.
    statement_day: int | None = Field(default=None, ge=1, le=31)
    opening_balance: Decimal | None = None


class AccountResponse(ApiModel):
    id: uuid.UUID
    connection_id: uuid.UUID | None
    name: str
    official_name: str | None
    institution_name: str | None
    mask: str | None
    type: AccountType
    subtype: str | None
    kind: AccountKind
    current_balance: Decimal
    available_balance: Decimal | None
    credit_limit: Decimal | None
    currency: str
    is_on_budget: bool
    is_manual: bool
    owner_user_id: uuid.UUID | None = None
    # Resolved from the owner rather than stored, so a rename in the profile
    # page reaches every account at once.
    owner_name: str | None = None
    interest_rate: Decimal | None = None
    minimum_payment: Decimal | None = None
    statement_day: int | None = None
    opening_balance: Decimal | None = None
    payment_category_id: uuid.UUID | None = None
    last_synced_at: datetime | None


class TransactionUpdate(BaseModel):
    # Which month's plan this counts against. Explicit `None` clears it back to
    # "the month it posted in", which is why the endpoint checks
    # `model_fields_set` rather than truthiness.
    budget_month: date | None = None
    account_id: uuid.UUID | None = None
    paid_by_user_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    merchant_name: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = None
    posted_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    reviewed: bool | None = None
    excluded_from_budget: bool | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class TagResponse(ApiModel):
    id: uuid.UUID
    name: str
    color: str


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#d8924d", pattern=r"^#[0-9a-fA-F]{6}$")


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class TransactionCreate(BaseModel):
    account_id: uuid.UUID
    category_id: uuid.UUID | None = None
    merchant_name: str = Field(min_length=1, max_length=255)
    amount: Decimal
    posted_date: date
    notes: str | None = Field(default=None, max_length=4000)
    reviewed: bool = True
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class TransactionResponse(ApiModel):
    id: uuid.UUID
    account_id: uuid.UUID
    category_id: uuid.UUID | None
    merchant_name: str | None
    original_description: str
    amount: Decimal
    posted_date: date
    # Null unless somebody moved it: the month whose plan this counts against.
    budget_month: date | None = None
    pending: bool
    is_manual: bool
    excluded_from_budget: bool
    is_transfer: bool
    notes: str | None
    reviewed: bool
    categorization_source: str | None
    tags: list[TagResponse] = Field(default_factory=list)
    # A split parent is a container, not an amount. Clients must show it as
    # such and must not add it to any total alongside its lines.
    is_split: bool = False
    parent_transaction_id: uuid.UUID | None = None
    splits: list["TransactionSplitLine"] = Field(default_factory=list)


class TransactionSplitLine(ApiModel):
    id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    amount: Decimal
    notes: str | None = None
    excluded_from_budget: bool = False
    tags: list[TagResponse] = Field(default_factory=list)


class SplitLineInput(BaseModel):
    category_id: uuid.UUID | None = None
    amount: Decimal = Field(max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    excluded_from_budget: bool = False
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class SplitRequest(BaseModel):
    # Bounded so a malformed client cannot ask the database to write thousands
    # of rows for one charge; the service enforces the same ceiling.
    lines: list[SplitLineInput] = Field(min_length=2, max_length=40)


class CategoryResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    group_is_income: bool
    name: str
    color: str
    icon: str | None
    flex_bucket: FlexBucket
    excluded_from_budget: bool = False
    # -1 means this category's spending counts against the previous month's
    # plan, which is what rent due on the 1st is.
    budget_month_offset: int = 0


class IncomeSourceBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    amount: Decimal = Decimal("0")
    cadence: PayCadence = PayCadence.monthly
    is_active: bool = True
    # Any one real pay date. With it, "how many cheques does August hold" is
    # arithmetic; without it, only the yearly average can be offered.
    first_paid_on: date | None = None
    notes: str | None = Field(default=None, max_length=400)


class IncomeSourceCreate(IncomeSourceBase):
    pass


class IncomeSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    amount: Decimal | None = None
    cadence: PayCadence | None = None
    is_active: bool | None = None
    first_paid_on: date | None = None
    notes: str | None = Field(default=None, max_length=400)


class IncomeSourceResponse(IncomeSourceBase):
    id: uuid.UUID
    # Computed, never stored: bi-weekly pay is amount * 26 / 12, not amount * 2,
    # and storing a derived figure invites the two to disagree.
    monthly_equivalent: Decimal
    cadence_label: str
    extra_paycheque_months: int


class IncomeSummary(BaseModel):
    sources: list[IncomeSourceResponse]
    monthly_total: Decimal


class AiConfigUpdate(BaseModel):
    model: str | None = Field(default=None, min_length=1, max_length=200)
    # Two is right for a 3B and forty for a large one; the ceiling stops a
    # typo turning one batch into the whole backlog.
    min_batch_size: int | None = Field(default=None, ge=1, le=40)


class ImportRow(BaseModel):
    posted_date: str
    amount: Decimal
    merchant: str = Field(min_length=1, max_length=255)


class ImportCommit(BaseModel):
    account_id: uuid.UUID
    rows: list[ImportRow] = Field(min_length=1, max_length=5000)


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: Decimal = Field(gt=0)
    target_date: date | None = None
    account_id: uuid.UUID | None = None
    saved_amount: Decimal = Decimal("0")
    notes: str | None = Field(default=None, max_length=400)


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: Decimal | None = Field(default=None, gt=0)
    target_date: date | None = None
    account_id: uuid.UUID | None = None
    saved_amount: Decimal | None = None
    notes: str | None = Field(default=None, max_length=400)
    is_achieved: bool | None = None


class GoalResponse(BaseModel):
    id: uuid.UUID
    name: str
    target_amount: Decimal
    target_date: date | None
    account_id: uuid.UUID | None
    saved_amount: Decimal
    remaining: Decimal
    progress_percent: float
    months_left: int | None
    # Rounded up: a figure that is arithmetically right and still misses the
    # target is the one thing a savings plan cannot do.
    monthly_needed: Decimal | None
    overdue: bool
    is_achieved: bool
    notes: str | None


class ThreadSummary(BaseModel):
    id: uuid.UUID
    title: str
    last_message_at: datetime
    created_at: datetime
    message_count: int


class ThreadMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class ThreadDetail(BaseModel):
    id: uuid.UUID
    title: str
    messages: list[ThreadMessage]


class ThreadRename(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    # Absent starts a new conversation, titled from the question.
    thread_id: uuid.UUID | None = None


# Named for the assistant deliberately: the organizer already has a
# `ProposalResponse` with an entirely different shape, and the second
# definition in a module silently wins — which is how this first showed
# up, as the organizer's enum rejecting the word 'categorize'.
class AssistantProposalResponse(BaseModel):
    id: uuid.UUID
    kind: str
    summary: str
    status: str
    # How many rows this would touch, recomputed when it is shown. None for
    # kinds where the question does not apply, such as creating a rule.
    affected: int | None = None
    examples: list[dict] = []
    result: dict | None = None
    created_at: datetime


class ChatReply(BaseModel):
    thread_id: uuid.UUID
    title: str
    reply: str
    # A memory the assistant would like to keep. Nothing is stored until it is
    # confirmed, so this is a suggestion on screen and nothing more.
    suggested_memory: str | None = None
    # A change it would like to make. Same principle: stored as pending, and
    # nothing touches the ledger until somebody presses approve.
    proposal: AssistantProposalResponse | None = None


class MemoryResponse(BaseModel):
    id: uuid.UUID
    fact: str
    source: MemorySource
    is_active: bool
    confirmed_at: datetime | None
    created_at: datetime


class MemoryCreate(BaseModel):
    fact: str = Field(min_length=1, max_length=400)


class MemoryUpdate(BaseModel):
    fact: str | None = Field(default=None, min_length=1, max_length=400)
    is_active: bool | None = None
    confirmed: bool | None = None


class ProposalResponse(BaseModel):
    id: uuid.UUID
    kind: ProposalKind
    status: ProposalStatus
    payload: dict
    rationale: str
    confidence: Decimal
    created_at: datetime


class ProposalEdit(BaseModel):
    """
    Change a proposal before accepting it.

    The whole payload is replaced, so approving always applies exactly what was
    last on screen rather than a mix of proposed and edited values.
    """

    payload: dict


class ProposalDecision(BaseModel):
    proposal_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class OrganizerRunResult(BaseModel):
    duplicate: int = 0
    transfer: int = 0
    exclusion: int = 0
    category: int = 0
    rule: int = 0
    budget: int = 0


class CategoryGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_income: bool = False


class CategoryGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_income: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)


class CategoryGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_income: bool
    sort_order: int
    category_count: int


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    group_id: uuid.UUID
    color: str = Field(default="#7f8b81", pattern=r"^#[0-9a-fA-F]{6}$")
    flex_bucket: FlexBucket = FlexBucket.flex


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    group_id: uuid.UUID | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    flex_bucket: FlexBucket | None = None
    is_archived: bool | None = None
    excluded_from_budget: bool | None = None
    budget_month_offset: int | None = Field(default=None, ge=-1, le=1)


class BudgetLineInput(BaseModel):
    category_id: uuid.UUID
    planned_amount: Decimal = Decimal("0")
    rollover_enabled: bool = False
    non_monthly_target: Decimal | None = None
    non_monthly_due_date: date | None = None


class BudgetUpsert(BaseModel):
    month: date
    mode: BudgetMode
    expected_income: Decimal = Decimal("0")
    flex_amount: Decimal = Decimal("0")
    # None means "work it out from the pay dates"; True and False are a person
    # overriding that for this month alone.
    extra_paycheque: bool | None = None
    lines: list[BudgetLineInput] = Field(max_length=500)


class PlaidPublicTokenRequest(BaseModel):
    public_token: str = Field(min_length=1, max_length=4096)
    institution_name: str | None = Field(default=None, max_length=255)


class PlaidConnectionResponse(BaseModel):
    id: uuid.UUID
    institution_name: str
    status: str
    account_count: int
    last_synced_at: datetime | None
    error_code: str | None
    # A queued sync that never landed. Computed server-side so the browser's
    # clock cannot disagree about it.
    sync_stale: bool


class PlaidStatusResponse(BaseModel):
    configured: bool
    environment: str
    webhook_configured: bool
    redirect_uri_configured: bool
    connections_in_use: int = 0
    # None means no limit is configured — not that there is no limit. Plaid's
    # tiers change, so the number comes from the deployment rather than a
    # guess baked in here.
    connection_limit: int | None = None
    connections_remaining: int | None = None


class RecurringItemResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    direction: Literal["inflow", "outflow"]
    cadence: str
    average_amount: Decimal
    last_amount: Decimal
    occurrences: int
    last_seen: date
    next_due: date
    category_id: uuid.UUID | None
    category_name: str | None
    account_name: str | None
    is_active: bool


class RecurringItemUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: uuid.UUID | None = None
    is_active: bool | None = None


class RecurringDetectResponse(BaseModel):
    queued: bool


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    match_type: RuleMatchType
    merchant_pattern: str = Field(min_length=1, max_length=255)
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    category_id: uuid.UUID
    priority: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    match_type: RuleMatchType | None = None
    merchant_pattern: str | None = Field(default=None, min_length=1, max_length=255)
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    category_id: uuid.UUID | None = None
    priority: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None


class RuleResponse(BaseModel):
    id: uuid.UUID
    name: str
    match_type: RuleMatchType
    merchant_pattern: str
    min_amount: Decimal | None
    max_amount: Decimal | None
    category_id: uuid.UUID
    category_name: str
    priority: int
    is_active: bool


class RulePreviewRequest(BaseModel):
    match_type: RuleMatchType
    merchant_pattern: str = Field(min_length=1, max_length=255)
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)


class RulePreviewSample(BaseModel):
    merchant: str
    amount: Decimal
    posted_date: date


class RulePreviewResponse(BaseModel):
    scanned: int
    matched: int
    uncategorized_matched: int
    samples: list[RulePreviewSample]


class RuleRunResponse(BaseModel):
    queued: int


class BulkReviewRequest(BaseModel):
    # None marks every unreviewed transaction in the household.
    transaction_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class BulkReviewResponse(BaseModel):
    reviewed: int
    skipped_uncategorized: int = 0


class BulkTransactionActionRequest(BaseModel):
    transaction_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["categorize", "exclude", "include"]
    category_id: uuid.UUID | None = None


class BulkTransactionActionResponse(BaseModel):
    updated: int


class AiProgressResponse(BaseModel):
    state: Literal["idle", "queued", "running", "done", "failed"]
    total: int = 0
    processed: int = 0
    suggested: int = 0
    abstained: int = 0
    invalid: int = 0
    remaining: int = 0
    failed_batches: int = 0
    merchants: int = 0
    merchants_done: int = 0
    updated_at: int = 0
    started_at: int = 0
    error: str | None = None


class AiReviewResponse(BaseModel):
    queued: int


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AssistantRequest(BaseModel):
    messages: list[AssistantMessage] = Field(min_length=1, max_length=12)


class AssistantResponse(BaseModel):
    reply: str


class AiModelsResponse(BaseModel):
    ok: bool
    models: list[str] = []
    error: str | None = None


class AiStatusResponse(BaseModel):
    configured: bool
    model: str | None = None
    probe_ok: bool | None = None
    probe_latency_ms: int | None = None
    probe_error: str | None = None


class WorkerStatusResponse(BaseModel):
    online: bool
    last_seen_at: datetime | None
    queued_jobs: int
    heartbeat_ttl_seconds: int
    ai_configured: bool | None = None
    ai_model: str | None = None
    ai_config_matches_backend: bool | None = None
    ai_endpoint_matches_backend: bool | None = None
    ai_model_matches_backend: bool | None = None
    web_backups_enabled: bool = False


class OperatorConfirmRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=32)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # Read is the default on purpose: a tool that only answers questions should
    # not be able to change anything by accident of configuration.
    can_write: bool = False


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    can_write: bool
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class ApiKeyCreated(ApiKeyResponse):
    # Returned exactly once, at creation. Never stored in a recoverable form.
    secret: str


class LedgerResponse(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    is_sandbox: bool
    cloned_from_id: uuid.UUID | None = None
    cloned_at: datetime | None = None


class SandboxCreate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class SandboxRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class LedgerSwitch(BaseModel):
    household_id: uuid.UUID


class BackupSummary(BaseModel):
    name: str
    created_at: str
    bytes: int
    sha256: str = ""
    app_version: str | None = None
    encryption_fingerprint: str | None = None
    row_counts: dict[str, int] | None = None
    verified_at: str | None = None
    verify_ok: bool | None = None
    verify_error: str | None = None


class BackupListResponse(BaseModel):
    backups: list[BackupSummary] = []
    keep: int
    directory: str
    # Present state of the key that encrypts provider tokens. A backup whose
    # fingerprint differs was taken under a different key and will not decrypt.
    encryption_fingerprint: str
    writable: bool
    error: str | None = None


class BackupVerifyResponse(BaseModel):
    ok: bool
    error: str | None = None
    duration_ms: int | None = None
    encryption_key_matches: bool | None = None
    expected_counts: dict[str, int] = {}
    restored_counts: dict[str, int] = {}
    shortfalls: dict[str, dict[str, int]] = {}


class DashboardSummary(BaseModel):
    assets: Decimal
    liabilities: Decimal
    net_worth: Decimal
    month_income: Decimal
    month_spending: Decimal
    savings_rate: Decimal
    reserved: Decimal
    needs_review: int = 0
