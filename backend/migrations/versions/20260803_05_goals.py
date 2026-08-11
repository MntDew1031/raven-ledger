"""Savings goals that survive a change of month.

`flex_bucket = 'goal'` has existed on categories since the beginning and did
nothing. The closest thing to a goal was `budget_lines.non_monthly_target`,
which is stored per month — so it could describe "put aside $300 in August" but
not "reach $12,000 by June 2027", which is what a goal actually is.

Revision ID: 20260803_05
Revises: 20260803_04
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_05"
down_revision = "20260803_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS goals (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          name VARCHAR(120) NOT NULL,
          target_amount NUMERIC(18, 2) NOT NULL,
          target_date DATE,
          -- Where the money for this goal actually sits. Optional: a goal can
          -- be tracked by hand before it has an account of its own, which is
          -- how most goals start.
          account_id UUID REFERENCES accounts(id) ON DELETE SET NULL,
          -- What has been put aside so far when no account is linked. Ignored
          -- when one is, because the account balance is the truth and two
          -- sources of the same number will disagree.
          saved_amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
          notes VARCHAR(400),
          is_achieved BOOLEAN NOT NULL DEFAULT FALSE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE (household_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS goals_household_idx
          ON goals (household_id, is_achieved)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS goals")
