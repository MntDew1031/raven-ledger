from pathlib import Path

from app.models import Base
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

EXPECTED_SCOPED_FOREIGN_KEYS = {
    "accounts": {
        "fk_accounts_connection_household",
        "fk_accounts_payment_category_household",
    },
    "categories": {"fk_categories_group_household"},
    "transactions": {
        "fk_transactions_account_household",
        "fk_transactions_category_household",
        "fk_transactions_parent_household",
    },
    "goals": {"fk_goals_account_household"},
    "categorization_rules": {"fk_rules_category_household"},
    "merchant_memories": {"fk_merchant_memories_category_household"},
    "recurring_items": {
        "fk_recurring_category_household",
        "fk_recurring_account_household",
    },
}


def constraint_names(table_name: str, kind: type) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, kind) and constraint.name
    }


def test_every_cross_financial_reference_is_household_scoped():
    for table_name, expected in EXPECTED_SCOPED_FOREIGN_KEYS.items():
        assert expected <= constraint_names(table_name, ForeignKeyConstraint)


def test_composite_targets_are_declared_unique():
    for table_name in (
        "institution_connections",
        "accounts",
        "category_groups",
        "categories",
        "transactions",
    ):
        table = Base.metadata.tables[table_name]
        unique_column_sets = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert ("id", "household_id") in unique_column_sets


def test_scoped_constraints_do_not_make_orm_relationships_ambiguous():
    configure_mappers()


def test_tenant_integrity_migration_follows_the_mfa_migration():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260805_02_tenant_integrity.py"
    ).read_text()

    assert 'revision = "20260805_02"' in migration
    assert 'down_revision = "20260805_01"' in migration
