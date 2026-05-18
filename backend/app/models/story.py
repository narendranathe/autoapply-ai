"""StoryEntry — STAR narrative bank for interview prep and resume tailoring."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_VALID_DOMAINS = (
    "'testing_ci_cd'",
    "'orchestration'",
    "'architecture_finops'",
    "'streaming_realtime'",
    "'ml_ai_platform'",
    "'cloud_infra'",
    "'leadership_ownership'",
    "'sql_data_modeling'",
    "'data_quality_observability'",
    "'semantic_layer_governance'",
)
_DOMAIN_CHECK = f"domain IN ({', '.join(_VALID_DOMAINS)})"


class StoryEntry(TimestampMixin, Base):
    __tablename__ = "story_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    situation: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(150), nullable=False)
    result_text: Mapped[str] = mapped_column(String(150), nullable=False)
    reflection: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_DOMAIN_CHECK, name="ck_story_entries_domain"),
        CheckConstraint(
            "quality_score >= 0.0 AND quality_score <= 1.0",
            name="ck_story_entries_quality_score",
        ),
        Index("ix_story_entries_user_domain", "user_id", "domain"),
        Index("ix_story_entries_user_quality", "user_id", "quality_score"),
    )

    def __repr__(self) -> str:
        return f"<StoryEntry id={self.id} domain={self.domain} score={self.quality_score}>"
