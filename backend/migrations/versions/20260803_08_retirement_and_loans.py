"""Retirement accounts, and loans that keep up with themselves.

Two gaps Alex hit at once.

`AccountType` had `investment` but nothing for a 401(k) or a Roth IRA, which
are the accounts most households have the most money in and never look at.
They are worth telling apart from a brokerage: the tax treatment differs and so
does what you can do with the money.

And a manually tracked debt was a number that only ever went down when
somebody remembered to edit it. A loan accrues interest whether or not anybody
edits anything, so a balance that ignores it drifts optimistic — which is the
wrong direction for a debt.

Revision ID: 20260803_08
Revises: 20260803_07
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_08"
down_revision = "20260803_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for value in ("retirement", "brokerage", "loan"):
        op.execute(f"ALTER TYPE account_type ADD VALUE IF NOT EXISTS '{value}'")
    op.execute(
        """
        ALTER TABLE accounts
          -- Annual percentage rate, as a percentage: 6.25 means 6.25%. Null
          -- means "do not model interest", which stays the default because a
          -- guessed rate is worse than none.
          ADD COLUMN IF NOT EXISTS interest_rate NUMERIC(6, 3),
          -- What a normal payment is, for projecting a payoff date.
          ADD COLUMN IF NOT EXISTS minimum_payment NUMERIC(18, 2),
          -- The category that payments to this debt land in, created with the
          -- account so a new loan is budgetable immediately rather than after
          -- somebody notices it has nowhere to go.
          ADD COLUMN IF NOT EXISTS payment_category_id UUID
            REFERENCES categories(id) ON DELETE SET NULL,
          -- When interest was last applied, so a monthly accrual runs once a
          -- month regardless of how often the job happens to fire.
          ADD COLUMN IF NOT EXISTS interest_applied_through DATE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE accounts
          DROP COLUMN IF EXISTS interest_rate,
          DROP COLUMN IF EXISTS minimum_payment,
          DROP COLUMN IF EXISTS payment_category_id,
          DROP COLUMN IF EXISTS interest_applied_through
        """
    )
    # Enum values are left in place: removing one means rebuilding the type.
