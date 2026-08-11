"""Count a transaction in a month other than the one it posted in.

Rent is due on the 1st. Alex pays it from the *previous* month's pay, and it
posts on the 1st of the new one. His words:

    "rent is due at the first of the month so it technically comes out of the
    July budget/paycheck but the transaction goes through in August and makes
    it look like we don't have to budget for next month's rent, which is not
    true."

August's Housing line read $1,279.87 spent of $1,280.50 planned — satisfied,
apparently — while the money that paid it left in July, and nothing anywhere
told him to set September's rent aside out of August's pay.

**`posted_date` is not touched and never will be by this.** It is when the
money actually moved; reports are history and history does not get edited to
make a plan tidier. This column is a second, optional answer to a different
question: *which month's plan should this count against?* NULL — the default
and the case for almost every row — means "the month it posted in", so nothing
changes for anyone who never uses it.

Only the budget page reads it. Every other money query in this codebase filters
on `posted_date`, and that is deliberate: net worth, cash flow, the Sankey, the
statements and the reconciliation are all statements about what happened, not
about what was planned.

Revision ID: 20260804_02
Revises: 20260804_01
Create Date: 2026-08-04
"""

from alembic import op

revision = "20260804_02"
down_revision = "20260804_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `IF NOT EXISTS` because a fresh database is built from `database/schema.sql`
    # and *then* migrated, so a plain add_column fails on exactly the installs
    # that have never seen the column.
    op.execute(
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS budget_month DATE"
    )
    # Read on the budget page for one household and one month at a time.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transactions_budget_month "
        "ON transactions (household_id, budget_month) "
        "WHERE budget_month IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transactions_budget_month")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS budget_month")
