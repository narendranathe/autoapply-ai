"""merge_profile_fields_and_file_hash

Revision ID: 45ca64ce5f2e
Revises: a1b2c3d4e5f6, a4b8c2d6e1f9
Create Date: 2026-03-20 15:06:20.131421

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "45ca64ce5f2e"
down_revision: str | None = ("a1b2c3d4e5f6", "a4b8c2d6e1f9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
