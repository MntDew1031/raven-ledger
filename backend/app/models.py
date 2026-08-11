import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HouseholdRole(str, enum.Enum):
    owner = "owner"
    member = "member"
    viewer = "viewer"


class AccountKind(str, enum.Enum):
    asset = "asset"
    liability = "liability"


class AccountType(str, enum.Enum):
    checking = "checking"
    savings = "savings"
    credit = "credit"
    investment = "investment"
    # Told apart from a plain brokerage on purpose: the tax treatment differs,
    # and so does what the money can be used for before retirement.
    retirement = "retirement"
    brokerage = "brokerage"
    mortgage = "mortgage"
    loan = "loan"
    debt = "debt"
    cash = "cash"
    other = "other"


class BudgetMode(str, enum.Enum):
    category = "category"
    flex = "flex"


class FlexBucket(str, enum.Enum):
    fixed = "fixed"
    flex = "flex"
    non_monthly = "non_monthly"
    goal = "goal"


class RuleMatchType(str, enum.Enum):
    contains = "contains"
    exact = "exact"
    regex = "regex"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mfa_recovery_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    memberships: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
        uselist=False,
    )


class UserProfile(TimestampMixin, Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "theme IN ('system', 'light', 'parchment', 'dark', 'midnight', 'aurora')",
            name="user_profile_theme",
        ),
        CheckConstraint(
            "accent IN ('obsidian', 'green', 'orange', 'red', 'blue', 'plum')",
            name="user_profile_accent",
        ),
        CheckConstraint(
            "density IN ('comfortable', 'compact')",
            name="user_profile_density",
        ),
        CheckConstraint(
            "button_style IN ('iris', 'solid', 'flat', 'duotone', 'restrained')",
            name="user_profile_button_style",
        ),
        CheckConstraint(
            "start_page IN ('/', '/accounts', '/transactions', '/budgets', '/reports')",
            name="user_profile_start_page",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(String(16), default="system")
    accent: Mapped[str] = mapped_column(String(16), default="obsidian")
    density: Mapped[str] = mapped_column(String(16), default="comfortable")
    # How buttons are drawn — a separate axis from `theme`, so any treatment
    # works under any colour scheme.
    button_style: Mapped[str] = mapped_column(String(16), default="iris")
    start_page: Mapped[str] = mapped_column(String(32), default="/")
    avatar_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    avatar_mime: Mapped[str | None] = mapped_column(String(40))
    avatar_revision: Mapped[str | None] = mapped_column(String(36))
    avatar_size: Mapped[int | None] = mapped_column(Integer)
    onboarding_dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Household(TimestampMixin, Base):
    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(CHAR(3), default="USD")
    timezone: Mapped[str] = mapped_column(String(64), default="America/Phoenix")
    # A sandbox is a disposable copy of a real ledger. It never holds bank
    # credentials, so it can be destroyed without consequence.
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False)
    cloned_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("households.id", ondelete="SET NULL")
    )
    cloned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = (
        UniqueConstraint("household_id", "user_id"),
        Index("ix_household_members_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    role: Mapped[HouseholdRole] = mapped_column(
        Enum(HouseholdRole, name="household_role"), default=HouseholdRole.member
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    household: Mapped[Household] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class HouseholdInvite(TimestampMixin, Base):
    __tablename__ = "household_invites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    invited_email: Mapped[str] = mapped_column(String(320))
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    role: Mapped[HouseholdRole] = mapped_column(
        Enum(HouseholdRole, name="household_role"),
        default=HouseholdRole.member,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InstitutionConnection(TimestampMixin, Base):
    __tablename__ = "institution_connections"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "household_id",
            name="uq_institution_connections_id_household",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(30), default="plaid")
    provider_item_id: Mapped[str] = mapped_column(String(255), unique=True)
    institution_id: Mapped[str | None] = mapped_column(String(255))
    institution_name: Mapped[str | None] = mapped_column(String(255))
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    # Who linked this. Stamped onto the accounts it creates, which is the only
    # dependable way to tell two people's identical cards apart — Plaid's own
    # holder name is the bank's formatting of a joint title as often as not.
    linked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cursor: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="healthy")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(120))


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "provider_account_id",
            name="uq_accounts_household_provider",
        ),
        UniqueConstraint("id", "household_id", name="uq_accounts_id_household"),
        ForeignKeyConstraint(
            ["connection_id", "household_id"],
            ["institution_connections.id", "institution_connections.household_id"],
            name="fk_accounts_connection_household",
        ),
        ForeignKeyConstraint(
            ["payment_category_id", "household_id"],
            ["categories.id", "categories.household_id"],
            name="fk_accounts_payment_category_household",
        ),
        CheckConstraint("current_balance IS NOT NULL", name="account_has_balance"),
        Index("ix_accounts_household", "household_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("institution_connections.id", ondelete="SET NULL")
    )
    provider_account_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(160))
    official_name: Mapped[str | None] = mapped_column(String(255))
    institution_name: Mapped[str | None] = mapped_column(String(255))
    mask: Mapped[str | None] = mapped_column(String(8))
    type: Mapped[AccountType] = mapped_column(Enum(AccountType, name="account_type"))
    subtype: Mapped[str | None] = mapped_column(String(80))
    kind: Mapped[AccountKind] = mapped_column(Enum(AccountKind, name="account_kind"))
    is_on_budget: Mapped[bool] = mapped_column(Boolean, default=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whose account this is. NULL means shared, which is the right default —
    # a joint checking account belongs to the household rather than to
    # whoever happened to open it.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Annual percentage rate as a percentage: 6.25 means 6.25%. None means
    # "do not model interest", and that stays the default — a guessed rate is
    # worse than no rate, because it produces a confident wrong balance.
    # What the account held before the first recorded transaction. NULL means
    # "not established", which is not the same as zero — zero is a claim that
    # the account was empty, and most were not. Without it, reconciliation has
    # no right answer to compare against.
    opening_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    minimum_payment: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    # Payments to this debt land here. Created alongside the account so a new
    # loan is budgetable immediately.
    payment_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    # So a monthly accrual runs once a month however often the job fires.
    interest_applied_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    available_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # Day of the month this card's statement closes. A card closing on the 8th
    # bills July's spending in August, and that payment leaves the account in
    # August whatever month the budget thinks the spending belonged to. NULL
    # means the card is left out of the obligations panel rather than guessed
    # at — a wrong due date is worse than an absent one.
    statement_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), default="USD")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Eager by design. Every screen that lists accounts wants the owner's name
    # to disambiguate — the household holds two Chase Prime cards and two
    # Discover it cards between two people — and a lazy load here would be an
    # IO call inside serialization, which async SQLAlchemy refuses outright.
    owner: Mapped["User | None"] = relationship(
        lazy="selectin", foreign_keys=[owner_user_id]
    )

    @property
    def owner_name(self) -> str | None:
        """
        Whose account this is, for display. None means shared.

        A property rather than a stored string: renaming yourself in the
        profile page should rename you everywhere, not leave a stale copy on
        every account you linked.
        """
        return self.owner.display_name if self.owner else None


