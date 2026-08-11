"""Add Parchment and Aurora appearance themes.

Revision ID: 20260801_02
Revises: 20260801_01
Create Date: 2026-08-01
"""

from alembic import op

revision = "20260801_02"
down_revision = "20260801_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("user_profile_theme", "user_profiles", type_="check")
    op.create_check_constraint(
        "user_profile_theme",
        "user_profiles",
        "theme IN ('system', 'light', 'parchment', 'dark', 'midnight', 'aurora')",
    )


def downgrade() -> None:
    # Preserve valid rows when rolling back to a release that only understands
    # the original four choices.
    op.execute(
        "UPDATE user_profiles SET theme = 'light' WHERE theme = 'parchment'"
    )
    op.execute("UPDATE user_profiles SET theme = 'dark' WHERE theme = 'aurora'")
    op.drop_constraint("user_profile_theme", "user_profiles", type_="check")
    op.create_check_constraint(
        "user_profile_theme",
        "user_profiles",
        "theme IN ('system', 'light', 'dark', 'midnight')",
    )
