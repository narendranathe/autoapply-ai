"""add_portal_scan_cache

Revision ID: b37e76e0b288
Revises: 3ca41429132c
Create Date: 2026-04-27 14:45:40.376924

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  # noqa: F401

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b37e76e0b288"
down_revision: str | None = "3ca41429132c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_scan_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("job_id", sa.String(200), nullable=False),
        sa.Column("board_type", sa.String(50), nullable=False),
        sa.Column("job_url", sa.String(2048), nullable=False),
        sa.Column("compensation_min", sa.Integer(), nullable=True),
        sa.Column("compensation_max", sa.Integer(), nullable=True),
        sa.Column("scan_result", postgresql.JSONB(), nullable=False),
        sa.Column(
            "schema_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_stale",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
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
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "board_type IN ('greenhouse','lever','ashby','wellfound','manual')",
            name="ck_portal_scan_board_type",
        ),
        sa.UniqueConstraint(
            "user_id", "board_type", "job_id", name="uq_portal_scan_user_board_job"
        ),
    )
    op.create_index("ix_portal_scan_user_id", "portal_scan_cache", ["user_id"])
    op.create_index(
        "ix_portal_scan_user_company",
        "portal_scan_cache",
        ["user_id", "company_name"],
    )
    op.execute(
        "CREATE INDEX ix_portal_scan_stale ON portal_scan_cache (user_id) WHERE is_stale = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_portal_scan_stale")
    op.drop_index("ix_portal_scan_user_company", table_name="portal_scan_cache")
    op.drop_index("ix_portal_scan_user_id", table_name="portal_scan_cache")
    op.drop_table("portal_scan_cache")
