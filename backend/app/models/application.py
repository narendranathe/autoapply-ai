"""
Application model — tracks every resume version sent to each company.

Each row represents one application. The resume itself lives in GitHub
(referenced by git_path). We only store metadata here.

The similarity_score and similar_to_application_id enable the
"smart reuse" feature — when a user applies to a similar role,
we suggest tweaking a previous resume instead of starting fresh.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # ── Job Information ───────────────────────────────────
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    role_title: Mapped[str] = mapped_column(String(255))
    job_url: Mapped[str | None] = mapped_column(String(2048))
    platform: Mapped[str | None] = mapped_column(
        String(50), comment="linkedin | greenhouse | workday | lever | manual"
    )
    jd_hash: Mapped[str] = mapped_column(
        String(64),
        index=True,
        comment="SHA-256 of normalized job description text. Used for dedup.",
    )

    # ── Resume Version Control ────────────────────────────
    git_path: Mapped[str] = mapped_column(
        String(512), comment="Path in GitHub repo: applications/google-swe-2025-02-09/"
    )
    base_resume_commit_sha: Mapped[str | None] = mapped_column(
        String(40), comment="Git SHA of the base template used"
    )
    tailored_resume_commit_sha: Mapped[str | None] = mapped_column(
        String(40), comment="Git SHA of the tailored version"
    )

    # ── Smart Reuse ───────────────────────────────────────
    similarity_score: Mapped[float | None] = mapped_column(
        Float, comment="Cosine similarity to most similar previous application (0.0-1.0)"
    )
    similar_to_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id"),
        comment="Reference to the most similar previous application",
    )
    rewrite_strategy: Mapped[str | None] = mapped_column(
        String(50), comment="slight_tweak | moderate | ground_up"
    )

    # ── Status Tracking ───────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(50),
        default="draft",
        index=True,
        comment="draft | tailored | applied | rejected | interview | offer",
    )
    changes_summary: Mapped[str | None] = mapped_column(
        Text, comment="Human-readable summary of what the LLM changed"
    )

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="applications")

    def __repr__(self) -> str:
        return f"<Application {self.company_name} - {self.role_title} ({self.status})>"
