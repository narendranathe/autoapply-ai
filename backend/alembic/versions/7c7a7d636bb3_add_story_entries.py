"""add_story_entries

Revision ID: 7c7a7d636bb3
Revises: a4218c2ef784
Create Date: 2026-04-27 14:14:35.663797

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c7a7d636bb3"
down_revision: str | None = "a4218c2ef784"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_tags", postgresql.JSONB(), nullable=False),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("situation", sa.String(200), nullable=False),
        sa.Column("action", sa.String(150), nullable=False),
        sa.Column("result_text", sa.String(150), nullable=False),
        sa.Column("reflection", sa.String(200), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("use_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "domain IN ('testing_ci_cd','orchestration','architecture_finops',"
            "'streaming_realtime','ml_ai_platform','cloud_infra','leadership_ownership',"
            "'sql_data_modeling','data_quality_observability','semantic_layer_governance')",
            name="ck_story_entries_domain",
        ),
        sa.CheckConstraint(
            "quality_score >= 0.0 AND quality_score <= 1.0",
            name="ck_story_entries_quality_score",
        ),
    )
    op.create_index("ix_story_entries_user_id", "story_entries", ["user_id"])
    op.create_index("ix_story_entries_user_domain", "story_entries", ["user_id", "domain"])
    op.create_index("ix_story_entries_user_quality", "story_entries", ["user_id", "quality_score"])
    op.execute("CREATE INDEX ix_story_entries_skill_tags ON story_entries USING GIN (skill_tags)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_story_entries_skill_tags")
    op.drop_index("ix_story_entries_user_quality", table_name="story_entries")
    op.drop_index("ix_story_entries_user_domain", table_name="story_entries")
    op.drop_index("ix_story_entries_user_id", table_name="story_entries")
    op.drop_table("story_entries")
