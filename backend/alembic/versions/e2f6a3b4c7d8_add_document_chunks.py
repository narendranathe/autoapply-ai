"""add document_chunks table for RAG pipeline

Revision ID: e2f6a3b4c7d8
Revises: d1e5f3a4b2c6
Create Date: 2026-03-13 00:00:00.000000

Stores chunked markdown documents (resume.md / work-history.md) with TF-IDF
vectors and optional dense embeddings for RAG-grounded generation.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e2f6a3b4c7d8"
down_revision: str | None = "d1e5f3a4b2c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_header", sa.String(500), nullable=False, server_default=""),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tfidf_vector", postgresql.JSON(), nullable=True),
        sa.Column("dense_embedding", postgresql.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=False, server_default=""),
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
    )
    op.create_index(
        "ix_document_chunks_user_doc_type",
        "document_chunks",
        ["user_id", "doc_type"],
    )
    op.create_index(
        "ix_document_chunks_user_filename",
        "document_chunks",
        ["user_id", "source_filename"],
    )
    op.create_index(
        "ix_document_chunks_user_id",
        "document_chunks",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_user_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_user_filename", table_name="document_chunks")
    op.drop_index("ix_document_chunks_user_doc_type", table_name="document_chunks")
    op.drop_table("document_chunks")
