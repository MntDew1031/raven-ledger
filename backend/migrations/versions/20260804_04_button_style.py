"""Pick how buttons are drawn, separately from the colour theme.

Alex: "I'm not entirely in love with the gradient buttons. What other options
would you suggest besides gradients?" — then, of the four alternatives: "let's
just make all of your suggestions separate themes that we can pick from."

**A separate axis from `theme`, deliberately.** A button treatment is not a
colour scheme: he uses light and dark equally, and making these themes would
have meant ten of them and no way to have Midnight with solid buttons. As its
own preference, every treatment works under every theme.

The five, from loudest to quietest:

- `iris`      the gradient ramp — what shipped in 1.54.0, still the default
- `solid`     one accent fill with a weighted shadow; calm, and the most
              conventional reading for a money application
- `flat`      the same fill with no drop shadow and a 1px top highlight; crisp
- `duotone`   an accent *tint* with accent border and text; the quietest
- `restrained` the gradient kept for the one primary action on a screen, every
              other button solid — emphasis by scarcity rather than by force

Revision ID: 20260804_04
Revises: 20260804_03
Create Date: 2026-08-04
"""

from alembic import op

revision = "20260804_04"
down_revision = "20260804_03"
branch_labels = None
depends_on = None

STYLES = "'iris', 'solid', 'flat', 'duotone', 'restrained'"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS "
        "button_style VARCHAR(16) NOT NULL DEFAULT 'iris'"
    )
    # Postgres has no ADD CONSTRAINT IF NOT EXISTS, so drop first.
    op.execute(
        "ALTER TABLE user_profiles DROP CONSTRAINT IF EXISTS user_profile_button_style"
    )
    op.execute(
        "ALTER TABLE user_profiles ADD CONSTRAINT user_profile_button_style "
        f"CHECK (button_style IN ({STYLES}))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_profiles DROP CONSTRAINT IF EXISTS user_profile_button_style"
    )
    op.execute("ALTER TABLE user_profiles DROP COLUMN IF EXISTS button_style")
