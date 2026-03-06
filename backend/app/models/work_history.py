"""
Work History model — stores structured employment + education history per user.

Used for:
  1. Grounding LLM answer generation with real facts (no hallucination)
  2. Resume bullet generation with accurate metrics
  3. Skills extraction for ATS scoring
"""

import uuid

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WorkHistoryEntry(Base, TimestampMixin):
    __tablename__ = "work_history_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # --- Entry type ---
    entry_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="work"
    )  # "work" | "education" | "certification"

    # --- Role identity ---
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[str] = mapped_column(String(30), nullable=False)  # "July 2024"
    end_date: Mapped[str | None] = mapped_column(String(30), nullable=True)  # None = current
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Content ---
    bullets: Mapped[list] = mapped_column(JSON, default=list)  # list[str] achievement bullets
    technologies: Mapped[list] = mapped_column(JSON, default=list)  # list[str] tech/skills
    team_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Display order (0 = most recent, ascending) ---
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        end = "present" if self.is_current else (self.end_date or "?")
        return f"<WorkHistoryEntry {self.role_title} @ {self.company_name} {self.start_date}–{end}>"

    def to_text_block(self) -> str:
        """Format as a dense text block for LLM injection."""
        date_range = f"{self.start_date} – {'present' if self.is_current else self.end_date or '?'}"
        status = "CURRENT" if self.is_current else "PAST"
        lines = [f"{status} ROLE: {self.role_title} at {self.company_name} ({date_range})"]
        for b in self.bullets:
            lines.append(f"• {b}")
        if self.technologies:
            lines.append(f"Technologies: {', '.join(self.technologies)}")
        return "\n".join(lines)
