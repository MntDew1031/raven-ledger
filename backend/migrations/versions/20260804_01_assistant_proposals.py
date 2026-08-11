"""Proposals the assistant makes and a person approves.

`IF NOT EXISTS` throughout — a fresh database is built from
`database/schema.sql` and *then* migrated, so plain DDL fails on exactly the
installs that have never seen this. See `20260803_11` and `20260803_13`.

Revision ID: 20260804_01
Revises: 20260803_13
"""

from alembic import op

revision = "20260804_01"
down_revision = "20260803_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_proposals (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          thread_id UUID REFERENCES assistant_threads(id) ON DELETE SET NULL,
          created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
          kind VARCHAR(32) NOT NULL,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          summary VARCHAR(400) NOT NULL,
          status VARCHAR(16) NOT NULL DEFAULT 'pending',
          applied_at TIMESTAMPTZ,
          result JSONB,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          CONSTRAINT assistant_proposal_kind
            CHECK (kind IN ('categorize', 'create_rule')),
          CONSTRAINT assistant_proposal_status
            CHECK (status IN ('pending', 'approved', 'rejected', 'failed'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_proposals_household_idx
          ON assistant_proposals (household_id, status)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assistant_proposals")
