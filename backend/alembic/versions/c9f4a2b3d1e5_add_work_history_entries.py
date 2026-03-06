"""add work history entries table

Revision ID: c9f4a2b3d1e5
Revises: b8e3f9a1c2d4
Create Date: 2026-03-05 00:00:00.000000

Stores structured employment + education history per user.
Used to ground LLM answer/resume generation with real facts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9f4a2b3d1e5"
down_revision: str | None = "b8e3f9a1c2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_history_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("entry_type", sa.String(20), nullable=False, server_default="work"),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("role_title", sa.String(200), nullable=False),
        sa.Column("start_date", sa.String(30), nullable=False),
        sa.Column("end_date", sa.String(30), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("location", sa.String(100), nullable=True),
        sa.Column("bullets", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("technologies", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("team_size", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_work_history_user_id", "work_history_entries", ["user_id"])
    op.create_index(
        "ix_work_history_user_sort",
        "work_history_entries",
        ["user_id", "sort_order"],
    )


def downgrade() -> None:
    op.drop_index("ix_work_history_user_sort", table_name="work_history_entries")
    op.drop_index("ix_work_history_user_id", table_name="work_history_entries")
    op.drop_table("work_history_entries")
