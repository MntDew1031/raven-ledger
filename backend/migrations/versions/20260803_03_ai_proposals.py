"""Proposals the AI makes, which a person approves, edits, or rejects.

Raven already had the AI write directly to transactions. That is fine for a
category guess — it is visibly unreviewed and easy to correct — but it does not
extend to writing rules or budget amounts, which are decisions with
consequences. Those need to be *proposed* and looked at first.

Nothing here is applied until somebody approves it.

Revision ID: 20260803_03
Revises: 20260803_02
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_03"
down_revision = "20260803_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE proposal_kind AS ENUM (
            'category', 'transfer', 'exclusion', 'rule', 'budget'
          );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE proposal_status AS ENUM (
            'pending', 'approved', 'rejected', 'stale'
          );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_proposals (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          kind proposal_kind NOT NULL,
          status proposal_status NOT NULL DEFAULT 'pending',
          -- What the change would do, and what it would undo. `payload` is
          -- edited in place when somebody changes a proposal before accepting
          -- it, so approving always applies exactly what was on screen.
          payload JSONB NOT NULL,
          -- Enough to answer "why is it suggesting this?" without re-running
          -- the model. Shown next to every row.
          rationale VARCHAR(400) NOT NULL DEFAULT '',
          -- Deterministic proposals (a matched transfer pair) are certain;
          -- model proposals are not. Sorts the confident ones first.
          confidence NUMERIC(4, 3) NOT NULL DEFAULT 0.5,
          -- Set when the underlying data moved on before a decision was made,
          -- so a stale proposal is never silently applied to something else.
          decided_at TIMESTAMPTZ,
          decided_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ai_proposals_pending_idx
          ON ai_proposals (household_id, status, kind)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_proposals")
    op.execute("DROP TYPE IF EXISTS proposal_kind")
    op.execute("DROP TYPE IF EXISTS proposal_status")
