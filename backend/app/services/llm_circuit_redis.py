"""
Redis-backed circuit breaker for LLM provider dispatch.

Issue #107 — Phase 2. Per-provider circuit state lives in Redis under
``llm:circuit:{provider}`` keys with a 60-second TTL. When a provider
records ``_FAILURE_THRESHOLD`` consecutive failures inside the rolling
60-second window, the circuit opens and ``LLMGateway`` skips it until
the key expires.

Design notes
------------
* The breaker is *advisory*. If Redis is unavailable we log a warning
  once per failure and proceed without circuit-breaking — the request
  must never fail because of a missing observability dependency.
* State keys carry their own TTL so we never need a separate
  half-open timer: a single ``GET`` is all the gateway needs.
* Failure counters live under ``llm:circuit:{provider}:fails`` with the
  same TTL; reaching the threshold flips the circuit-open key on.
* The module is intentionally light on assumptions about how Redis is
  managed — it accepts an optional ``redis_url`` so tests can wire a
  fake client, but defaults to ``settings.REDIS_URL`` so production
  callers don't need to plumb the URL through.
"""

from __future__ import annotations

import contextlib
from typing import Any

from loguru import logger

from app.config import settings

_FAILURE_THRESHOLD = 3
_WINDOW_SECONDS = 60

_CIRCUIT_KEY = "llm:circuit:{provider}"
_FAILS_KEY = "llm:circuit:{provider}:fails"


def _circuit_key(provider: str) -> str:
    return _CIRCUIT_KEY.format(provider=provider)


def _fails_key(provider: str) -> str:
    return _FAILS_KEY.format(provider=provider)


async def _get_client(redis_url: str | None = None) -> Any | None:
    """Build a Redis client or return ``None`` if construction fails.

    A returned ``None`` signals "no Redis available" and the breaker
    falls back to a permissive mode (every provider is considered
    closed). Callers must not raise on a ``None`` client.
    """
    try:
        # Imported lazily so test environments without redis still load.
        from redis.asyncio import Redis  # noqa: WPS433

        url = redis_url or settings.REDIS_URL
        return Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except Exception as exc:  # pragma: no cover - import / config failures
        logger.warning(f"llm.circuit: redis client unavailable ({exc}); skipping breaker")
        return None


async def is_open(provider: str, client: Any | None = None) -> bool:
    """Return True iff ``provider`` is currently circuit-open.

    A Redis failure is treated as "closed" so the request still
    attempts the provider — graceful degradation per spec.
    """
    owns_client = False
    if client is None:
        client = await _get_client()
        owns_client = True
    if client is None:
        return False

    try:
        flag = await client.get(_circuit_key(provider))
        return flag is not None
    except Exception as exc:
        logger.warning(f"llm.circuit: GET failed for '{provider}' ({exc}); treating as closed")
        return False
    finally:
        if owns_client:
            with contextlib.suppress(Exception):  # pragma: no cover - defensive
                await client.aclose()


async def record_success(provider: str, client: Any | None = None) -> None:
    """Reset the failure counter for ``provider``.

    Closing the circuit is implicit: the open flag has a 60-second
    TTL and expires on its own, so we only need to clear the fail
    counter to prevent flap.
    """
    owns_client = False
    if client is None:
        client = await _get_client()
        owns_client = True
    if client is None:
        return

    try:
        await client.delete(_fails_key(provider))
    except Exception as exc:
        logger.warning(f"llm.circuit: DEL fails failed for '{provider}' ({exc})")
    finally:
        if owns_client:
            with contextlib.suppress(Exception):  # pragma: no cover - defensive
                await client.aclose()


async def record_failure(provider: str, client: Any | None = None) -> bool:
    """Increment the failure counter; return True if circuit just opened.

    The counter shares the same 60-second TTL as the open flag — if a
    provider has 3 failures within 60s the circuit trips; otherwise
    older failures expire and never accumulate.
    """
    owns_client = False
    if client is None:
        client = await _get_client()
        owns_client = True
    if client is None:
        return False

    just_opened = False
    try:
        fails_key = _fails_key(provider)
        count = await client.incr(fails_key)
        # Ensure the counter expires so failures more than ``_WINDOW_SECONDS``
        # old roll out of the sliding window even if no new failures arrive.
        await client.expire(fails_key, _WINDOW_SECONDS)
        if int(count) >= _FAILURE_THRESHOLD:
            await client.set(_circuit_key(provider), "1", ex=_WINDOW_SECONDS)
            just_opened = True
    except Exception as exc:
        logger.warning(f"llm.circuit: INCR failed for '{provider}' ({exc}); skipping breaker")
    finally:
        if owns_client:
            with contextlib.suppress(Exception):  # pragma: no cover - defensive
                await client.aclose()
    return just_opened


__all__ = [
    "is_open",
    "record_failure",
    "record_success",
    "_FAILURE_THRESHOLD",
    "_WINDOW_SECONDS",
]
