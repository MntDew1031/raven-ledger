"""Named API keys so other tools can read, and some can write.

Revision ID: 20260802_03
Revises: 20260802_02
Create Date: 2026-08-02
"""

from alembic import op

revision = "20260802_03"
down_revision = "20260802_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          created_by_user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,
          name VARCHAR(80) NOT NULL,
          -- Only the hash is stored. The secret is shown once, at creation,
          -- and is unrecoverable afterwards; a leaked database therefore
          -- yields no usable key.
          token_hash VARCHAR(64) NOT NULL UNIQUE,
          -- The first few characters, kept so a key can be told apart in a
          -- list without revealing anything that could be used.
          prefix VARCHAR(16) NOT NULL,
          -- Read is implicit. This is the flag that separates "ask my ledger
          -- questions" from "change my ledger".
          can_write BOOLEAN NOT NULL DEFAULT FALSE,
          last_used_at TIMESTAMPTZ,
          expires_at TIMESTAMPTZ,
          revoked_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_api_keys_household
        ON api_keys (household_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_keys")
