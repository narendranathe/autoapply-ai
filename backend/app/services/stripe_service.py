"""
Stripe service — customer creation, checkout/portal sessions, webhook handling.

This is the single source of truth for all Stripe API interactions. Routers
import from here; nothing else talks to the Stripe SDK directly.

Webhook contract:
    handle_webhook_event(payload_bytes, signature_header, db) -> dict

Sub-events handled:
    customer.subscription.created  → upsert Subscription, plan from price ID
    customer.subscription.updated  → mirror plan/status/period/cancel_at_period_end
    customer.subscription.deleted  → mark Subscription canceled, plan free
    invoice.payment_failed         → mark Subscription past_due

All other event types are returned with status="ignored" so Stripe stops
retrying them. Signature verification is mandatory — no signature, no event.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import stripe
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.subscription import Plan, Subscription, SubscriptionStatus
from app.models.user import User

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _client() -> Any:
    """Configure the Stripe SDK at call time so test patches take effect."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def _to_dt(epoch: int | None) -> datetime | None:
    """Convert a Stripe epoch-seconds value to a UTC datetime (or None)."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC)


def _plan_from_price(price_id: str | None) -> Plan:
    """Map a Stripe price ID to our internal Plan enum."""
    if price_id and price_id == settings.STRIPE_PRICE_PRO:
        return Plan.pro
    if price_id and price_id == settings.STRIPE_PRICE_TEAM:
        return Plan.team
    return Plan.free


_STATUS_MAP: dict[str, SubscriptionStatus] = {
    "active": SubscriptionStatus.active,
    "trialing": SubscriptionStatus.trialing,
    "past_due": SubscriptionStatus.past_due,
    "canceled": SubscriptionStatus.canceled,
    "unpaid": SubscriptionStatus.unpaid,
    # Edge states — treat as past_due so users see "fix your payment" UX
    "incomplete": SubscriptionStatus.past_due,
    "incomplete_expired": SubscriptionStatus.canceled,
    "paused": SubscriptionStatus.past_due,
}


def _status_from_stripe(status_str: str) -> SubscriptionStatus:
    """Map a Stripe subscription status to our internal enum."""
    return _STATUS_MAP.get(status_str, SubscriptionStatus.active)


def _extract_price_id(sub_obj: dict[str, Any]) -> str | None:
    """Pull the first price ID off a Stripe subscription event object."""
    items = sub_obj.get("items", {}).get("data", [])
    if not items:
        return None
    price = items[0].get("price") or {}
    return price.get("id")


async def _find_subscription_by_customer(
    db: AsyncSession, customer_id: str
) -> tuple[Subscription | None, User | None]:
    """Locate the User + Subscription rows tied to a given Stripe customer ID."""
    user_result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return None, None
    sub_result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    return sub_result.scalar_one_or_none(), user


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


async def get_or_create_customer(user: User, db: AsyncSession) -> str:
    """
    Return the user's Stripe customer ID, creating one if it doesn't exist.

    The customer ID is persisted on User.stripe_customer_id so the second call
    is a no-op DB read.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    sdk = _client()
    customer = sdk.Customer.create(
        metadata={"user_id": str(user.id), "clerk_id": user.clerk_id},
    )
    user.stripe_customer_id = customer["id"]
    await db.flush()
    logger.info(f"Created Stripe customer {customer['id']} for user {user.id}")
    return customer["id"]


