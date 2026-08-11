"""A category can always count in the month before.

1.65.0 let a single transaction be counted in a different budget month, and
Alex's immediate answer was that he wants it automatic — rent is not a
one-off, it happens every month for as long as he lives there.

`categories.budget_month_offset` is that default, in months. `-1` on Housing
means "spending in this category counts against the previous month's plan",
which is what rent due on the 1st and paid from last month's pay actually is.
`0`, the default, changes nothing.

**Applied when the budget is read, not written into each row.** Setting
`budget_month` on every Housing transaction at save time would work until he
changed his mind, at which point every past row would keep the old answer and
nothing would say so — the same staleness trap that has produced silently wrong
figures here before. Computed at read time, changing the offset fixes the
history too.

A per-transaction `budget_month` still wins over the category default: the
specific beats the general, so one odd month can be corrected without turning
the rule off.

Revision ID: 20260804_03
Revises: 20260804_02
Create Date: 2026-08-04
"""

from alembic import op

revision = "20260804_03"
down_revision = "20260804_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS "
        "budget_month_offset SMALLINT NOT NULL DEFAULT 0"
    )
    # A range rather than a free integer: this is "the month before" or "the
    # month after", not an arbitrary shift. Postgres has no
    # ADD CONSTRAINT IF NOT EXISTS, so drop first.
    op.execute(
        "ALTER TABLE categories DROP CONSTRAINT IF EXISTS category_budget_offset"
    )
    op.execute(
        "ALTER TABLE categories ADD CONSTRAINT category_budget_offset "
        "CHECK (budget_month_offset BETWEEN -1 AND 1)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE categories DROP CONSTRAINT IF EXISTS category_budget_offset"
    )
    op.execute(
        "ALTER TABLE categories DROP COLUMN IF EXISTS budget_month_offset"
    )
