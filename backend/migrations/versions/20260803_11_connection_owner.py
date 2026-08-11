"""Who linked a connection, so two identical cards can be told apart.

Alex and Jordan hold the same two cards: a Chase Prime and a Discover it.
When she linked hers, the ledger showed four accounts with two names between
them, and no way to know which was whose — the account list read as though it
had duplicated itself.

Plaid does not say who owns an account in any way worth trusting: the holder
name is often the bank's own formatting of a joint title, and it is absent
entirely on plenty of institutions. But Raven already knows something reliable
— *which person was sitting at the screen when the connection was made*. That
is recorded here, and stamped onto the accounts the connection creates.

`accounts.owner_user_id` already existed for manual accounts; this only starts
filling it in for linked ones. It stays nullable and stays overridable: a joint
account linked by one person still belongs to both, and clearing the owner by
hand has to keep working.

Revision ID: 20260803_11
Revises: 20260803_10
Create Date: 2026-08-03
"""

from alembic import op

revision = "20260803_11"
down_revision = "20260803_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE institution_connections
        ADD COLUMN IF NOT EXISTS linked_by_user_id UUID
        REFERENCES users(id) ON DELETE SET NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE institution_connections DROP COLUMN IF EXISTS linked_by_user_id"
    )
