"""An opening balance, so a manual account can actually be reconciled.

The first version of the reconciliation check compared an account's balance to
the sum of its transactions and called any gap a fault. For a manual account
that is wrong: the gap *is* the opening balance — whatever the account held
before the first recorded transaction — and reporting it as drift means the
check fires on every account forever, which is the fastest way to make a
warning worthless.

With an opening balance recorded, the arithmetic has a right answer and a gap
means something genuinely does not add up.

Revision ID: 20260803_10
Revises: 20260803_09
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_10"
down_revision = "20260803_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE accounts
          -- NULL means "not established", which is different from zero: zero
          -- is a claim that the account was empty, and most were not.
          ADD COLUMN IF NOT EXISTS opening_balance NUMERIC(18, 2)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS opening_balance")
