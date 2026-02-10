"""
Audit log — immutable record of every significant action.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Who
    user_hash: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)

    # What
    action: Mapped[str] = mapped_column(String(100), index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text)

    # Outcome
    success: Mapped[bool] = mapped_column(default=True)
    error_type: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)

    # Performance
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    # When
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
