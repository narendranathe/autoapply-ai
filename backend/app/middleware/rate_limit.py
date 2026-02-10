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


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for health checks
        if request.url.path in {"/health", "/ready", "/metrics"}:
            return await call_next(request)

        # Identify client (user ID header > IP address)
        client_id = request.headers.get(
            "X-User-ID", request.client.host if request.client else "unknown"
        )

        try:
            redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            key = f"ratelimit:{client_id}:{request.url.path}"

            # Increment counter and set expiry
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, 60)  # 60-second window

            ttl = await redis.ttl(key)
            await redis.aclose()

            # Check limit
            if current > self.rpm:
                logger.warning(
                    "rate_limit_exceeded",
                    client_id=client_id[:16],
                    path=request.url.path,
                    current=current,
                    limit=self.rpm,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Rate limit exceeded",
                        "detail": f"Maximum {self.rpm} requests per minute",
                        "retry_after": ttl,
                    },
                    headers={"Retry-After": str(ttl)},
                )

            response = await call_next(request)
            # Add rate limit headers (like GitHub does)
            response.headers["X-RateLimit-Limit"] = str(self.rpm)
            response.headers["X-RateLimit-Remaining"] = str(max(0, self.rpm - current))
            response.headers["X-RateLimit-Reset"] = str(ttl)
            return response

        except Exception as e:
            # If Redis is down, allow the request (fail open)
            # Better to serve without rate limiting than to block everyone
            logger.warning(f"Rate limiter failed (allowing request): {e}")
            return await call_next(request)
