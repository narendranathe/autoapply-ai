"""add user_provider_configs table

Revision ID: f3a7b1c2d4e5
Revises: e2f6a3b4c7d8
Create Date: 2026-03-17 00:00:00.000000

Stores per-user LLM provider API key configuration (encrypted), optional
model override, and enabled flag.  One row per (user, provider) pair.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f3a7b1c2d4e5"
down_revision: str | None = "e2f6a3b4c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_name",
            sa.String(50),
            nullable=False,
            comment="anthropic | openai | kimi | ollama",
        ),
        sa.Column(
            "encrypted_api_key",
            sa.Text(),
            nullable=False,
            comment="Fernet-encrypted API key — decrypted in-memory only.",
        ),
        sa.Column(
            "model_override",
            sa.String(100),
            nullable=True,
            comment="Optional model ID to use instead of the provider default.",
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Whether this provider is active for the user.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "provider_name", name="uq_user_provider"),
    )
    op.create_index(
        "ix_user_provider_configs_user_id",
        "user_provider_configs",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_provider_configs_user_id", table_name="user_provider_configs")
    op.drop_table("user_provider_configs")
