"""PortalScanCache — cached structured JD data from ATS job boards."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PortalScanCache(TimestampMixin, Base):
    __tablename__ = "portal_scan_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_id: Mapped[str] = mapped_column(String(200), nullable=False)
    board_type: Mapped[str] = mapped_column(String(50), nullable=False)
    job_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    compensation_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compensation_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scan_result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint(
            "board_type IN ('greenhouse','lever','ashby','wellfound','manual')",
            name="ck_portal_scan_board_type",
        ),
        UniqueConstraint("user_id", "board_type", "job_id", name="uq_portal_scan_user_board_job"),
        Index("ix_portal_scan_user_company", "user_id", "company_name"),
    )

    def __repr__(self) -> str:
        return f"<PortalScanCache id={self.id} board={self.board_type} job_id={self.job_id}>"
