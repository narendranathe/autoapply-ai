"""Tests for ``LLMGenerationError`` — structured per-attempt error type.

Issue #107 — Phase 2. The error exposes ``provider``, ``attempt_number``
and ``cause`` so callers can build per-attempt observability without
parsing strings.
"""

from __future__ import annotations

import pytest

from app.services.llm_gateway import LLMGenerationError


def test_error_is_an_exception():
    err = LLMGenerationError(
        "provider 'anthropic' raised",
        provider="anthropic",
        attempt_number=1,
    )
    assert isinstance(err, Exception)


def test_error_carries_structured_fields():
    cause = TimeoutError("upstream slow")
    err = LLMGenerationError(
        "boom",
        provider="anthropic",
        attempt_number=2,
        cause=cause,
    )
    assert err.provider == "anthropic"
    assert err.attempt_number == 2
    assert err.cause is cause


def test_error_cause_defaults_to_none():
    err = LLMGenerationError("no cause", provider="openai", attempt_number=1)
    assert err.cause is None


def test_error_str_returns_message():
    err = LLMGenerationError(
        "message body",
        provider="groq",
        attempt_number=1,
    )
    assert "message body" in str(err)


def test_error_repr_shows_provider_and_attempt():
    err = LLMGenerationError(
        "x",
        provider="kimi",
        attempt_number=3,
        cause=ValueError("inner"),
    )
    text = repr(err)
    assert "kimi" in text
    assert "attempt_number=3" in text
    assert "ValueError" in text


def test_error_keyword_only_construction():
    """Provider / attempt_number / cause must be supplied as kwargs."""
    with pytest.raises(TypeError):
        LLMGenerationError("msg", "anthropic", 1)  # type: ignore[misc]


def test_error_is_importable_from_top_level_module():
    """Spec requires direct import from ``app.services.llm_gateway``."""
    from app.services import llm_gateway

    assert hasattr(llm_gateway, "LLMGenerationError")
    assert llm_gateway.LLMGenerationError is LLMGenerationError
