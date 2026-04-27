"""merge_heads_for_story_entries

Revision ID: a4218c2ef784
Revises: 45ca64ce5f2e, add_tailored_resumes
Create Date: 2026-04-27 14:14:28.865455

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a4218c2ef784"
down_revision: str | None = ("45ca64ce5f2e", "add_tailored_resumes")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
