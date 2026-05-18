from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_response(model: str) -> MagicMock:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "content": [{"text": "response text"}],
        "model": model,
    }
    return mock_response


@pytest.mark.asyncio
async def test_call_anthropic_accepts_model_param():
    """_call_anthropic must forward model param to Anthropic API."""
    mock_response = _make_mock_response("claude-haiku-4-5-20251001")

    mock_post = AsyncMock(return_value=mock_response)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("app.services.llm_gateway.httpx.AsyncClient", return_value=mock_client):
        from app.services.llm_gateway import _call_anthropic

        await _call_anthropic("sys", "user", "sk-fake", model="claude-haiku-4-5-20251001")

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["model"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_call_anthropic_defaults_to_sonnet():
    """_call_anthropic default model is claude-sonnet-4-6."""
    mock_response = _make_mock_response("claude-sonnet-4-6")

    mock_post = AsyncMock(return_value=mock_response)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = mock_post

    with patch("app.services.llm_gateway.httpx.AsyncClient", return_value=mock_client):
        from app.services.llm_gateway import _call_anthropic

        await _call_anthropic("sys", "user", "sk-fake")

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["model"] == "claude-sonnet-4-6"
