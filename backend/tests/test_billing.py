"""Tests for /api/v1/billing — Stripe checkout, portal, subscription, webhook (issue #93)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Plan, Subscription, SubscriptionStatus
from app.models.user import User

# ---------------------------------------------------------------------------
# Test 1: GET /subscription returns free plan when no Subscription row exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_subscription_returns_free_plan(client: AsyncClient, test_user: User):
    """A user with no Subscription row gets plan=free, status=active."""
    response = await client.get(
        "/api/v1/billing/subscription",
        headers={"X-Clerk-User-Id": test_user.clerk_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["plan"] == Plan.free.value
    assert data["status"] == SubscriptionStatus.active.value
    assert data["cancel_at_period_end"] is False
    assert data["current_period_end"] is None


# ---------------------------------------------------------------------------
# Test 2: webhook customer.subscription.created upserts a Subscription row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_creates_subscription_row(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
):
    """A signed customer.subscription.created event creates a Subscription row on pro plan."""
    customer_id = f"cus_{uuid.uuid4().hex[:14]}"
    test_user.stripe_customer_id = customer_id
    await db_session.flush()

    pro_price = "price_pro_test_123"
    fake_event = {
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_test_abc",
                "customer": customer_id,
                "status": "active",
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_702_000_000,
                "cancel_at_period_end": False,
                "items": {"data": [{"price": {"id": pro_price}}]},
            }
        },
    }

    with (
        patch("app.services.stripe_service.settings") as mock_settings,
        patch("app.services.stripe_service.stripe.Webhook.construct_event") as mock_construct,
    ):
        mock_settings.STRIPE_SECRET_KEY = "sk_test_dummy"
        mock_settings.STRIPE_WEBHOOK_SECRET = "whsec_dummy"
        mock_settings.STRIPE_PRICE_PRO = pro_price
        mock_settings.STRIPE_PRICE_TEAM = "price_team_test"
        mock_construct.return_value = fake_event

        response = await client.post(
            "/api/v1/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "t=1,v1=fake"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["type"] == "customer.subscription.created"

    result = await db_session.execute(
        select(Subscription).where(Subscription.user_id == test_user.id)
    )
    sub = result.scalar_one_or_none()
    assert sub is not None
    assert sub.plan == Plan.pro
    assert sub.status == SubscriptionStatus.active
    assert sub.stripe_subscription_id == "sub_test_abc"
    assert sub.cancel_at_period_end is False


# ---------------------------------------------------------------------------
# Test 3: POST /checkout without auth returns 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_requires_auth(client: AsyncClient):
    """Calling /checkout with no auth headers must be rejected with 401."""
    response = await client.post(
        "/api/v1/billing/checkout",
        json={"plan": "pro"},
    )
    assert response.status_code == 401, response.text
