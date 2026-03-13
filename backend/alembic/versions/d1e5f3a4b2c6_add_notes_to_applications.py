"""add notes column to applications table

Revision ID: d1e5f3a4b2c6
Revises: c9f4a2b3d1e5
Create Date: 2026-03-13 00:00:00.000000

Adds a free-form notes field so users can record interview feedback,
contact names, follow-up reminders, etc. for each application.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e5f3a4b2c6"
down_revision: str | None = "c9f4a2b3d1e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column(
            "notes", sa.Text(), nullable=True, comment="Free-form notes about this application"
        ),
    )


def downgrade() -> None:
    op.drop_column("applications", "notes")
