"""Regression tests for ``skip_fallback`` flag on ``LLMGateway.generate``.

Issue #186 — Previously the gateway unconditionally appended Ollama as a
secondary attempt. When a caller wraps the gateway in its own outer
fallback loop (``_dispatch_provider_entry``), this caused two problems:

1. A failed cloud provider triggered a silent 180-second Ollama timeout.
2. The outer loop attributed Ollama's response to the cloud provider,
   because it used the entry's ``name`` rather than the gateway's
   returned ``provider_used``.

The ``skip_fallback=True`` flag opts the caller out of the Ollama
secondary so the gateway only attempts the requested provider and the
returned ``provider_used`` is always accurate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.llm_gateway import LLMGateway


@pytest.mark.asyncio
async def test_skip_fallback_does_not_invoke_ollama_on_failure():
    """When skip_fallback=True and primary fails, Ollama must NOT be called."""
    gateway = LLMGateway()
    ollama_mock = AsyncMock(return_value="ollama would respond here")

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_gateway._call_anthropic",
            new=AsyncMock(side_effect=RuntimeError("primary failed")),
        ),
        patch("app.services.llm_gateway._call_ollama", new=ollama_mock),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
            skip_fallback=True,
        )

    ollama_mock.assert_not_awaited()
    assert provider_used == "fallback"
    assert content == ""


@pytest.mark.asyncio
async def test_skip_fallback_default_false_preserves_legacy_behaviour():
    """Without skip_fallback (default), Ollama is still attempted on failure."""
    gateway = LLMGateway()
    ollama_text = "Ollama responded. " * 20
    ollama_mock = AsyncMock(return_value=ollama_text)

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_gateway._call_anthropic",
            new=AsyncMock(side_effect=RuntimeError("primary failed")),
        ),
        patch("app.services.llm_gateway._call_ollama", new=ollama_mock),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="anthropic",
            api_key="sk-ant-test1234567890",
        )

    ollama_mock.assert_awaited_once()
    assert provider_used == "ollama"
    assert content == ollama_text


@pytest.mark.asyncio
async def test_provider_used_matches_actual_responder_when_skip_fallback_off():
    """When the gateway DOES fall back to Ollama, provider_used must report
    'ollama' — never the originally requested provider. This is what the
    outer-loop in ``_dispatch_provider_entry`` previously masked.
    """
    gateway = LLMGateway()
    ollama_text = "Ollama. " * 40

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_gateway._call_gemini",
            new=AsyncMock(side_effect=RuntimeError("gemini boom")),
        ),
        patch(
            "app.services.llm_gateway._call_ollama",
            new=AsyncMock(return_value=ollama_text),
        ),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="gemini",
            api_key="AIzaSyTestKey12345678901234567890ABC",
        )

    assert provider_used == "ollama"
    assert content == ollama_text


@pytest.mark.asyncio
async def test_provider_used_matches_primary_when_skip_fallback_on():
    """When skip_fallback=True and the primary succeeds, provider_used is
    the primary's name. Round-trip sanity check for the caller contract.
    """
    gateway = LLMGateway()
    payload = "Real answer. " * 25

    with (
        patch(
            "app.services.llm_circuit_redis.is_open",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_circuit_redis.record_success",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.llm_circuit_redis.record_failure",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.services.llm_gateway._call_gemini",
            new=AsyncMock(return_value=payload),
        ),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="gemini",
            api_key="AIzaSyTestKey12345678901234567890ABC",
            skip_fallback=True,
        )

    assert provider_used == "gemini"
    assert content == payload
