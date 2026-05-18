"""
UsageRecord model — tracks monthly feature usage per user for plan enforcement.
"""

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class UsageRecord(Base, TimestampMixin):
    __tablename__ = "usage_records"

    __table_args__ = (UniqueConstraint("user_id", "period_start", name="uq_usage_user_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    resume_tailors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qa_drafts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cover_letters_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="usage_records")
