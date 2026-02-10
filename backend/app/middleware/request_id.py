"""
Request ID middleware.

Every HTTP request gets a unique UUID. This ID is:
1. Attached to the request state (accessible in route handlers)
2. Returned in the X-Request-ID response header
3. Included in all log entries for this request
4. Stored in audit logs for tracing

When a user reports a bug, ask them for the X-Request-ID
from their browser's network tab — then search your logs.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Use client-provided ID if present (for distributed tracing),
        # otherwise generate a new one
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
