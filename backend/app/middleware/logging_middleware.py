"""
Structured logging middleware.

Logs every HTTP request with consistent fields:
- request_id: For tracing through the system
- user_hash: SHA-256 of user identifier (privacy)
- method: HTTP method
- path: URL path
- status_code: Response code
- duration_ms: How long the request took

Skips noisy paths (health checks, metrics) in production.
"""

import time

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.utils.hashing import hash_pii

# Paths to skip logging (too noisy, pollute dashboards)
SKIP_PATHS = {"/health", "/ready", "/metrics", "/favicon.ico"}


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip noisy endpoints
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        start_time = time.perf_counter()
        request_id = getattr(request.state, "request_id", "unknown")

        # Hash user identifier for privacy
        user_id = request.headers.get("X-User-ID", "anonymous")
        user_hash = hash_pii(user_id)[:16]  # First 16 chars is enough for grouping

        try:
            response = await call_next(request)
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logger.bind(
                request_id=request_id,
                user_hash=user_hash,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            ).info("request_completed")

            # Add performance header (useful for debugging from browser)
            response.headers["X-Duration-Ms"] = str(duration_ms)
            return response

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.bind(
                request_id=request_id,
                user_hash=user_hash,
                method=request.method,
                path=request.url.path,
                error_type=type(e).__name__,
                error_message=str(e)[:500],  # Truncate long error messages
                duration_ms=duration_ms,
            ).error("request_failed")
            raise
