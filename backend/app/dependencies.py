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

import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.base import async_session_factory
from app.services.llm_gateway import LLMGateway

if TYPE_CHECKING:
    from app.models.user import User

# Module-level JWKS cache: {"keys": list, "fetched_at": float}
_jwks_cache: dict[str, Any] = {}
_JWKS_TTL = 900  # seconds (15 minutes)


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


async def _fetch_clerk_jwks() -> list[dict]:
    url = f"{settings.CLERK_FRONTEND_API_URL}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        keys = resp.json()["keys"]

    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = time.monotonic()
    return keys  # type: ignore[return-value]


async def _get_clerk_jwks(force_refresh: bool = False) -> list[dict]:
    """Fetch and cache Clerk's JWKS public keys (TTL = ``_JWKS_TTL`` seconds)."""
    now = time.monotonic()
    if not force_refresh and _jwks_cache and (now - _jwks_cache.get("fetched_at", 0)) < _JWKS_TTL:
        return _jwks_cache["keys"]  # type: ignore[return-value]
    return await _fetch_clerk_jwks()


def _find_jwk_by_kid(keys: list[dict], kid: str) -> dict | None:
    return next((k for k in keys if k.get("kid") == kid), None)


async def _resolve_jwk_for_kid(kid: str) -> dict | None:
    """Return the JWK matching ``kid``, force-refreshing once on cache miss."""
    keys = await _get_clerk_jwks()
    key = _find_jwk_by_kid(keys, kid)
    if key is not None:
        return key
    keys = await _get_clerk_jwks(force_refresh=True)
    return _find_jwk_by_kid(keys, kid)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_clerk_user_id: str | None = Header(None, alias="X-Clerk-User-Id"),
) -> "User":
    """
    Resolve the authenticated user.

    Priority:
    1. If CLERK_FRONTEND_API_URL is configured: validate the
       ``Authorization: Bearer <token>`` JWT against Clerk's JWKS.
    2. Otherwise fall back to ``X-Clerk-User-Id`` header (dev / extension flow).
    3. In development with no header: resolve the user whose ``clerk_id`` matches
       ``settings.DEV_TEST_USER_ID``. If that setting is empty, return 401
       (no credentials → unauthenticated).
    """
    from app.models.user import User  # late import to avoid circular deps

    clerk_id: str | None = None

    # ── 1. JWT path (production) ──────────────────────────────────────────
    if settings.CLERK_FRONTEND_API_URL:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                header = jwt.get_unverified_header(token)
                kid = header.get("kid")
                if not kid:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired authentication token.",
                    )
                jwk = await _resolve_jwk_for_kid(kid)
                if jwk is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired authentication token.",
                    )
                options = {"verify_aud": bool(settings.CLERK_JWT_AUDIENCE)}
                payload = jwt.decode(
                    token,
                    jwk,
                    algorithms=["RS256"],
                    audience=settings.CLERK_JWT_AUDIENCE or None,
                    options=options,
                )
                clerk_id = payload.get("sub")
            except JWTError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired authentication token.",
                ) from exc

    # ── 2. Header path (extension / dev) ─────────────────────────────────
    if clerk_id is None and x_clerk_user_id:
        clerk_id = x_clerk_user_id

    if clerk_id:
        result = await db.execute(
            select(User).where(
                User.clerk_id == clerk_id,
                User.is_active.is_(True),
            )
        )
        user = result.scalar_one_or_none()
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    # ── 3. Dev fallback ───────────────────────────────────────────────────
    if settings.is_development:
        if not settings.DEV_TEST_USER_ID:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Dev auth bypass requires DEV_TEST_USER_ID to be set to a "
                    "valid clerk_id in your .env. Set it or send a Clerk JWT / "
                    "X-Clerk-User-Id header."
                ),
            )
        result = await db.execute(
            select(User).where(
                User.clerk_id == settings.DEV_TEST_USER_ID,
                User.is_active.is_(True),
            )
        )
        user = result.scalar_one_or_none()
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"DEV_TEST_USER_ID '{settings.DEV_TEST_USER_ID}' does not match "
                "any active user in the database."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Authentication required. "
            "Send Authorization: Bearer <token> from your Clerk session."
        ),
    )


def get_llm_gateway() -> LLMGateway:
    """Provide an LLMGateway instance as a FastAPI dependency."""
    return LLMGateway()
