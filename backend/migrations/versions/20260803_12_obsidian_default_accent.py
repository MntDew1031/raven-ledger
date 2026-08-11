"""Obsidian becomes the default accent for new profiles.

Only the column default moves. **Existing rows are deliberately left alone**:
there is no way to tell a profile that chose Forest from one that never touched
the setting, and silently repainting somebody's chosen accent is worse than
leaving them one click away from the new one.

Revision ID: 20260803_12
Revises: 20260803_11
"""

import sqlalchemy as sa
from alembic import op

revision = "20260803_12"
down_revision = "20260803_11"
branch_labels = None
depends_on = None


ACCENTS = ("obsidian", "green", "orange", "red", "blue", "plum")


def upgrade() -> None:
    # The CHECK constraint is the part that actually matters. Without widening
    # it, choosing Obsidian fails in the database rather than in validation —
    # the setting applies in the browser, appears to work, and is gone on the
    # next load. A value added to a Literal needs the constraint, the column
    # default, `models.py` and `database/schema.sql` for a fresh install.
    op.drop_constraint("user_profile_accent", "user_profiles", type_="check")
    op.create_check_constraint(
        "user_profile_accent",
        "user_profiles",
        "accent IN " + str(ACCENTS),
    )
    op.alter_column(
        "user_profiles",
        "accent",
        existing_type=sa.String(16),
        existing_nullable=False,
        server_default="obsidian",
    )


def downgrade() -> None:
    op.execute("UPDATE user_profiles SET accent = 'green' WHERE accent = 'obsidian'")
    op.drop_constraint("user_profile_accent", "user_profiles", type_="check")
    op.create_check_constraint(
        "user_profile_accent",
        "user_profiles",
        "accent IN ('green', 'orange', 'red', 'blue', 'plum')",
    )
    op.alter_column(
        "user_profiles",
        "accent",
        existing_type=sa.String(16),
        existing_nullable=False,
        server_default="green",
    )
