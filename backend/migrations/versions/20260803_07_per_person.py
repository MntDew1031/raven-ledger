"""Whose account is whose, so spending can be attributed.

A household ledger that cannot say who spent what can only ever answer "we
spent". Once Jordan joins, the interesting question is usually the other one.

Attribution hangs off the account rather than the transaction, because that is
where it is actually known: a card belongs to somebody, and every charge on it
is theirs. A per-transaction override exists for the cases that are not — a
shared card used for a personal purchase, say.

`NULL` means shared, which is the right default: a joint checking account
belongs to the household, not to whoever happened to open it.

Revision ID: 20260803_07
Revises: 20260803_06
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_07"
down_revision = "20260803_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE accounts
          ADD COLUMN IF NOT EXISTS owner_user_id UUID
          REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE transactions
          ADD COLUMN IF NOT EXISTS paid_by_user_id UUID
          REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS transactions_paid_by_idx
          ON transactions (household_id, paid_by_user_id)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS paid_by_user_id")
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS owner_user_id")
