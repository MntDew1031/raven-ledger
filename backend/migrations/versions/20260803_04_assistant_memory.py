"""Conversations that survive a refresh, and things Raven remembers about you.

Two problems, one migration.

The assistant kept its messages in the browser's memory. Reloading the page
threw the conversation away, which makes it a toy: you cannot come back to a
question about your finances tomorrow.

And it started every conversation knowing nothing. Anything you explained last
week — that Southwest is reimbursed work travel, that you are saving for a
house — had to be explained again.

Both live here rather than in an external memory service. Financial facts
belong beside the financial data: they inherit the nightly dump that proves
itself by restoring, the household scoping, and the same encryption key. An
outside store would be a second copy of your finances with different backup and
retention properties.

Revision ID: 20260803_04
Revises: 20260803_03
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_04"
down_revision = "20260803_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          CREATE TYPE memory_source AS ENUM ('person', 'assistant', 'derived');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_threads (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          -- Whose conversation. A household shares a ledger but not its
          -- half-finished questions about money.
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title VARCHAR(160) NOT NULL DEFAULT 'New conversation',
          -- Bumped on every message so the list sorts by real activity rather
          -- than by when the thread happened to be started.
          last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_threads_recent_idx
          ON assistant_threads (user_id, last_message_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_messages (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          thread_id UUID NOT NULL
            REFERENCES assistant_threads(id) ON DELETE CASCADE,
          role VARCHAR(16) NOT NULL,
          content TEXT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_messages_thread_idx
          ON assistant_messages (thread_id, created_at)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_memories (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          -- One plain sentence. Kept short deliberately: a memory that needs a
          -- paragraph is a note, and a person cannot skim a wall of them to
          -- decide which is now wrong.
          fact VARCHAR(400) NOT NULL,
          source memory_source NOT NULL DEFAULT 'person',
          -- Off rather than deleted, so something that stops being true this
          -- year can be switched back on next year.
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          -- Raven proposes; a person confirms. An unconfirmed memory is shown
          -- for approval and never reaches the model's context.
          confirmed_at TIMESTAMPTZ,
          created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS assistant_memories_household_idx
          ON assistant_memories (household_id, is_active)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assistant_messages")
    op.execute("DROP TABLE IF EXISTS assistant_threads")
    op.execute("DROP TABLE IF EXISTS assistant_memories")
    op.execute("DROP TYPE IF EXISTS memory_source")
