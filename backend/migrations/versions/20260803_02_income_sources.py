"""Named income sources, so a household with two earners can say so.

The budget held a single "expected monthly income" number. Alex and Jordan are
paid different amounts on different schedules, and one field cannot represent
that — nor can it survive a raise without somebody re-deriving the total by
hand and getting the bi-weekly arithmetic wrong.

Revision ID: 20260803_02
Revises: 20260803_01
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_02"
down_revision = "20260803_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE pay_cadence AS ENUM (
            'weekly', 'biweekly', 'semimonthly', 'monthly', 'annual'
          );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS income_sources (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          -- Whose pay this is. A person's name rather than a user id: an
          -- earner does not have to have an account here, and Jordan's income
          -- should be plannable before she ever signs in.
          name VARCHAR(80) NOT NULL,
          amount NUMERIC(18, 2) NOT NULL DEFAULT 0,
          cadence pay_cadence NOT NULL DEFAULT 'monthly',
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          notes VARCHAR(400),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE (household_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS income_sources_household_idx
          ON income_sources (household_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS income_sources")
    op.execute("DROP TYPE IF EXISTS pay_cadence")
