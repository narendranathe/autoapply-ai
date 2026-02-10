"""
Application model — tracks job applications.
"""

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User


from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Job details
    company_name: Mapped[str] = mapped_column(String(255), index=True)
    role_title: Mapped[str] = mapped_column(String(255))
    job_url: Mapped[str | None] = mapped_column(String(2048))
    platform: Mapped[str | None] = mapped_column(String(50))

    # Resume tracking
    git_path: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="applications")
