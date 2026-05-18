"""merge pr150 with main heads

Revision ID: 2988114ea6a5
Revises: b37e76e0b288, b6d2e4f8a1c3, b7c1d2e3f4a5, b7c2d4e6f8a1
Create Date: 2026-05-18 01:41:52.845889

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "2988114ea6a5"
down_revision: str | None = ("b37e76e0b288", "b6d2e4f8a1c3", "b7c1d2e3f4a5", "b7c2d4e6f8a1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