class CategoryGroup(TimestampMixin, Base):
    __tablename__ = "category_groups"
    __table_args__ = (
        UniqueConstraint("household_id", "name"),
        UniqueConstraint("id", "household_id", name="uq_category_groups_id_household"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_income: Mapped[bool] = mapped_column(Boolean, default=False)


class AppSetting(TimestampMixin, Base):
    """
    One install-wide setting, changeable without a redeploy.

    Install-wide rather than per household: there is one AI endpoint, and a
    sandbox is a household. Writes are operator-gated, the same authority that
    gates backups.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ActivityLog(TimestampMixin, Base):
    """
    One reversible action.

    The organizer can apply thirty changes in a tap; bulk edits and rule runs
    touch as many. Without a way back, the safe move is to hesitate — which is
    the friction those features exist to remove.

    `changes` carries the value each field held *before*, written at the time,
    because after the fact it cannot be worked out.
    """

    __tablename__ = "activity_log"
    __table_args__ = (
        Index("activity_log_recent_idx", "household_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(String(300))
    changes: Mapped[list] = mapped_column(JSONB)
    undone_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SecurityEvent(Base):
    """Append-oriented authentication and sensitive-action evidence."""

    __tablename__ = "security_events"
    __table_args__ = (
        Index(
            "security_events_household_recent",
            "household_id",
            text("created_at DESC"),
        ),
        Index("security_events_user_recent", "user_id", text("created_at DESC")),
        Index("ix_security_events_event_type", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("households.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(80))
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(240), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Goal(TimestampMixin, Base):
    """
    Something being saved for, tracked across months.

    `budget_lines.non_monthly_target` could say "put aside $300 in August" but
    not "reach $12,000 by June 2027" — a goal outlives the month it is planned
    in, which is why it needs a row of its own.
    """

    __tablename__ = "goals"
    __table_args__ = (
        UniqueConstraint("household_id", "name"),
        ForeignKeyConstraint(
            ["account_id", "household_id"],
            ["accounts.id", "accounts.household_id"],
            name="fk_goals_account_household",
        ),
        Index("goals_household_idx", "household_id", "is_achieved"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Optional: most goals start being tracked before they have an account.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    # Only consulted when no account is linked. With one, the balance is the
    # truth — two sources of the same number will disagree eventually.
    saved_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    notes: Mapped[str | None] = mapped_column(String(400), nullable=True)
    is_achieved: Mapped[bool] = mapped_column(Boolean, default=False)


class MemorySource(str, enum.Enum):
    person = "person"
    assistant = "assistant"
    derived = "derived"


class AssistantThread(TimestampMixin, Base):
    """One conversation, kept so it can be returned to."""

    __tablename__ = "assistant_threads"
    __table_args__ = (
        Index(
            "assistant_threads_recent_idx",
            "user_id",
            text("last_message_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    # A household shares a ledger but not its half-finished questions about
    # money, so threads belong to a person rather than to the household.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(160), default="New conversation")
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AssistantMessage(TimestampMixin, Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (
        Index("assistant_messages_thread_idx", "thread_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assistant_threads.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)


class AssistantMemory(TimestampMixin, Base):
    """
    Something Raven should carry into every conversation.

    Deliberately one short sentence each: a memory that needs a paragraph is a
    note, and a wall of paragraphs cannot be skimmed to find the one that has
    stopped being true.
    """

    __tablename__ = "assistant_memories"
    __table_args__ = (
        Index("assistant_memories_household_idx", "household_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    fact: Mapped[str] = mapped_column(String(400))
    source: Mapped[MemorySource] = mapped_column(
        Enum(MemorySource, name="memory_source"), default=MemorySource.person
    )
    # Off rather than deleted, so something that stops being true this year can
    # be switched back on next year.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Raven proposes; a person confirms. Unconfirmed memories never reach the
    # model's context — same rule as the organizer.
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ProposalKind(str, enum.Enum):
    category = "category"
    duplicate = "duplicate"
    transfer = "transfer"
    exclusion = "exclusion"
    rule = "rule"
    budget = "budget"


class ProposalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    # The data moved on before a decision was made. Never applied.
    stale = "stale"


class AiProposal(TimestampMixin, Base):
    """
    A change the AI would like to make, which nobody has agreed to yet.

    The AI already writes category guesses straight onto transactions, and that
    is fine: a guess is visibly unreviewed and one tap to correct. It does not
    extend to writing rules or budget amounts, which are decisions with
    consequences — so those are proposed, shown with a reason, and applied only
    when somebody says so.
    """

    __tablename__ = "ai_proposals"
    __table_args__ = (
        Index("ai_proposals_pending_idx", "household_id", "status", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    kind: Mapped[ProposalKind] = mapped_column(Enum(ProposalKind, name="proposal_kind"))
    status: Mapped[ProposalStatus] = mapped_column(
        Enum(ProposalStatus, name="proposal_status"),
        default=ProposalStatus.pending,
    )
    # Edited in place when somebody changes a proposal before accepting it, so
    # approving always applies exactly what was on screen.
    payload: Mapped[dict] = mapped_column(JSONB)
    rationale: Mapped[str] = mapped_column(String(400), default="")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.5"))
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PayCadence(str, enum.Enum):
    weekly = "weekly"
    biweekly = "biweekly"
    semimonthly = "semimonthly"
    monthly = "monthly"
    annual = "annual"


class IncomeSource(TimestampMixin, Base):
    """
    One earner's pay. A household with two incomes needs two of these; the
    single "expected monthly income" field it replaces could not say who was
    paid what, or how often.
    """

    __tablename__ = "income_sources"
    __table_args__ = (
        UniqueConstraint("household_id", "name"),
        Index("income_sources_household_idx", "household_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    # A name, not a user id: an earner does not need an account here for their
    # pay to be worth planning around.
    name: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    cadence: Mapped[PayCadence] = mapped_column(
        Enum(PayCadence, name="pay_cadence"), default=PayCadence.monthly
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Any one real pay date. Everything else about "which months carry a third
    # cheque" follows from it arithmetically, so this is the difference between
    # a monthly average and what actually lands in August. NULL means "we do
    # not know", and the average is all that can honestly be offered.
    first_paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(400), nullable=True)


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("household_id", "name"),
        UniqueConstraint("id", "household_id", name="uq_categories_id_household"),
        ForeignKeyConstraint(
            ["group_id", "household_id"],
            ["category_groups.id", "category_groups.household_id"],
            name="fk_categories_group_household",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("category_groups.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(CHAR(7), default="#7f8b81")
    # Never counts toward budgets or spending totals. Distinct from
    # is_archived, which hides the category; an excluded category stays
    # visible and keeps its transactions, they simply do not count.
    excluded_from_budget: Mapped[bool] = mapped_column(Boolean, default=False)
    # Months to shift this category's spending when the *budget* reads it.
    # -1 = "counts against the previous month's plan": rent due on the 1st is
    # paid from last month's pay. Applied at read time, so changing it fixes
    # the history rather than only what happens next.
    budget_month_offset: Mapped[int] = mapped_column(SmallInteger, default=0)
    icon: Mapped[str | None] = mapped_column(String(40))
    flex_bucket: Mapped[FlexBucket] = mapped_column(
        Enum(FlexBucket, name="flex_bucket"), default=FlexBucket.flex
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)


transaction_tags = Table(
    "transaction_tags",
    Base.metadata,
    Column(
        "transaction_id",
        ForeignKey("transactions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "provider_transaction_id",
            name="uq_transactions_account_provider",
        ),
        UniqueConstraint("id", "household_id", name="uq_transactions_id_household"),
        ForeignKeyConstraint(
            ["account_id", "household_id"],
            ["accounts.id", "accounts.household_id"],
            name="fk_transactions_account_household",
        ),
        ForeignKeyConstraint(
            ["category_id", "household_id"],
            ["categories.id", "categories.household_id"],
            name="fk_transactions_category_household",
        ),
        ForeignKeyConstraint(
            ["parent_transaction_id", "household_id"],
            ["transactions.id", "transactions.household_id"],
            name="fk_transactions_parent_household",
        ),
        Index(
            "ix_transactions_household_date",
            "household_id",
            text("posted_date DESC"),
        ),
        Index("ix_transactions_household_category", "household_id", "category_id"),
        Index(
            "ix_transactions_parent",
            "parent_transaction_id",
            postgresql_where=text("parent_transaction_id IS NOT NULL"),
        ),
        Index("ix_transactions_merchant", "household_id", "normalized_merchant"),
        Index(
            "ix_transactions_budget_month",
            "household_id",
            "budget_month",
            postgresql_where=text("budget_month IS NOT NULL"),
        ),
        Index("transactions_paid_by_idx", "household_id", "paid_by_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE")
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    provider_transaction_id: Mapped[str | None] = mapped_column(String(255))
    pending_provider_transaction_id: Mapped[str | None] = mapped_column(String(255))
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    original_description: Mapped[str] = mapped_column(Text)
    normalized_merchant: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), default="USD")
    posted_date: Mapped[date] = mapped_column(Date)
    # Which month's *plan* this counts against, when that is not the month it
    # posted in. Rent due on the 1st comes out of the previous month's pay, so
    # it belongs to that month's budget while posting in this one.
    #
    # NULL means "the month it posted in", which is almost every row. Read by
    # the budget page and nothing else: `posted_date` above stays the single
    # answer to "when did this happen", because every report is history.
    budget_month: Mapped[date | None] = mapped_column(Date, nullable=True)
    authorized_date: Mapped[date | None] = mapped_column(Date)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_from_budget: Mapped[bool] = mapped_column(Boolean, default=False)
    # Overrides the account's owner for this one transaction: a shared card
    # used for something personal, or the reverse.
    paid_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    categorization_source: Mapped[str | None] = mapped_column(String(40))
    # Plaid's own guess, e.g. "FOOD_AND_DRINK_GROCERIES". Kept verbatim: it is
    # a strong free signal for categorization and a useful hint to the model,
    # but it names Plaid's taxonomy, never a category in this household.
    provider_category: Mapped[str | None] = mapped_column(String(120))
    # A split line points at the bank charge it came from; the charge itself is
    # flagged `is_split`. Exactly one of these is ever set on a given row.
    parent_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE")
    )
    is_split: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set when a person corrects a synced amount. Sync then leaves that one
    # field alone rather than reverting the correction on its next run.
    amount_overridden: Mapped[bool] = mapped_column(Boolean, default=False)

    tags: Mapped[list["Tag"]] = relationship(
        secondary=transaction_tags, back_populates="transactions"
    )
    splits: Mapped[list["Transaction"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys=[parent_transaction_id],
    )
    parent: Mapped["Transaction | None"] = relationship(
        back_populates="splits",
        foreign_keys=[parent_transaction_id],
        remote_side=[id],
    )

    @property
    def is_manual(self) -> bool:
        # A split line has no provider id of its own, but it is not a manual
        # entry — its account, date, and merchant belong to the bank charge
        # above it and must not become editable.
        return self.provider_transaction_id is None and (
            self.parent_transaction_id is None
        )

    @property
    def is_split_line(self) -> bool:
        return self.parent_transaction_id is not None


class Tag(TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("household_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(CHAR(7), default="#d8924d")

    transactions: Mapped[list[Transaction]] = relationship(
        secondary=transaction_tags, back_populates="tags"
    )


class CategorizationRule(TimestampMixin, Base):
    __tablename__ = "categorization_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "household_id"],
            ["categories.id", "categories.household_id"],
            name="fk_rules_category_household",
        ),
        Index("ix_rules_household_priority", "household_id", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    match_type: Mapped[RuleMatchType] = mapped_column(
        Enum(RuleMatchType, name="rule_match_type")
    )
    merchant_pattern: Mapped[str] = mapped_column(String(255))
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    tag_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ApiKey(TimestampMixin, Base):
    """
    A long-lived credential for something that is not a browser.

    Deliberately separate from sessions: a session belongs to a person sitting
    at a screen and expires, while this belongs to a tool and does not. Keeping
    them apart is what lets the sensitive, person-only operations refuse an API
    key outright no matter who created it.
    """

    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_household", "household_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MerchantMemory(TimestampMixin, Base):
    """
    What this household decided a merchant is.

    Written whenever a person categorizes or approves a transaction, and read
    before anything else guesses. It is the difference between a categorizer
    that is asked the same question every month and one that converges: once
    somebody says Trader Joe's is groceries, no rule, model, or keyword table
    ever has to work it out again.

    Distinct from `CategorizationRule`: rules are authored deliberately and are
    visible and editable as rules. This is a by-product of ordinary review,
    invisible until it stops being right, at which point the next correction
    overwrites it.
    """

    __tablename__ = "merchant_memories"
    __table_args__ = (
        UniqueConstraint("household_id", "merchant_key"),
        ForeignKeyConstraint(
            ["category_id", "household_id"],
            ["categories.id", "categories.household_id"],
            name="fk_merchant_memories_category_household",
        ),
        Index("ix_merchant_memories_household", "household_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    merchant_key: Mapped[str] = mapped_column(String(255))
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    # A display sample of the merchant text, so the memory is legible to a
    # person even though matching happens on the normalized key.
    sample_label: Mapped[str | None] = mapped_column(String(255))
    # "human" when a person chose or approved it, "ai" when only a model has.
    # Human memories are never overwritten by a model.
    source: Mapped[str] = mapped_column(String(20), default="human")
    hits: Mapped[int] = mapped_column(Integer, default=0)
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecurringItem(TimestampMixin, Base):
    __tablename__ = "recurring_items"
    __table_args__ = (
        UniqueConstraint("household_id", "merchant_key", "direction"),
        ForeignKeyConstraint(
            ["category_id", "household_id"],
            ["categories.id", "categories.household_id"],
            name="fk_recurring_category_household",
        ),
        ForeignKeyConstraint(
            ["account_id", "household_id"],
            ["accounts.id", "accounts.household_id"],
            name="fk_recurring_account_household",
        ),
        Index("ix_recurring_household", "household_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    merchant_key: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(10), default="outflow")
    cadence: Mapped[str] = mapped_column(String(16))
    average_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    last_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    occurrences: Mapped[int] = mapped_column(Integer)
    last_seen: Mapped[date] = mapped_column(Date)
    next_due: Mapped[date] = mapped_column(Date)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AssistantProposal(TimestampMixin, Base):
    """
    A change the assistant would like to make, which it cannot make itself.

    Alex chose propose → approve → act over both read-only and direct action,
    and the reason this is a table rather than a message is the audit trail: he
    wants to see what was suggested, what he agreed to, and what it actually
    did, after the fact.

    **The payload names intent, never row ids.** A proposal says "everything
    from Chipotle that has no category yet", and the rows are resolved from the
    ledger at approval time. A model that invents a transaction id would
    otherwise be proposing a change to something that does not exist, or worse,
    to something that does and is unrelated. Resolving late also means a
    proposal cannot act on rows that were edited between suggesting and
    approving.
    """

    __tablename__ = "assistant_proposals"
    __table_args__ = (
        Index("assistant_proposals_household_idx", "household_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assistant_threads.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    # The sentence shown to a person. Written by Raven, not by the model, so a
    # proposal cannot describe itself as something other than what it does.
    summary: Mapped[str] = mapped_column(String(400))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # What actually happened, recorded because the count at approval time is
    # frequently not the count at suggestion time.
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Budget(TimestampMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("household_id", "month"),
        CheckConstraint(
            "date_trunc('month', month) = month", name="month_is_first_day"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    month: Mapped[date] = mapped_column(Date)
    mode: Mapped[BudgetMode] = mapped_column(
        Enum(BudgetMode, name="budget_mode"), default=BudgetMode.category
    )
    expected_income: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    flex_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    # Tri-state on purpose. NULL is "work it out from the pay dates", which is
    # right almost always; True and False are a person overriding that for one
    # month, which they need when a cheque lands a day either side of a month
    # boundary and the calendar disagrees with the bank.
    extra_paycheque: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class BudgetLine(TimestampMixin, Base):
    __tablename__ = "budget_lines"
    __table_args__ = (UniqueConstraint("budget_id", "category_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE")
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    rollover_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rollover_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    non_monthly_target: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    non_monthly_due_date: Mapped[date | None] = mapped_column(Date)


class Holding(TimestampMixin, Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("account_id", "security_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE")
    )
    security_id: Mapped[str] = mapped_column(String(255))
    ticker_symbol: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NetWorthSnapshot(Base):
    __tablename__ = "net_worth_snapshots"
    __table_args__ = (UniqueConstraint("household_id", "snapshot_date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    snapshot_date: Mapped[date] = mapped_column(Date)
    assets: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    liabilities: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    net_worth: Mapped[Decimal] = mapped_column(Numeric(18, 2))


class DashboardWidget(TimestampMixin, Base):
    __tablename__ = "dashboard_widgets"
    __table_args__ = (UniqueConstraint("user_id", "household_id", "widget_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE")
    )
    widget_key: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
