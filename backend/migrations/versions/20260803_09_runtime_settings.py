"""Settings that can be changed without a redeploy.

Choosing which model Raven uses meant editing a Kubernetes manifest and
restarting two deployments. That is a poor fit for something you want to try
three of in an evening — and the last round of testing showed the *batch size*
matters as much as the model, so both need to move together.

Install-wide rather than per household: there is one AI endpoint, and a sandbox
is a household. Writes are restricted to an operator, the same authority that
gates backups.

**`LLM_BASE_URL` deliberately stays in the environment.** A model name is a
harmless choice; an endpoint is where this household's financial data gets
sent. Anything settable in the UI is settable by anyone who reaches the UI, and
"point the ledger at a server I control" is not a button worth building.

Revision ID: 20260803_09
Revises: 20260803_08
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_09"
down_revision = "20260803_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
          key VARCHAR(64) PRIMARY KEY,
          -- JSONB rather than text so a setting can grow a shape later
          -- without another migration.
          value JSONB NOT NULL,
          updated_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings")
