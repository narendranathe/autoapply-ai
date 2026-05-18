"""drop is_enabled column from user_provider_configs

Revision ID: b7c2d4e6f8a1
Revises: 45ca64ce5f2e
Create Date: 2026-05-17 00:00:00.000000

Issue #104: ``is_enabled`` was redundant — a provider is enabled iff the user
has supplied an API key.  The flag is now derived from ``encrypted_api_key``
at the model layer, so the stored column is dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c2d4e6f8a1"
down_revision: str | None = "45ca64ce5f2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("user_provider_configs", "is_enabled")


def downgrade() -> None:
    op.add_column(
        "user_provider_configs",
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Whether this provider is active for the user.",
        ),
    )
