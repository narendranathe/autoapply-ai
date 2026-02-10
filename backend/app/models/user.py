"""
User model.
"""

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.application import Application


from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clerk_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    github_username: Mapped[str | None] = mapped_column(String(255))
    encrypted_github_token: Mapped[str | None] = mapped_column(Text)
    resume_repo_name: Mapped[str] = mapped_column(String(255), default="resume-vault")
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    encrypted_llm_api_key: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    total_resumes_generated: Mapped[int] = mapped_column(default=0)
    total_applications_tracked: Mapped[int] = mapped_column(default=0)

    # Relationships
    applications: Mapped[list["Application"]] = relationship(back_populates="user")
