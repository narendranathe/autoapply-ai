"""Regression tests for API-key scrubbing in error / log paths.

Issue #190 — Gemini accepts the API key as a ``?key=`` query string
parameter, Perplexity's 4xx bodies sometimes echo the
``x-api-key`` header, Groq's tokens are ``gsk_...``, Anthropic's are
``sk-ant-...``, etc. Any of these can end up inside an exception
``str()`` and then in a log line or
``LLMGenerationError.__repr__``. The gateway must scrub before
interpolation so leaked keys never reach the log stream.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.llm_gateway import (
    LLMGenerationError,
    _scrub,
)

# -- direct scrubber unit tests ------------------------------------------


def test_scrub_redacts_anthropic_key():
    text = "401 unauthorised: sk-ant-abcDEF1234567890_-= rejected"
    out = _scrub(text)
    assert "sk-ant-" not in out
    assert "[REDACTED]" in out


def test_scrub_redacts_gemini_key():
    text = "POST https://example.com/v1/x?key=AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q failed"
    out = _scrub(text)
    assert "AIzaSy" not in out
    assert "key=AIza" not in out
    assert "[REDACTED]" in out


def test_scrub_redacts_query_string_key_param():
    text = "GET ?key=somesecretvalue123 ; got 401"
    out = _scrub(text)
    assert "somesecretvalue123" not in out
    assert "[REDACTED]" in out


def test_scrub_redacts_api_key_query_param():
    text = "GET /path?api_key=xyz9876 returned 401"
    out = _scrub(text)
    assert "xyz9876" not in out


def test_scrub_redacts_bearer_token():
    text = "Headers: Authorization: Bearer abc.def.ghi=="
    out = _scrub(text)
    assert "abc.def.ghi" not in out
    assert "[REDACTED]" in out


def test_scrub_redacts_x_api_key_header():
    text = "headers x-api-key: pplx-livesecret1234567890"
    out = _scrub(text)
    assert "pplx-livesecret" not in out


def test_scrub_redacts_groq_key():
    text = "Auth failure: gsk_liveGroqKey1234567890abcdef"
    out = _scrub(text)
    assert "gsk_" not in out


def test_scrub_redacts_openai_key():
    text = "sk-abcDEF1234567890XYZWVU09 invalid"
    out = _scrub(text)
    assert "sk-abcDEF1234567890XYZWVU09" not in out


def test_scrub_keeps_innocent_text():
    """Non-secret text passes through unchanged so logs remain useful."""
    text = "Provider 'anthropic' raised: HTTPStatusError 429 rate limited"
    assert _scrub(text) == text


# -- LLMGenerationError __repr__ scrubbing -------------------------------


def test_error_repr_scrubs_anthropic_key_from_cause():
    cause = RuntimeError("auth failed for sk-ant-LeAkEdKey1234567890abc")
    err = LLMGenerationError(
        "boom",
        provider="anthropic",
        attempt_number=1,
        cause=cause,
    )
    out = repr(err)
    assert "sk-ant-LeAkEdKey" not in out
    assert "[REDACTED]" in out
    # Provider / attempt info still present
    assert "anthropic" in out
    assert "attempt_number=1" in out


def test_error_repr_scrubs_gemini_query_param():
    # An httpx error containing a Gemini URL with the key in the query string
    cause = httpx.HTTPStatusError(
        "Client error '401 Unauthorized' for url "
        "'https://generativelanguage.googleapis.com/v1/x?key=AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q'",
        request=httpx.Request("GET", "https://example.invalid"),
        response=httpx.Response(401),
    )
    err = LLMGenerationError(
        "boom",
        provider="gemini",
        attempt_number=2,
        cause=cause,
    )
    out = repr(err)
    assert "AIzaSy" not in out
    assert "[REDACTED]" in out


def test_error_repr_with_no_cause_still_works():
    err = LLMGenerationError("no cause", provider="openai", attempt_number=1)
    out = repr(err)
    assert "openai" in out
    assert "attempt_number=1" in out
    assert "cause=None" in out


def test_error_message_does_not_contain_secret_when_constructed_via_gateway_path():
    """The gateway's cascade builds err.args[0] from the scrubbed exception
    text. Constructing one ourselves with a clean message must remain clean.
    """
    err = LLMGenerationError(
        "Provider 'groq' raised: HTTPStatusError 500",
        provider="groq",
        attempt_number=1,
        cause=None,
    )
    assert "[REDACTED]" not in str(err)


# -- Test pattern that matches LLMGateway error-path interpolation -------


@pytest.mark.asyncio
async def test_gateway_error_message_scrubs_upstream_secret():
    """When _call_anthropic raises with the API key in the exception text,
    the gateway's failure path must NOT include the key in the error
    message it propagates (or in the loguru warning it emits).
    """
    from unittest.mock import AsyncMock, patch

    from app.services.llm_gateway import LLMGateway

    leaky = RuntimeError(
        "401 Unauthorized for https://api.anthropic.com/v1/messages "
        "with sk-ant-LeAkEdSecret1234567890abc"
    )

    captured_messages: list[str] = []

    # Use the gateway module's bound logger to dodge sys.modules-level
    # ``loguru.logger`` mutations performed by other tests in the suite.
    from app.services import llm_gateway as _gw

    _logger = _gw.logger
    if not hasattr(_logger, "add") or not hasattr(_logger, "remove"):
        pytest.skip("loguru.logger was monkey-patched by another test module")

    def sink(message) -> None:  # noqa: ANN001
        captured_messages.append(message.record["message"])

    sink_id = _logger.add(sink, level="WARNING")
    try:
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
            patch(
                "app.services.llm_gateway._call_anthropic",
                new=AsyncMock(side_effect=leaky),
            ),
            patch(
                "app.services.llm_gateway._call_ollama",
                new=AsyncMock(side_effect=leaky),
            ),
        ):
            await gateway.generate(
                system_prompt="S",
                user_prompt="U",
                provider="anthropic",
                api_key="sk-ant-test1234567890",
            )
    finally:
        _logger.remove(sink_id)

    full_log = "\n".join(captured_messages)
    assert "sk-ant-LeAkEdSecret" not in full_log
    assert "[REDACTED]" in full_log
