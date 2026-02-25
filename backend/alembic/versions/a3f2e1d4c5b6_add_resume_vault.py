"""add resume vault

Revision ID: a3f2e1d4c5b6
Revises: 15d0f847bcc2
Create Date: 2026-02-24 12:00:00.000000

Adds three new tables:
  resumes            — resume vault storage with embeddings
  resume_usages      — per-application usage history
  application_answers — open-ended Q&A storage for auto-fill & callback reference
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision: str = "a3f2e1d4c5b6"
down_revision: str | None = "15d0f847bcc2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── resumes ────────────────────────────────────────────────────────────
    op.create_table(
        "resumes",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("latex_content", sa.Text(), nullable=True),
        sa.Column("markdown_content", sa.Text(), nullable=True),
        sa.Column("bullet_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skills_detected", JSON, nullable=True),
        sa.Column("companies_found", JSON, nullable=True),
        sa.Column("sections_found", JSON, nullable=True),
        sa.Column("tfidf_vector", JSON, nullable=True),
        sa.Column("embedding_vector", JSON, nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("version_tag", sa.String(length=200), nullable=True),
        sa.Column("recruiter_filename", sa.String(length=100), nullable=True),
        sa.Column("is_base_template", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("github_path", sa.String(length=500), nullable=True),
        sa.Column("github_commit_sha", sa.String(length=40), nullable=True),
        sa.Column("ats_score", sa.Float(), nullable=True),
        sa.Column("target_company", sa.String(length=200), nullable=True),
        sa.Column("target_role", sa.String(length=200), nullable=True),
        sa.Column("target_jd_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])
    op.create_index("ix_resumes_version_tag", "resumes", ["version_tag"])
    op.create_index("ix_resumes_target_company", "resumes", ["target_company"])
    op.create_index("ix_resumes_user_company", "resumes", ["user_id", "target_company"])

    # ── resume_usages ──────────────────────────────────────────────────────
    op.create_table(
        "resume_usages",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), nullable=True),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("role_title", sa.String(length=200), nullable=False),
        sa.Column("job_id", sa.String(length=100), nullable=True),
        sa.Column("job_url", sa.String(length=1000), nullable=True),
        sa.Column("ats_score_at_use", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(length=50), nullable=False, server_default="unknown"),
        sa.Column("git_tag", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resume_usages_user_id", "resume_usages", ["user_id"])
    op.create_index("ix_resume_usages_company", "resume_usages", ["company_name"])
    op.create_index(
        "ix_resume_usages_user_company",
        "resume_usages",
        ["user_id", "company_name"],
    )

    # ── application_answers ────────────────────────────────────────────────
    op.create_table(
        "application_answers",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), nullable=True),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_category", sa.String(length=50), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("was_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("llm_provider_used", sa.String(length=50), nullable=True),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("role_title", sa.String(length=200), nullable=True),
        sa.Column("job_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_answers_user_id", "application_answers", ["user_id"])
    op.create_index("ix_answers_company", "application_answers", ["company_name"])
    op.create_index("ix_answers_question_hash", "application_answers", ["question_hash"])
    op.create_index(
        "ix_answers_user_company",
        "application_answers",
        ["user_id", "company_name"],
    )


def downgrade() -> None:
    op.drop_table("application_answers")
    op.drop_table("resume_usages")
    op.drop_table("resumes")
