"""Remember merchant decisions and keep Plaid's own category.

Revision ID: 20260801_01
Revises: 20260731_02
Create Date: 2026-08-01
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "20260801_01"
down_revision = "20260731_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE transactions
        ADD COLUMN IF NOT EXISTS provider_category VARCHAR(120)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS merchant_memories (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          household_id UUID NOT NULL
            REFERENCES households(id) ON DELETE CASCADE,
          merchant_key VARCHAR(255) NOT NULL,
          category_id UUID NOT NULL
            REFERENCES categories(id) ON DELETE CASCADE,
          sample_label VARCHAR(255),
          source VARCHAR(20) NOT NULL DEFAULT 'human',
          hits INTEGER NOT NULL DEFAULT 0,
          last_applied_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE (household_id, merchant_key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_merchant_memories_household
        ON merchant_memories (household_id)
        """
    )
    _backfill_from_reviewed_history()


# A frozen copy of `normalize_merchant` as it stood when this migration was
# written. Backfilled keys have to match what the application computes, and
# importing the live function would silently rewrite this migration's behaviour
# the next time that function is tuned.
_REFERENCE_TOKEN = re.compile(r"^(?=.*[a-z])(?=(?:\D*\d){2,})[a-z0-9]{4,}$")


def _normalize(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    normalized = re.sub(r"\b\d{4,}\b", " ", normalized)
    tokens = normalized.split()
    kept = [
        token
        for index, token in enumerate(tokens)
        if not _REFERENCE_TOKEN.match(token)
        and not (index > 0 and token.isdigit())
    ]
    return " ".join(kept or tokens)


def _backfill_from_reviewed_history() -> None:
    """
    Seed memory from decisions people have already made.

    Every reviewed, categorized transaction is a judgement that was previously
    thrown away. Replaying the most recent one per merchant means the change is
    felt immediately on existing history rather than only on new imports.

    Done in Python rather than SQL so the key is computed by exactly the same
    rules the application uses — an approximation here would produce memories
    that never match anything.
    """
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT household_id, category_id,
                   coalesce(normalized_merchant, merchant_name,
                            original_description) AS raw,
                   coalesce(merchant_name, original_description) AS label
            FROM transactions
            WHERE reviewed IS TRUE AND category_id IS NOT NULL
            ORDER BY posted_date ASC
            """
        )
    ).all()

    # Later rows overwrite earlier ones, so the newest decision per merchant is
    # the one that survives.
    latest: dict[tuple, tuple] = {}
    for household_id, category_id, raw, label in rows:
        key = _normalize(raw or "")
        if not key:
            continue
        latest[(household_id, key[:255])] = (category_id, (label or "")[:255])

    for (household_id, key), (category_id, label) in latest.items():
        connection.execute(
            sa.text(
                """
                INSERT INTO merchant_memories
                  (household_id, merchant_key, category_id, sample_label,
                   source, hits)
                VALUES (:household_id, :key, :category_id, :label, 'human', 0)
                ON CONFLICT (household_id, merchant_key) DO NOTHING
                """
            ),
            {
                "household_id": household_id,
                "key": key,
                "category_id": category_id,
                "label": label,
            },
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS merchant_memories")
    op.execute("ALTER TABLE transactions DROP COLUMN IF EXISTS provider_category")
