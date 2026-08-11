"""Track per-user onboarding dismissal.

Revision ID: 20260731_01
Revises: 20260730_01
Create Date: 2026-07-31
"""

from alembic import op

revision = "20260731_01"
down_revision = "20260730_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_profiles
        ADD COLUMN IF NOT EXISTS onboarding_dismissed_at TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_profiles
        DROP COLUMN IF EXISTS onboarding_dismissed_at
        """
    )
