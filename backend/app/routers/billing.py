"""
Billing router — Stripe checkout, portal, subscription state, webhooks.

Endpoints
---------
POST /api/v1/billing/checkout       Create a Checkout Session for Pro/Team
POST /api/v1/billing/portal         Create a Stripe billing portal session
GET  /api/v1/billing/subscription   Return current plan + status (free if none)
POST /api/v1/billing/webhook        Stripe webhook receiver (no auth, sig-verified)

Auth
----
- /checkout, /portal, /subscription require a Clerk-authenticated user
- /webhook is intentionally unauthenticated — Stripe verifies via signature
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.subscription import Plan, Subscription, SubscriptionStatus
from app.models.user import User
from app.services import stripe_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    plan: Literal["pro", "team"]
    success_url: str | None = None
    cancel_url: str | None = None


class PortalRequest(BaseModel):
    return_url: str | None = None


class SubscriptionResponse(BaseModel):
    plan: str
    status: str
    cancel_at_period_end: bool
    current_period_end: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _price_for_plan(plan: str) -> str:
    if plan == "pro":
        price = settings.STRIPE_PRICE_PRO
    elif plan == "team":
        price = settings.STRIPE_PRICE_TEAM
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown plan '{plan}'",
        )
    if not price:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Plan '{plan}' is not configured on the server.",
        )
    return price


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/checkout")
async def create_checkout(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for the requested plan."""
    price_id = _price_for_plan(payload.plan)
    return await stripe_service.create_checkout_session(
        user=user,
        price_id=price_id,
        db=db,
        success_url=payload.success_url,
        cancel_url=payload.cancel_url,
    )


@router.post("/portal")
async def create_portal(
    payload: PortalRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a Stripe billing portal session for the authenticated user."""
    return_url = payload.return_url if payload else None
    return await stripe_service.create_portal_session(user=user, db=db, return_url=return_url)


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    """Return the user's current plan/status. Defaults to free when no row exists."""
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    if sub is None:
        return SubscriptionResponse(
            plan=Plan.free.value,
            status=SubscriptionStatus.active.value,
            cancel_at_period_end=False,
            current_period_end=None,
        )
    return SubscriptionResponse(
        plan=sub.plan.value,
        status=sub.status.value,
        cancel_at_period_end=sub.cancel_at_period_end,
        current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Stripe webhook receiver.

    Authenticated solely via Stripe-Signature header (HMAC of request body
    against STRIPE_WEBHOOK_SECRET). No Clerk auth — Stripe calls this from
    its own infrastructure with no user context.
    """
    payload = await request.body()
    try:
        return await stripe_service.handle_webhook_event(payload, stripe_signature, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
