"""Let a person correct a synced transaction's amount, and keep the correction.

Revision ID: 20260802_01
Revises: 20260801_03
Create Date: 2026-08-02
"""

from alembic import op

revision = "20260802_01"
down_revision = "20260801_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plaid's sign is not always what a household means. A card payment, a
    # refund, or a transfer can arrive pointing the wrong way, and until now
    # there was no way to fix it: the API refused the edit, and the next sync
    # would have overwritten it regardless. This remembers that a person
    # decided, so sync stops arguing with them about that one field.
    op.execute(
        """
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS amount_overridden BOOLEAN NOT NULL DEFAULT FALSE
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE transactions DROP COLUMN IF EXISTS amount_overridden"
    )
