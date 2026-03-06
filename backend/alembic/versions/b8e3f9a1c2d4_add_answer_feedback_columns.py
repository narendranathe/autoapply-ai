"""add answer feedback columns

Revision ID: b8e3f9a1c2d4
Revises: a3f2e1d4c5b6
Create Date: 2026-03-05 00:00:00.000000

Adds RL reward-signal columns to application_answers:
  feedback      — outcome: used_as_is | edited | regenerated | skipped | pending
  reward_score  — float 0.0–1.0 computed from feedback
  edit_distance — char-level edit distance if feedback == "edited"
  + composite index for fast category + reward ranking
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8e3f9a1c2d4"
down_revision: str | None = "a3f2e1d4c5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "application_answers",
        sa.Column("feedback", sa.String(30), nullable=False, server_default="pending"),
    )
    op.add_column(
        "application_answers",
        sa.Column("reward_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "application_answers",
        sa.Column("edit_distance", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_answers_user_category_reward",
        "application_answers",
        ["user_id", "question_category", "reward_score"],
    )


def downgrade() -> None:
    op.drop_index("ix_answers_user_category_reward", table_name="application_answers")
    op.drop_column("application_answers", "edit_distance")
    op.drop_column("application_answers", "reward_score")
    op.drop_column("application_answers", "feedback")
