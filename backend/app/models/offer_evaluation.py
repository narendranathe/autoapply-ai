"""OfferEvaluation — dimensional A-F offer scoring results."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OfferEvaluation(TimestampMixin, Base):
    __tablename__ = "offer_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    jd_text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[str] = mapped_column(String(200), nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    overall_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "overall_grade IN ('A','B','C','D','F')",
            name="ck_offer_eval_grade",
        ),
        CheckConstraint(
            "overall_score >= 0.0 AND overall_score <= 100.0",
            name="ck_offer_eval_score",
        ),
        UniqueConstraint("user_id", "jd_text_hash", name="uq_offer_eval_user_jd"),
        Index("ix_offer_eval_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<OfferEvaluation id={self.id} grade={self.overall_grade} score={self.overall_score}>"
        )
