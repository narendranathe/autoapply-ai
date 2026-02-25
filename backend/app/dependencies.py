"""
FastAPI dependency injection.

These are the "providers" that inject database sessions, Redis clients,
and authenticated users into route handlers. FastAPI calls these
automatically based on function parameter types.

Usage in routes:
    @router.get("/me")
    async def get_me(
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        ...
"""

from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.base import async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session per request.

    Uses async context manager to ensure the session is properly
    closed after the request completes, even if an error occurs.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    Provide a Redis client per request.

    Used for: rate limiting counters, JD embedding cache,
    circuit breaker state, session tracking.
    """
    client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        yield client
    finally:
        await client.aclose()


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    x_clerk_user_id: str | None = Header(None, alias="X-Clerk-User-Id"),
):
    """
    Resolve the authenticated user from the Clerk user ID header.

    The Clerk frontend SDK sends ``X-Clerk-User-Id`` automatically on every
    fetch request once the user is signed in.

    - If the header is present → look up User by clerk_id (active users only).
    - In development with no header → fall back to the first user in the DB
      so local testing doesn't require a full auth setup.
    - In production with no header → 401 Unauthorized.
    """
    from app.models.user import User  # late import to avoid circular deps

    if x_clerk_user_id:
        result = await db.execute(
            select(User).where(
                User.clerk_id == x_clerk_user_id,
                User.is_active.is_(True),
            )
        )
        user = result.scalar_one_or_none()
        if user:
            return user
        # Header present but no matching user → don't fall through to dev mode
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    if settings.is_development:
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Authentication required. " "Send the X-Clerk-User-Id header from your Clerk session."
        ),
    )