async def create_checkout_session(
    user: User,
    price_id: str,
    db: AsyncSession,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for a subscription."""
    customer_id = await get_or_create_customer(user, db)
    sdk = _client()
    session = sdk.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url or settings.STRIPE_CHECKOUT_SUCCESS_URL,
        cancel_url=cancel_url or settings.STRIPE_CHECKOUT_CANCEL_URL,
        metadata={"user_id": str(user.id)},
    )
    return {"id": session["id"], "url": session["url"]}


async def create_portal_session(
    user: User,
    db: AsyncSession,
    return_url: str | None = None,
) -> dict[str, Any]:
    """
    Create a Stripe billing portal session.

    The portal lets the user update payment methods, cancel, or change plans
    without us having to build that UI ourselves.
    """
    customer_id = await get_or_create_customer(user, db)
    sdk = _client()
    session = sdk.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url or settings.STRIPE_BILLING_PORTAL_RETURN_URL,
    )
    return {"url": session["url"]}


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------


async def _upsert_subscription_from_event(
    db: AsyncSession, sub_obj: dict[str, Any]
) -> Subscription | None:
    """Create or update a Subscription row from a Stripe subscription event."""
    customer_id = sub_obj.get("customer")
    if not customer_id:
        logger.warning("Subscription event missing customer ID, skipping")
        return None

    existing, user = await _find_subscription_by_customer(db, customer_id)
    if user is None:
        logger.warning(f"No user found for Stripe customer {customer_id}, skipping")
        return None

    plan = _plan_from_price(_extract_price_id(sub_obj))
    status = _status_from_stripe(sub_obj.get("status", "active"))

    if existing is None:
        existing = Subscription(
            user_id=user.id,
            stripe_customer_id=customer_id,
        )
        db.add(existing)

    existing.stripe_subscription_id = sub_obj.get("id")
    existing.stripe_customer_id = customer_id
    existing.plan = plan
    existing.status = status
    existing.current_period_start = _to_dt(sub_obj.get("current_period_start"))
    existing.current_period_end = _to_dt(sub_obj.get("current_period_end"))
    existing.cancel_at_period_end = bool(sub_obj.get("cancel_at_period_end", False))
    await db.flush()
    return existing


async def _on_subscription_created(db: AsyncSession, event: dict[str, Any]) -> None:
    await _upsert_subscription_from_event(db, event["data"]["object"])


async def _on_subscription_updated(db: AsyncSession, event: dict[str, Any]) -> None:
    await _upsert_subscription_from_event(db, event["data"]["object"])


async def _on_subscription_deleted(db: AsyncSession, event: dict[str, Any]) -> None:
    """When a subscription is canceled outright, downgrade to free."""
    sub_obj = event["data"]["object"]
    customer_id = sub_obj.get("customer")
    if not customer_id:
        return
    existing, _user = await _find_subscription_by_customer(db, customer_id)
    if existing is None:
        return
    existing.status = SubscriptionStatus.canceled
    existing.plan = Plan.free
    existing.cancel_at_period_end = False
    await db.flush()


async def _on_payment_failed(db: AsyncSession, event: dict[str, Any]) -> None:
    """Mark the user past_due so feature gates can prompt them to fix payment."""
    invoice = event["data"]["object"]
    customer_id = invoice.get("customer")
    if not customer_id:
        return
    existing, _user = await _find_subscription_by_customer(db, customer_id)
    if existing is None:
        return
    existing.status = SubscriptionStatus.past_due
    await db.flush()


_HANDLERS = {
    "customer.subscription.created": _on_subscription_created,
    "customer.subscription.updated": _on_subscription_updated,
    "customer.subscription.deleted": _on_subscription_deleted,
    "invoice.payment_failed": _on_payment_failed,
}


async def handle_webhook_event(
    payload: bytes,
    signature: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Verify a Stripe webhook signature and dispatch the event to a handler.

    Raises:
        ValueError: if STRIPE_WEBHOOK_SECRET is unset, the signature header
            is missing, or signature verification fails.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")
    if not signature:
        raise ValueError("Missing Stripe-Signature header")

    sdk = _client()
    event = sdk.Webhook.construct_event(
        payload=payload,
        sig_header=signature,
        secret=settings.STRIPE_WEBHOOK_SECRET,
    )

    raw_type = event.get("type") if isinstance(event, dict) else event["type"]
    if not isinstance(raw_type, str):
        raise ValueError("Stripe event missing 'type' field")
    event_type: str = raw_type
    handler = _HANDLERS.get(event_type)
    if handler is None:
        logger.info(f"Stripe webhook event '{event_type}' ignored (no handler)")
        return {"status": "ignored", "type": event_type}

    event_dict = event if isinstance(event, dict) else dict(event)
    await handler(db, event_dict)
    logger.info(f"Stripe webhook event '{event_type}' processed")
    return {"status": "ok", "type": event_type}
