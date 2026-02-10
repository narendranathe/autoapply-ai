"""
FastAPI dependency injection.

These are the "providers" that inject database sessions, Redis clients,
and authenticated users into route handlers. FastAPI calls these
automatically based on function parameter types.

Usage in routes:
    @router.get("/me")
    async def get_me(db: AsyncSession = Depends(get_db)):
        ...
"""

from collections.abc import AsyncGenerator

from redis.asyncio import Redis
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
