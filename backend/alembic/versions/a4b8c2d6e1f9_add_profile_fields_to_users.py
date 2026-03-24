"""add profile fields to users

Revision ID: a4b8c2d6e1f9
Revises: f3a7b1c2d4e5
Create Date: 2026-03-20 00:00:00.000000

Adds 14 nullable profile columns to the users table:
first_name, last_name, phone, city, state, zip_code, country,
linkedin_url, github_url, portfolio_url, degree, years_experience,
salary, sponsorship.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b8c2d6e1f9"
down_revision: str | None = "f3a7b1c2d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(50), nullable=True))
    op.add_column("users", sa.Column("city", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("state", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("zip_code", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("country", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("linkedin_url", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("github_url", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("portfolio_url", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("degree", sa.String(200), nullable=True))
    op.add_column("users", sa.Column("years_experience", sa.String(50), nullable=True))
    op.add_column("users", sa.Column("salary", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("sponsorship", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "sponsorship")
    op.drop_column("users", "salary")
    op.drop_column("users", "years_experience")
    op.drop_column("users", "degree")
    op.drop_column("users", "portfolio_url")
    op.drop_column("users", "github_url")
    op.drop_column("users", "linkedin_url")
    op.drop_column("users", "country")
    op.drop_column("users", "zip_code")
    op.drop_column("users", "state")
    op.drop_column("users", "city")
    op.drop_column("users", "phone")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
