"""add subscription and usage tracking

Revision ID: b6d2e4f8a1c3
Revises: 45ca64ce5f2e
Create Date: 2026-03-30 00:00:00.000000

Phase A of Stripe billing integration:
- plan_enum / subscription_status_enum Postgres enums
- subscriptions table (one-to-one with users)
- usage_records table (one-per-billing-period per user)
- stripe_customer_id column on users
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b6d2e4f8a1c3"
down_revision: str | None = "45ca64ce5f2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

plan_enum = postgresql.ENUM("free", "pro", "team", name="plan_enum", create_type=False)
subscription_status_enum = postgresql.ENUM(
    "active",
    "trialing",
    "past_due",
    "canceled",
    "unpaid",
    name="subscription_status_enum",
    create_type=False,
)


def upgrade() -> None:
    # --- enums ---
    sa.Enum("free", "pro", "team", name="plan_enum").create(op.get_bind(), checkfirst=True)
    sa.Enum(
        "active",
        "trialing",
        "past_due",
        "canceled",
        "unpaid",
        name="subscription_status_enum",
    ).create(op.get_bind(), checkfirst=True)

    # --- subscriptions ---
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("plan", plan_enum, nullable=False, server_default="free"),
        sa.Column("status", subscription_status_enum, nullable=False, server_default="active"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_stripe_customer_id", "subscriptions", ["stripe_customer_id"])
    op.create_index(
        "ix_subscriptions_stripe_subscription_id", "subscriptions", ["stripe_subscription_id"]
    )

    # --- usage_records ---
    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("resume_tailors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qa_drafts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cover_letters_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "period_start", name="uq_usage_user_period"),
    )
    op.create_index("ix_usage_records_user_id", "usage_records", ["user_id"])

    # --- users.stripe_customer_id ---
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"])


def downgrade() -> None:
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "stripe_customer_id")

    op.drop_index("ix_usage_records_user_id", table_name="usage_records")
    op.drop_table("usage_records")

    op.drop_index("ix_subscriptions_stripe_subscription_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_stripe_customer_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    sa.Enum(name="subscription_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="plan_enum").drop(op.get_bind(), checkfirst=True)
