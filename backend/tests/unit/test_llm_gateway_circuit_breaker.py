"""Tests for the Redis-backed LLM circuit breaker.

Issue #107 — Phase 2. The breaker lives in
``app.services.llm_circuit_redis`` and is consulted by
``LLMGateway.generate()`` before every provider attempt.

Tests run against an in-memory fake Redis (a tiny dict-backed class)
to avoid spinning up a real Redis service. The graceful-degradation
test additionally simulates a Redis client that always raises.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services import llm_circuit_redis
from app.services.llm_gateway import LLMGateway


class _FakeRedis:
    """Minimal in-memory async Redis stub for circuit-breaker tests."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, float | None]] = {}

    def _now(self) -> float:
        return time.monotonic()

    def _expired(self, key: str) -> bool:
        v = self.store.get(key)
        if v is None:
            return True
        _, expires_at = v
        if expires_at is None:
            return False
        if self._now() >= expires_at:
            del self.store[key]
            return True
        return False

    async def get(self, key: str) -> str | None:
        if self._expired(key):
            return None
        return self.store[key][0]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        expires_at = self._now() + ex if ex else None
        self.store[key] = (str(value), expires_at)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def incr(self, key: str) -> int:
        if self._expired(key):
            self.store[key] = ("1", None)
            return 1
        val = int(self.store[key][0])
        val += 1
        prev_ttl = self.store[key][1]
        self.store[key] = (str(val), prev_ttl)
        return val

    async def expire(self, key: str, ttl: int) -> None:
        if key in self.store:
            cur, _ = self.store[key]
            self.store[key] = (cur, self._now() + ttl)

    async def aclose(self) -> None:
        return None


class _BrokenRedis:
    """Simulates Redis being completely down — every call raises."""

    async def get(self, *_a: Any, **_kw: Any) -> str | None:
        raise ConnectionError("redis down")

    async def set(self, *_a: Any, **_kw: Any) -> None:
        raise ConnectionError("redis down")

    async def delete(self, *_a: Any, **_kw: Any) -> None:
        raise ConnectionError("redis down")

    async def incr(self, *_a: Any, **_kw: Any) -> int:
        raise ConnectionError("redis down")

    async def expire(self, *_a: Any, **_kw: Any) -> None:
        raise ConnectionError("redis down")

    async def aclose(self) -> None:
        return None


# -- is_open / record_failure / record_success ------------------------------


@pytest.mark.asyncio
async def test_breaker_starts_closed():
    fake = _FakeRedis()
    assert await llm_circuit_redis.is_open("anthropic", client=fake) is False


@pytest.mark.asyncio
async def test_breaker_opens_after_threshold_failures():
    fake = _FakeRedis()
    # 2 failures — still closed
    await llm_circuit_redis.record_failure("anthropic", client=fake)
    await llm_circuit_redis.record_failure("anthropic", client=fake)
    assert await llm_circuit_redis.is_open("anthropic", client=fake) is False
    # 3rd failure opens the circuit
    just_opened = await llm_circuit_redis.record_failure("anthropic", client=fake)
    assert just_opened is True
    assert await llm_circuit_redis.is_open("anthropic", client=fake) is True


@pytest.mark.asyncio
async def test_breaker_record_failure_returns_false_when_below_threshold():
    fake = _FakeRedis()
    result = await llm_circuit_redis.record_failure("openai", client=fake)
    assert result is False


@pytest.mark.asyncio
async def test_breaker_closes_after_ttl_expires(monkeypatch):
    fake = _FakeRedis()
    # Patch the threshold's TTL so the test runs fast
    monkeypatch.setattr(llm_circuit_redis, "_WINDOW_SECONDS", 1)
    for _ in range(3):
        await llm_circuit_redis.record_failure("groq", client=fake)
    assert await llm_circuit_redis.is_open("groq", client=fake) is True
    # Wait past the TTL — circuit auto-closes
    time.sleep(1.1)
    assert await llm_circuit_redis.is_open("groq", client=fake) is False


