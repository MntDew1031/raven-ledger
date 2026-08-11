"""Add persistent user profiles and avatars.

Revision ID: 20260730_01
Revises:
Create Date: 2026-07-30
"""

from alembic import op

revision = "20260730_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
          user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          theme VARCHAR(16) NOT NULL DEFAULT 'system',
          accent VARCHAR(16) NOT NULL DEFAULT 'green',
          density VARCHAR(16) NOT NULL DEFAULT 'comfortable',
          start_page VARCHAR(32) NOT NULL DEFAULT '/',
          avatar_data BYTEA,
          avatar_mime VARCHAR(40),
          avatar_revision VARCHAR(36),
          avatar_size INTEGER,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          CONSTRAINT user_profile_theme
            CHECK (theme IN ('system', 'light', 'dark', 'midnight')),
          CONSTRAINT user_profile_accent
            CHECK (accent IN ('green', 'orange', 'red', 'blue', 'plum')),
          CONSTRAINT user_profile_density
            CHECK (density IN ('comfortable', 'compact')),
          CONSTRAINT user_profile_start_page
            CHECK (start_page IN (
              '/', '/accounts', '/transactions', '/budgets', '/reports'
            ))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_profiles")
