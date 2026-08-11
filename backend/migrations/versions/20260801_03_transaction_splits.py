"""Split one transaction into several categorized lines.

Revision ID: 20260801_03
Revises: 20260801_02
Create Date: 2026-08-01
"""

from alembic import op

revision = "20260801_03"
down_revision = "20260801_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Split lines are ordinary transactions that point at the bank charge they
    # came from. Modelling them as rows rather than a side table means every
    # existing filter — category, tag, amount, date — works on them unchanged.
    op.execute(
        """
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS parent_transaction_id UUID
          REFERENCES transactions(id) ON DELETE CASCADE
        """
    )
    # `is_split` marks the parent. It is derivable from the children, but a
    # column keeps the "does this row represent real money" test to a single
    # cheap predicate in the dozen places that aggregate — and a missed
    # predicate is a silently doubled total, which is the whole risk here.
    op.execute(
        """
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS is_split BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_transactions_parent
        ON transactions (parent_transaction_id)
        WHERE parent_transaction_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Children carry the categorization; deleting them would silently discard
    # decisions. Fold each split back into its parent first so a downgrade
    # loses the breakdown but never the money.
    op.execute(
        """
        UPDATE transactions parent
        SET category_id = child.category_id
        FROM (
            SELECT DISTINCT ON (parent_transaction_id)
                   parent_transaction_id, category_id
            FROM transactions
            WHERE parent_transaction_id IS NOT NULL
            ORDER BY parent_transaction_id, abs(amount) DESC
        ) AS child
        WHERE parent.id = child.parent_transaction_id
          AND parent.category_id IS NULL
        """
    )
    op.execute("DELETE FROM transactions WHERE parent_transaction_id IS NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_transactions_parent")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS is_split")
    op.execute(
        "ALTER TABLE transactions DROP COLUMN IF EXISTS parent_transaction_id"
    )
