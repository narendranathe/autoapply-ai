"""merge_heads_for_story_entries

Revision ID: a4218c2ef784
Revises: 45ca64ce5f2e
Create Date: 2026-04-27 14:14:28.865455

PR #150 merge note: previously referenced ``add_tailored_resumes`` as a
second parent, but that branch was never merged to main. Dropping the
phantom parent so the migration graph has a single resolvable chain.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a4218c2ef784"
down_revision: str | None = "45ca64ce5f2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