@pytest.mark.asyncio
async def test_breaker_record_success_resets_counter():
    fake = _FakeRedis()
    await llm_circuit_redis.record_failure("kimi", client=fake)
    await llm_circuit_redis.record_failure("kimi", client=fake)
    await llm_circuit_redis.record_success("kimi", client=fake)
    # Two new failures should not be enough to re-open — the counter reset.
    just_opened = await llm_circuit_redis.record_failure("kimi", client=fake)
    assert just_opened is False
    assert await llm_circuit_redis.is_open("kimi", client=fake) is False


@pytest.mark.asyncio
async def test_breaker_isolates_providers():
    """A trip on one provider must not affect another."""
    fake = _FakeRedis()
    for _ in range(3):
        await llm_circuit_redis.record_failure("anthropic", client=fake)
    assert await llm_circuit_redis.is_open("anthropic", client=fake) is True
    assert await llm_circuit_redis.is_open("openai", client=fake) is False


# -- graceful degradation when Redis is unavailable --------------------------


@pytest.mark.asyncio
async def test_breaker_treats_redis_down_as_closed():
    broken = _BrokenRedis()
    # All operations must return safe defaults rather than raise
    assert await llm_circuit_redis.is_open("anthropic", client=broken) is False
    just_opened = await llm_circuit_redis.record_failure("anthropic", client=broken)
    assert just_opened is False
    # record_success must not raise either
    await llm_circuit_redis.record_success("anthropic", client=broken)


@pytest.mark.asyncio
async def test_gateway_proceeds_when_redis_is_unavailable():
    """LLMGateway must complete a request when the circuit breaker can't talk to Redis."""
    gateway = LLMGateway()
    payload = "Real LLM response. " * 20  # > 200 chars

    with (
        patch(
            "app.services.llm_circuit_redis._get_client",
            new=AsyncMock(return_value=None),  # simulate "redis unavailable"
        ),
        patch(
            "app.services.llm_gateway._call_anthropic",
            new=AsyncMock(return_value=payload),
        ),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="System.",
            user_prompt="Question.",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
        )

    assert provider_used == "anthropic"
    assert content == payload


# -- integration with LLMGateway: open circuit skips the provider -----------


@pytest.mark.asyncio
async def test_gateway_skips_provider_when_circuit_is_open():
    """When ``is_open`` returns True for the primary, the gateway must
    fall through to the next stage (Ollama) without calling it."""
    gateway = LLMGateway()
    ollama_text = "Ollama returned this answer. " * 15

    anthropic_mock = AsyncMock(return_value="should not be called")
    is_open_mock = AsyncMock(side_effect=lambda name, client=None: name == "anthropic")

    with (
        patch("app.services.llm_circuit_redis.is_open", new=is_open_mock),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch("app.services.llm_gateway._call_anthropic", new=anthropic_mock),
        patch(
            "app.services.llm_gateway._call_ollama",
            new=AsyncMock(return_value=ollama_text),
        ),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="System.",
            user_prompt="Question.",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
        )

    anthropic_mock.assert_not_awaited()
    assert provider_used == "ollama"
    assert content == ollama_text


@pytest.mark.asyncio
async def test_gateway_records_success_on_provider_success():
    gateway = LLMGateway()
    payload = "OK response. " * 20

    success_mock = AsyncMock(return_value=None)
    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch("app.services.llm_circuit_redis.record_success", new=success_mock),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_gateway._call_anthropic",
            new=AsyncMock(return_value=payload),
        ),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
        )

    assert provider_used == "anthropic"
    assert content == payload
    success_mock.assert_awaited()


@pytest.mark.asyncio
async def test_gateway_records_failure_when_provider_raises():
    gateway = LLMGateway()
    failure_mock = AsyncMock(return_value=False)

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch("app.services.llm_circuit_redis.record_failure", new=failure_mock),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_gateway._call_anthropic",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch(
            "app.services.llm_gateway._call_ollama",
            new=AsyncMock(side_effect=RuntimeError("ollama down")),
        ),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
        )

    assert provider_used == "fallback"
    assert content == ""
    assert failure_mock.await_count >= 1
