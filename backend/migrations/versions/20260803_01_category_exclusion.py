"""Let a whole category be kept out of budget and spending totals.

Transactions could already be excluded one at a time
(`transactions.excluded_from_budget`), but there was no way to say "this
category never counts" — reimbursed work expenses, a shared account whose
spending is somebody else's, a category kept only for record-keeping. Doing it
per transaction meant remembering to tick every future one.

Revision ID: 20260803_01
Revises: 20260802_03
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_01"
down_revision = "20260802_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE categories
          ADD COLUMN IF NOT EXISTS excluded_from_budget BOOLEAN
          NOT NULL DEFAULT FALSE
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE categories DROP COLUMN IF EXISTS excluded_from_budget"
    )
