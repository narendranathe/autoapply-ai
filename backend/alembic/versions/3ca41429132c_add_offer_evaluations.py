"""add_offer_evaluations

Revision ID: 3ca41429132c
Revises: 7c7a7d636bb3
Create Date: 2026-04-27 14:34:19.536678

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3ca41429132c"
down_revision: str | None = "7c7a7d636bb3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "offer_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("jd_text_hash", sa.String(64), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("role_title", sa.String(200), nullable=False),
        sa.Column("dimension_scores", postgresql.JSONB(), nullable=False),
        sa.Column("overall_grade", sa.String(1), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("overall_grade IN ('A','B','C','D','F')", name="ck_offer_eval_grade"),
        sa.CheckConstraint(
            "overall_score >= 0.0 AND overall_score <= 100.0",
            name="ck_offer_eval_score",
        ),
        sa.UniqueConstraint("user_id", "jd_text_hash", name="uq_offer_eval_user_jd"),
    )
    op.create_index("ix_offer_evaluations_user_id", "offer_evaluations", ["user_id"])
    op.create_index("ix_offer_evaluations_jd_hash", "offer_evaluations", ["jd_text_hash"])
    op.create_index("ix_offer_eval_user_created", "offer_evaluations", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_offer_eval_user_created", table_name="offer_evaluations")
    op.drop_index("ix_offer_evaluations_jd_hash", table_name="offer_evaluations")
    op.drop_index("ix_offer_evaluations_user_id", table_name="offer_evaluations")
    op.drop_table("offer_evaluations")
