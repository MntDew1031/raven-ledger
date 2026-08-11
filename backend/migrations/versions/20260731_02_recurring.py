"""Add detected recurring items.

Revision ID: 20260731_02
Revises: 20260731_01
Create Date: 2026-07-31
"""

from alembic import op

revision = "20260731_02"
down_revision = "20260731_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS recurring_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          merchant_key VARCHAR(255) NOT NULL,
          display_name VARCHAR(255) NOT NULL,
          direction VARCHAR(10) NOT NULL DEFAULT 'outflow',
          cadence VARCHAR(16) NOT NULL,
          average_amount NUMERIC(18,2) NOT NULL,
          last_amount NUMERIC(18,2) NOT NULL,
          occurrences INTEGER NOT NULL,
          last_seen DATE NOT NULL,
          next_due DATE NOT NULL,
          category_id UUID REFERENCES categories(id) ON DELETE SET NULL,
          account_id UUID REFERENCES accounts(id) ON DELETE SET NULL,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE (household_id, merchant_key, direction)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_recurring_household
        ON recurring_items (household_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recurring_items")
