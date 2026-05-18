"""
Subscription model — tracks Stripe billing state per user.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Plan(StrEnum):
    free = "free"
    pro = "pro"
    team = "team"


class SubscriptionStatus(StrEnum):
    active = "active"
    trialing = "trialing"
    past_due = "past_due"
    canceled = "canceled"
    unpaid = "unpaid"


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    plan: Mapped[Plan] = mapped_column(
        Enum(Plan, name="plan_enum", native_enum=True),
        nullable=False,
        default=Plan.free,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status_enum", native_enum=True),
        nullable=False,
        default=SubscriptionStatus.active,
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="subscription")
