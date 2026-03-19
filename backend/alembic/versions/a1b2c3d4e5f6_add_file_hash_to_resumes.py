"""add file_hash to resumes

Revision ID: a1b2c3d4e5f6
Revises: f3a7b1c2d4e5
Create Date: 2026-03-18 00:00:00.000000

Adds a SHA-256 file_hash column to the resumes table for content-based
deduplication. When a file with the same hash already exists in the vault
for the same user, the upload is skipped (already_synced).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f3a7b1c2d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resumes",
        sa.Column("file_hash", sa.String(64), nullable=True),
    )
    op.create_index("ix_resumes_file_hash", "resumes", ["file_hash"])


def downgrade() -> None:
    op.drop_index("ix_resumes_file_hash", table_name="resumes")
    op.drop_column("resumes", "file_hash")
