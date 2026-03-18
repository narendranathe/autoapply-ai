"""
UserProviderConfig model.

Stores per-user LLM provider configuration: encrypted API key, optional model
override, and whether the provider is enabled.

One row per (user, provider) pair — enforced by a unique constraint so that
client code can upsert safely.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserProviderConfig(Base, TimestampMixin):
    __tablename__ = "user_provider_configs"

    __table_args__ = (UniqueConstraint("user_id", "provider_name", name="uq_user_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="anthropic | openai | kimi | ollama",
    )
    encrypted_api_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Fernet-encrypted API key — decrypted in-memory only.",
    )
    model_override: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Optional model ID to use instead of the provider default.",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether this provider is active for the user.",
    )

    # ── Relationships ─────────────────────────────────────
    user: Mapped["User"] = relationship(back_populates="provider_configs")

    def __repr__(self) -> str:
        return (
            f"<UserProviderConfig user={self.user_id} "
            f"provider={self.provider_name} enabled={self.is_enabled}>"
        )
