"""Add TOTP MFA state and append-oriented security events.

Revision ID: 20260805_01
Revises: 20260804_04
Create Date: 2026-08-05
"""

from alembic import op

revision = "20260805_01"
down_revision = "20260804_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret_encrypted TEXT")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled_at TIMESTAMPTZ")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_recovery_codes JSONB")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID REFERENCES households(id) ON DELETE SET NULL,
          user_id UUID REFERENCES users(id) ON DELETE SET NULL,
          event_type VARCHAR(80) NOT NULL,
          success BOOLEAN NOT NULL DEFAULT TRUE,
          ip_address VARCHAR(64),
          user_agent VARCHAR(240),
          details JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS security_events_household_recent "
        "ON security_events (household_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS security_events_user_recent "
        "ON security_events (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_security_events_event_type "
        "ON security_events (event_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS security_events")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS mfa_recovery_codes")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS mfa_enabled_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS mfa_secret_encrypted")
