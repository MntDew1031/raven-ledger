"""Pay anchors, a per-month paycheque override, and card statement days.

**Written with `IF NOT EXISTS`, and that is not belt-and-braces.** A fresh
database is built by `database/schema.sql` from the postgres init mount and
*then* has migrations run over it, so every column added here already exists on
a new install. Written as plain `op.add_column` this fails on exactly the
deployments that have never seen it before — which is the opposite of the way
migrations are supposed to fail. Same convention as `20260803_11`.

Revision ID: 20260803_13
Revises: 20260803_12
"""

from alembic import op

revision = "20260803_13"
down_revision = "20260803_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One real pay date is all it takes to know which months carry a third
    # cheque. Nullable, because a household that has not supplied one still
    # gets the monthly average — just not the month-by-month truth.
    op.execute(
        "ALTER TABLE income_sources ADD COLUMN IF NOT EXISTS first_paid_on DATE"
    )
    # NULL means "work it out"; True/False are a person overriding one month.
    op.execute(
        "ALTER TABLE budgets ADD COLUMN IF NOT EXISTS extra_paycheque BOOLEAN"
    )
    op.execute(
        "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS statement_day SMALLINT"
    )
    # Postgres has no ADD CONSTRAINT IF NOT EXISTS, so drop first. Dropping a
    # constraint that is not there is a no-op with IF EXISTS, which makes this
    # safe to run against both a fresh schema and an upgraded one.
    op.execute(
        "ALTER TABLE accounts DROP CONSTRAINT IF EXISTS account_statement_day"
    )
    op.execute(
        """
        ALTER TABLE accounts ADD CONSTRAINT account_statement_day
        CHECK (statement_day IS NULL OR (statement_day BETWEEN 1 AND 31))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE accounts DROP CONSTRAINT IF EXISTS account_statement_day"
    )
    op.execute("ALTER TABLE accounts DROP COLUMN IF EXISTS statement_day")
    op.execute("ALTER TABLE budgets DROP COLUMN IF EXISTS extra_paycheque")
    op.execute("ALTER TABLE income_sources DROP COLUMN IF EXISTS first_paid_on")
