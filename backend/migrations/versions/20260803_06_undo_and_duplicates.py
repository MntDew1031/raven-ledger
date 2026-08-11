"""An undo for bulk actions, and a proposal kind for duplicates.

The organizer can apply thirty changes in one tap and there is no way back,
which is a good reason to hesitate before pressing Apply — exactly the
hesitation the feature was meant to remove. Bulk categorization and running
rules have the same problem.

Recording enough to reverse an action is cheap; recording it *after* the fact
is impossible, so the log stores the previous value of every field it touches.

The duplicate kind is added here rather than in its own migration because
`ALTER TYPE ... ADD VALUE` and the table it will be used with belong together.

Revision ID: 20260803_06
Revises: 20260803_05
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_06"
down_revision = "20260803_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres 12+ allows this inside a transaction as long as the new value is
    # not used in the same one. Nothing below uses it.
    op.execute("ALTER TYPE proposal_kind ADD VALUE IF NOT EXISTS 'duplicate'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_log (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          user_id UUID REFERENCES users(id) ON DELETE SET NULL,
          -- What was done, for the sentence shown to a person.
          kind VARCHAR(40) NOT NULL,
          summary VARCHAR(300) NOT NULL,
          -- Everything needed to put it back: one entry per field changed,
          -- carrying the value it held before. Written at the time because it
          -- cannot be reconstructed afterwards.
          changes JSONB NOT NULL,
          undone_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS activity_log_recent_idx
          ON activity_log (household_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS activity_log")
    # The enum value is deliberately left: removing a value from an enum in
    # Postgres means rebuilding the type, and a downgrade should not risk that.
