"""Regression tests for per-provider model overrides through ``LLMGateway``.

Issue #188 — ``LLMGateway.generate()`` must accept a ``model=`` kwarg and
forward it to the per-provider lambdas so callers can request specific
model variants (e.g. ``gemini-1.5-pro``). Previously the only way to
override a model was the legacy ``ollama_model`` kwarg, which Gemini /
Groq / Perplexity silently ignored.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.llm_gateway import LLMGateway


def _ok_response(text: str) -> httpx.Response:
    """Build an OpenAI-compatible chat-completions success response."""
    return httpx.Response(
        status_code=200,
        json={
            "choices": [{"message": {"content": text}}],
        },
        request=httpx.Request("POST", "https://example.invalid"),
    )


@pytest.mark.asyncio
async def test_gemini_honours_model_override():
    """When ``model="gemini-1.5-pro"`` is passed, the HTTP POST body must
    carry ``model="gemini-1.5-pro"`` rather than the hard-coded flash default."""
    payload_text = "Real response. " * 30  # > 200 chars
    captured: dict = {}

    async def fake_post(self, url, *args, **kwargs):  # noqa: ANN001
        captured["url"] = str(url)
        captured["json"] = kwargs.get("json", {})
        return _ok_response(payload_text)

    gateway = LLMGateway()
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
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="gemini",
            api_key="AIzaSyTestKey12345678901234567890ABC",
            model="gemini-1.5-pro",
        )

    assert provider_used == "gemini"
    assert content == payload_text
    assert captured["json"].get("model") == "gemini-1.5-pro"


@pytest.mark.asyncio
async def test_gemini_defaults_to_flash_when_model_unset():
    payload_text = "Real response. " * 30
    captured: dict = {}

    async def fake_post(self, url, *args, **kwargs):  # noqa: ANN001
        captured["json"] = kwargs.get("json", {})
        return _ok_response(payload_text)

    gateway = LLMGateway()
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
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="gemini",
            api_key="AIzaSyTestKey12345678901234567890ABC",
        )

    assert captured["json"].get("model") == "gemini-1.5-flash"


@pytest.mark.asyncio
async def test_groq_honours_model_override():
    payload_text = "Hello. " * 60
    captured: dict = {}

    async def fake_post(self, url, *args, **kwargs):  # noqa: ANN001
        captured["json"] = kwargs.get("json", {})
        return _ok_response(payload_text)

    gateway = LLMGateway()
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
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="groq",
            api_key="gsk_testkey1234567890abcdefghij",
            model="llama-3.1-8b-instant",
        )

    assert captured["json"].get("model") == "llama-3.1-8b-instant"


@pytest.mark.asyncio
async def test_perplexity_honours_model_override():
    payload_text = "Hello. " * 60
    captured: dict = {}

    async def fake_post(self, url, *args, **kwargs):  # noqa: ANN001
        captured["json"] = kwargs.get("json", {})
        return _ok_response(payload_text)

    gateway = LLMGateway()
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
        patch.object(httpx.AsyncClient, "post", new=fake_post),
    ):
        await gateway.generate(
            system_prompt="S",
            user_prompt="U",
            provider="perplexity",
            api_key="pplx-testkey1234567890abcdefghij",
            model="sonar-pro",
        )

    assert captured["json"].get("model") == "sonar-pro"
