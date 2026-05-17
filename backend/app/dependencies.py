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

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from jose import jwt
from jose.exceptions import JOSEError
from loguru import logger
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

# Negative cache for kids that miss even after a forced refresh. Prevents an
# attacker from amplifying random-kid requests into upstream JWKS fetches.
_jwks_unknown_kids: dict[str, float] = {}
_JWKS_UNKNOWN_KID_TTL = 60  # seconds
# Hard cap on the negative cache to bound memory under random-kid spam.
_JWKS_UNKNOWN_KIDS_MAX = 1024

# Coalesce concurrent force-refreshes so we hit Clerk at most once per stampede.
_jwks_refresh_lock = asyncio.Lock()

# Clerk signs JWTs with RS256 only. This allowlist is the single security
# boundary that blocks algorithm-confusion attacks (HS256, none, etc.) and
# is exported so regression tests pin the exact same value.
_CLERK_JWT_ALGORITHMS = ["RS256"]


def _warn_if_clerk_url_missing() -> bool:
    """
    Emit a clear log warning when CLERK_FRONTEND_API_URL is unset in a
    non-production environment (Issue #90).

    Production deploys without the URL are already refused at startup by
    the config validator in ``app.config`` — this helper exists for
    dev / staging / test, where the documented header-bypass is still
    permitted and we want it to be loud in CI logs.

    Returns:
        ``True`` if a warning was emitted (caller / tests can assert on
        the return value without needing to capture log output, which is
        fragile under loguru monkey-patching).
    """
    if not settings.CLERK_FRONTEND_API_URL and not settings.is_production:
        logger.warning(
            "CLERK_FRONTEND_API_URL is unset (env={}). JWT verification is "
            "DISABLED and X-Clerk-User-Id will be trusted from any caller. "
            "This is only safe for local development; production deploys "
            "are refused at startup by app.config.",
            settings.ENVIRONMENT,
        )
        return True
    return False


