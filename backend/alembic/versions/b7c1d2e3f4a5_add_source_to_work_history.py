"""add source + source_url to work_history_entries

Revision ID: b7c1d2e3f4a5
Revises: 45ca64ce5f2e
Create Date: 2026-05-17 00:00:00.000000

Adds provenance fields used by the GitHub/LinkedIn import endpoints (#108).
- ``source`` ("manual" | "github" | "linkedin") — defaults to "manual" so all
  existing rows are backfilled correctly.
- ``source_url`` — optional external identifier used to dedupe re-imports
  (e.g. a GitHub repo html_url).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: str | None = "45ca64ce5f2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_history_entries",
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
    )
    op.add_column(
        "work_history_entries",
        sa.Column("source_url", sa.String(500), nullable=True),
    )
    # Partial UNIQUE index on (user_id, source_url) — only enforced where
    # source_url is not null. This prevents the duplicate-row race between two
    # concurrent /import/github calls (the router catches IntegrityError and
    # treats it as "another concurrent call already created it"). The partial
    # predicate avoids treating every manual row (source_url IS NULL) as
    # duplicating every other manual row.
    op.create_index(
        "ix_work_history_user_source_url_unique",
        "work_history_entries",
        ["user_id", "source_url"],
        unique=True,
        postgresql_where=sa.text("source_url IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_work_history_user_source_url_unique",
        table_name="work_history_entries",
    )
    op.drop_column("work_history_entries", "source_url")
    op.drop_column("work_history_entries", "source")
