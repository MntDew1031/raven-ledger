"""enforce household integrity on financial relationships

Revision ID: 20260805_02
Revises: 20260805_01
"""

from alembic import op

revision = "20260805_02"
down_revision = "20260805_01"
branch_labels = None
depends_on = None


UNIQUE_CONSTRAINTS = (
    (
        "institution_connections",
        "uq_institution_connections_id_household",
        "id, household_id",
    ),
    ("accounts", "uq_accounts_id_household", "id, household_id"),
    (
        "category_groups",
        "uq_category_groups_id_household",
        "id, household_id",
    ),
    ("categories", "uq_categories_id_household", "id, household_id"),
    ("transactions", "uq_transactions_id_household", "id, household_id"),
)

FOREIGN_KEYS = (
    (
        "accounts",
        "fk_accounts_connection_household",
        "connection_id, household_id",
        "institution_connections",
        "id, household_id",
    ),
    (
        "accounts",
        "fk_accounts_payment_category_household",
        "payment_category_id, household_id",
        "categories",
        "id, household_id",
    ),
    (
        "categories",
        "fk_categories_group_household",
        "group_id, household_id",
        "category_groups",
        "id, household_id",
    ),
    (
        "transactions",
        "fk_transactions_account_household",
        "account_id, household_id",
        "accounts",
        "id, household_id",
    ),
    (
        "transactions",
        "fk_transactions_category_household",
        "category_id, household_id",
        "categories",
        "id, household_id",
    ),
    (
        "transactions",
        "fk_transactions_parent_household",
        "parent_transaction_id, household_id",
        "transactions",
        "id, household_id",
    ),
    (
        "goals",
        "fk_goals_account_household",
        "account_id, household_id",
        "accounts",
        "id, household_id",
    ),
    (
        "categorization_rules",
        "fk_rules_category_household",
        "category_id, household_id",
        "categories",
        "id, household_id",
    ),
    (
        "merchant_memories",
        "fk_merchant_memories_category_household",
        "category_id, household_id",
        "categories",
        "id, household_id",
    ),
    (
        "recurring_items",
        "fk_recurring_category_household",
        "category_id, household_id",
        "categories",
        "id, household_id",
    ),
    (
        "recurring_items",
        "fk_recurring_account_household",
        "account_id, household_id",
        "accounts",
        "id, household_id",
    ),
)


def _constraint_missing(table: str, constraint: str, ddl: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = '{constraint}'
              AND conrelid = '{table}'::regclass
          ) THEN
            {ddl};
          END IF;
        END $$
        """  # nosec B608 -- identifiers are fixed constants in this migration
    )


def upgrade() -> None:
    for table, name, columns in UNIQUE_CONSTRAINTS:
        _constraint_missing(
            table,
            name,
            f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({columns})",
        )

    for table, name, columns, target, target_columns in FOREIGN_KEYS:
        _constraint_missing(
            table,
            name,
            (
                f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                f"FOREIGN KEY ({columns}) REFERENCES {target} ({target_columns}) "
                "NOT VALID"
            ),
        )
        # Validation scans existing rows once. New writes are protected from
        # the instant the NOT VALID constraint is installed.
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")  # nosec B608


def downgrade() -> None:
    for table, name, *_ in reversed(FOREIGN_KEYS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")  # nosec B608
    for table, name, _ in reversed(UNIQUE_CONSTRAINTS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")  # nosec B608
