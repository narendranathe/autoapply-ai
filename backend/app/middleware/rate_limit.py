"""
Token bucket rate limiter using Redis.

Limits requests per user per minute. Uses Redis INCR + EXPIRE
for a simple sliding window counter.

Why rate limiting matters:
1. Protects GitHub API quota (5000 req/hour shared across all users)
2. Prevents abuse of LLM endpoints (each call costs real money)
3. Protects database from runaway clients

Returns 429 Too Many Requests with Retry-After header.
"""

from loguru import logger
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

# LLM endpoints that are expensive — apply a tighter per-minute cap
_LLM_PATHS = {
    "/api/v1/vault/generate/answers",
    "/api/v1/vault/generate/tailored",
    "/api/v1/vault/generate",
    "/api/v1/vault/generate/summary",
    "/api/v1/vault/generate/bullets",
    "/api/v1/vault/interview-prep",
    "/api/v1/work-history/import-from-resume",
}
_LLM_RPM = 10  # 10 LLM calls per minute per user


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in {"/health", "/ready", "/metrics"}:
            return await call_next(request)

        # Identify client — prefer authenticated user ID over IP
        # Check X-Clerk-User-Id (header auth) first, then fall back to IP
        client_id = (
            request.headers.get("X-Clerk-User-Id") or request.client.host
            if request.client
            else "unknown"
        )

        # For Bearer JWT auth we can't easily decode the sub here without full JWKS,
        # so fall back to IP if no X-Clerk-User-Id is present.
        # (JWT users are still per-IP rate-limited, which is acceptable.)

        is_llm_path = request.url.path in _LLM_PATHS
        effective_rpm = _LLM_RPM if is_llm_path else self.rpm
        window_key = "llm" if is_llm_path else "api"

        try:
            redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            key = f"ratelimit:{window_key}:{client_id}"

            # Increment counter and set expiry
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, 60)  # 60-second window

            ttl = await redis.ttl(key)
            await redis.aclose()

            # Check limit
            if current > effective_rpm:
                logger.warning(
                    "rate_limit_exceeded",
                    client_id=client_id[:16],
                    path=request.url.path,
                    current=current,
                    limit=effective_rpm,
                    window=window_key,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Rate limit exceeded",
                        "detail": (
                            f"Maximum {effective_rpm} {'LLM' if is_llm_path else 'API'} "
                            f"requests per minute"
                        ),
                        "retry_after": ttl,
                    },
                    headers={"Retry-After": str(ttl)},
                )

            response = await call_next(request)
            # Add rate limit headers (like GitHub does)
            response.headers["X-RateLimit-Limit"] = str(effective_rpm)
            response.headers["X-RateLimit-Remaining"] = str(max(0, effective_rpm - current))
            response.headers["X-RateLimit-Reset"] = str(ttl)
            return response

        except Exception as e:
            # If Redis is down, allow the request (fail open)
            # Better to serve without rate limiting than to block everyone
            logger.warning(f"Rate limiter failed (allowing request): {e}")
            return await call_next(request)
