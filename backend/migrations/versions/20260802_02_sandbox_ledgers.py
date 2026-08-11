"""Disposable copies of a whole ledger.

Revision ID: 20260802_02
Revises: 20260802_01
Create Date: 2026-08-02
"""

from alembic import op

revision = "20260802_02"
down_revision = "20260802_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A sandbox is an ordinary household with copies hanging off it. Everything
    # in this schema is already household-scoped, so cloning one gives a
    # complete, isolated ledger for free — and destroying it is a cascade
    # delete rather than a bespoke teardown that could miss a table.
    op.execute(
        """
        ALTER TABLE households
        ADD COLUMN IF NOT EXISTS is_sandbox BOOLEAN NOT NULL DEFAULT FALSE
        """
    )
    # Provenance, so a copy can say what it was a copy of. Nulled rather than
    # cascaded if the original is ever removed: the sandbox is still a real
    # ledger of its own and should not vanish with its parent.
    op.execute(
        """
        ALTER TABLE households
        ADD COLUMN IF NOT EXISTS cloned_from_id UUID
          REFERENCES households(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE households
        ADD COLUMN IF NOT EXISTS cloned_at TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    # Sandboxes are disposable by definition, so a downgrade removes them
    # rather than leaving copies that nothing can distinguish from real ledgers.
    op.execute("DELETE FROM households WHERE is_sandbox IS TRUE")
    op.execute("ALTER TABLE households DROP COLUMN IF EXISTS cloned_at")
    op.execute("ALTER TABLE households DROP COLUMN IF EXISTS cloned_from_id")
    op.execute("ALTER TABLE households DROP COLUMN IF EXISTS is_sandbox")