# Emit the warning at import time so it shows up in boot logs.
_warn_if_clerk_url_missing()


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
    # Invalidate negative cache entries for kids that just became known so
    # legitimate requests are not blocked for the remainder of the TTL.
    for key in keys:
        _jwks_unknown_kids.pop(key.get("kid"), None)
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
    """Return the JWK matching ``kid``, force-refreshing once on cache miss.

    Protections:
    * Short negative cache for unknown kids (DoS amplification mitigation).
    * ``asyncio.Lock`` coalesces concurrent refreshes (thundering-herd guard).
    * Clerk outages fall back to stale cache when possible, else raise 503
      so the auth handler does not leak ``httpx`` errors as 500s.
    """
    # Negative-cache hit: skip the upstream call entirely.
    now = time.monotonic()
    miss_ts = _jwks_unknown_kids.get(kid)
    if miss_ts is not None:
        if now - miss_ts < _JWKS_UNKNOWN_KID_TTL:
            return None
        # Expired — drop the entry and fall through to a normal lookup.
        _jwks_unknown_kids.pop(kid, None)

    # Initial (non-forced) lookup. Wrap in the same try/except so a Clerk
    # outage on a cold cache surfaces as 503, not a 500.
    try:
        keys = await _get_clerk_jwks()
    except (TimeoutError, httpx.HTTPError) as exc:
        cached_keys = _jwks_cache.get("keys")
        if cached_keys:
            logger.warning(
                "JWKS fetch failed ({}); serving stale cache with {} keys",
                exc.__class__.__name__,
                len(cached_keys),
            )
            keys = cached_keys
        else:
            logger.error(
                "JWKS fetch failed ({}) and no cached keys available",
                exc.__class__.__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable",
            ) from exc

    key = _find_jwk_by_kid(keys, kid)
    if key is not None:
        return key

    # Cache miss — coalesce concurrent force-refreshes.
    async with _jwks_refresh_lock:
        # Re-check the cache directly: another coroutine may have refreshed
        # while we waited on the lock. Avoid calling _get_clerk_jwks() here,
        # which could trigger an unrelated TTL-driven fetch.
        cached_keys = _jwks_cache.get("keys") or []
        key = _find_jwk_by_kid(cached_keys, kid)
        if key is not None:
            return key

        # Still missing — also re-check the negative cache (a sibling coroutine
        # may have just recorded the miss).
        miss_ts = _jwks_unknown_kids.get(kid)
        if miss_ts is not None and (time.monotonic() - miss_ts) < _JWKS_UNKNOWN_KID_TTL:
            return None

        logger.warning("JWKS force-refreshed due to unknown kid={}", kid)
        try:
            keys = await _get_clerk_jwks(force_refresh=True)
        except (TimeoutError, httpx.HTTPError) as exc:
            cached_keys = _jwks_cache.get("keys")
            if cached_keys:
                logger.warning(
                    "JWKS refresh failed ({}); serving stale cache with {} keys",
                    exc.__class__.__name__,
                    len(cached_keys),
                )
                keys = cached_keys
            else:
                logger.error(
                    "JWKS refresh failed ({}) and no cached keys available",
                    exc.__class__.__name__,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service unavailable",
                ) from exc
        else:
            logger.info("JWKS refresh succeeded; {} keys cached", len(keys))

        key = _find_jwk_by_kid(keys, kid)
        if key is None:
            # FIFO eviction to bound memory under random-kid spam.
            if len(_jwks_unknown_kids) >= _JWKS_UNKNOWN_KIDS_MAX:
                oldest_kid = min(
                    _jwks_unknown_kids,
                    key=lambda k: _jwks_unknown_kids[k],
                )
                _jwks_unknown_kids.pop(oldest_kid, None)
            _jwks_unknown_kids[kid] = time.monotonic()
        return key


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_clerk_user_id: str | None = Header(None, alias="X-Clerk-User-Id"),
) -> "User":
    """
    Resolve the authenticated user.

    Priority:
    1. Production fail-closed (Issue #90): if ``CLERK_FRONTEND_API_URL`` is
       missing in production, refuse the request with 401. The config
       validator in ``app.config`` blocks process startup in this state, so
       this branch is defense-in-depth for monkey-patched / mis-imported
       settings.
    2. If ``CLERK_FRONTEND_API_URL`` is configured: validate the
       ``Authorization: Bearer <token>`` JWT against Clerk's JWKS.
       In production the ``X-Clerk-User-Id`` header is NEVER trusted —
       only the verified JWT subject becomes the resolved clerk_id.
    3. Otherwise (dev / staging with no Clerk tenant) fall back to the
       ``X-Clerk-User-Id`` header.
    4. In development with no header: resolve the user whose ``clerk_id``
       matches ``settings.DEV_TEST_USER_ID``. If that setting is empty,
       return 401 (no credentials → unauthenticated).
    """
    from app.models.user import User  # late import to avoid circular deps

    # ── 0. Production fail-closed guard ───────────────────────────────────
    # Belt-and-braces for Issue #90: the config validator already refuses to
    # construct Settings without CLERK_FRONTEND_API_URL in production, but if
    # something monkey-patches the value at runtime we must NOT silently fall
    # through to the X-Clerk-User-Id header bypass.
    if settings.is_production and not settings.CLERK_FRONTEND_API_URL:
        logger.error(
            "CLERK_FRONTEND_API_URL is unset in production — refusing request "
            "to prevent X-Clerk-User-Id auth bypass (Issue #90)."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication unavailable: server misconfigured.",
        )

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
                    algorithms=_CLERK_JWT_ALGORITHMS,
                    audience=settings.CLERK_JWT_AUDIENCE or None,
                    options=options,
                )
                clerk_id = payload.get("sub")
            except JOSEError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired authentication token.",
                ) from exc

    # ── 2. Header path (extension / dev only) ────────────────────────────
    # The X-Clerk-User-Id header is a TRUSTED CLAIM with no cryptographic
    # binding. In production the JWT path above is the only acceptable
    # authentication mechanism — ignore the header outright to avoid any
    # path that would resolve a user from an unverified header value.
    if clerk_id is None and x_clerk_user_id and not settings.is_production:
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
            "Authentication required. Send Authorization: Bearer <token> from your Clerk session."
        ),
    )


def get_llm_gateway() -> LLMGateway:
    """Provide an LLMGateway instance as a FastAPI dependency."""
    return LLMGateway()
