"""Tests for LLMGateway — single source of truth for LLM provider dispatch."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.llm_gateway import LLMGateway


@pytest.mark.asyncio
async def test_gateway_calls_anthropic_when_provider_is_anthropic():
    """When provider='anthropic', gateway calls Anthropic API and returns (content, 'anthropic')."""
    gateway = LLMGateway()
    fake_response = "This is the LLM answer. " * 10  # > 200 chars to pass _MIN_RESPONSE_LEN check

    with patch(
        "app.services.llm_gateway._call_anthropic",
        new=AsyncMock(return_value=fake_response),
    ) as mock_call:
        content, provider_used = await gateway.generate(
            system_prompt="You are an assistant.",
            user_prompt="Tell me about Python.",
            provider="anthropic",
            api_key="sk-ant-test1234567890abcdef",
        )

    mock_call.assert_awaited_once()
    assert content == fake_response
    assert provider_used == "anthropic"


@pytest.mark.asyncio
async def test_gateway_falls_back_to_keyword_on_empty_key():
    """When api_key='', gateway skips the named provider and returns ('', 'fallback')."""
    gateway = LLMGateway()

    # Ollama will also be tried; patch it to fail so we reach fallback
    with patch(
        "app.services.llm_gateway._call_ollama",
        new=AsyncMock(side_effect=Exception("Ollama not running")),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="You are an assistant.",
            user_prompt="Tell me about Python.",
            provider="anthropic",
            api_key="",  # empty key — should skip anthropic
        )

    assert provider_used == "fallback"
    assert content == ""


@pytest.mark.asyncio
async def test_gateway_returns_provider_name_used():
    """Second return value is the name of the provider that succeeded."""
    gateway = LLMGateway()

    with patch(
        "app.services.llm_gateway._call_openai",
        new=AsyncMock(return_value="OpenAI answered this question with detail." * 10),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="System.",
            user_prompt="Question.",
            provider="openai",
            api_key="sk-test1234567890abcdef",
        )

    assert provider_used == "openai"
    assert len(content) > 0


@pytest.mark.asyncio
async def test_gateway_falls_back_to_ollama_when_primary_fails():
    """When primary provider raises, gateway falls back to Ollama before returning 'fallback'."""
    gateway = LLMGateway()
    ollama_text = "Ollama response here." * 15  # > 200 chars

    with (
        patch(
            "app.services.llm_gateway._call_anthropic",
            new=AsyncMock(side_effect=Exception("API error")),
        ),
        patch(
            "app.services.llm_gateway._call_ollama",
            new=AsyncMock(return_value=ollama_text),
        ),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="System.",
            user_prompt="Question.",
            provider="anthropic",
            api_key="sk-ant-test1234567890abcdef",
        )

    assert provider_used == "ollama"
    assert content == ollama_text


@pytest.mark.asyncio
async def test_gateway_supports_groq_provider():
    """gateway.generate works when provider='groq'."""
    gateway = LLMGateway()
    groq_text = "Groq answered." * 20

    with patch(
        "app.services.llm_gateway._call_groq",
        new=AsyncMock(return_value=groq_text),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="System.",
            user_prompt="Question.",
            provider="groq",
            api_key="gsk_test1234567890abcdef",
        )

    assert provider_used == "groq"
    assert content == groq_text


@pytest.mark.asyncio
async def test_gateway_supports_kimi_provider():
    """gateway.generate works when provider='kimi'."""
    gateway = LLMGateway()
    kimi_text = "Kimi answered." * 20

    with patch(
        "app.services.llm_gateway._call_kimi",
        new=AsyncMock(return_value=kimi_text),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="System.",
            user_prompt="Question.",
            provider="kimi",
            api_key="kimi-test1234567890abcdef",
        )

    assert provider_used == "kimi"
    assert content == kimi_text


@pytest.mark.asyncio
async def test_gateway_supports_ollama_provider_directly():
    """gateway.generate works when provider='ollama' (no api_key required)."""
    gateway = LLMGateway()
    ollama_text = "Ollama direct." * 20

    with patch(
        "app.services.llm_gateway._call_ollama",
        new=AsyncMock(return_value=ollama_text),
    ):
        content, provider_used = await gateway.generate(
            system_prompt="System.",
            user_prompt="Question.",
            provider="ollama",
            api_key="",
            ollama_model="llama3.1:8b",
        )

    assert provider_used == "ollama"
    assert content == ollama_text
