"""
Characterization tests for ``tailor_resume`` in ``app/services/llm_gateway.py``.

These tests lock in the *current* contract of ``tailor_resume`` so that
regressions during the upcoming refactor surface immediately. They mock at
the HTTP boundary (``httpx.AsyncClient.post``) only — no provider class
methods or ``get_provider`` are patched.

Contract under test::

    async def tailor_resume(
        resume_ast: ResumeAST,
        job_description: str,
        strategy: RewriteStrategy,
        provider_name: str,
        encrypted_api_key: str,
    ) -> tuple[list[str], bool, str]

Returns: ``(tailored_bullets, used_fallback, summary)``.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

from app.middleware.circuit_breaker import CircuitState, llm_circuit
from app.services.llm_gateway import (
    RewriteStrategy,
    _parse_llm_response,
    tailor_resume,
)
from app.services.resume_parser import ResumeAST, ResumeBullet, ResumeSection

# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_llm_circuit() -> Iterator[None]:
    """Reset the module-level LLM circuit breaker between tests.

    The breaker is a singleton — a failing test would otherwise leave it
    in the OPEN state and break subsequent tests.
    """
    llm_circuit._state = CircuitState.CLOSED
    llm_circuit._failure_count = 0
    llm_circuit._success_count = 0
    llm_circuit._last_failure_time = None
    llm_circuit._half_open_calls = 0
    yield
    llm_circuit._state = CircuitState.CLOSED
    llm_circuit._failure_count = 0
    llm_circuit._success_count = 0
    llm_circuit._last_failure_time = None
    llm_circuit._half_open_calls = 0


@pytest.fixture
def fernet_settings(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure a real Fernet key on ``settings`` so ``decrypt_value`` works.

    Returns the key (also useful if a test needs to encrypt manually).
    """
    key = Fernet.generate_key().decode()
    # ``_get_fernet()`` reads settings.FERNET_KEY lazily, so a runtime patch is enough.
    from app.config import settings

    monkeypatch.setattr(settings, "FERNET_KEY", key)
    return key


@pytest.fixture
def encrypted_anthropic_key(fernet_settings: str) -> str:
    """Return a Fernet-encrypted blob that decrypts to a well-formed Anthropic key."""
    return Fernet(fernet_settings.encode()).encrypt(b"sk-ant-test1234567890abcdef").decode()


@pytest.fixture
def encrypted_openai_key(fernet_settings: str) -> str:
    """Return a Fernet-encrypted blob that decrypts to a well-formed OpenAI key."""
    return Fernet(fernet_settings.encode()).encrypt(b"sk-test1234567890abcdef").decode()


@pytest.fixture
def sample_resume_ast() -> ResumeAST:
    """A small ResumeAST with 3 bullets, all in EXPERIENCE."""
    ast = ResumeAST(source_format="docx")
    ast.bullets = [
        ResumeBullet(
            text="Built a distributed data pipeline processing 10M events daily.",
            section=ResumeSection.EXPERIENCE,
            company="Acme Corp",
            role="Senior Engineer",
            dates="2022-Present",
            original_index=0,
        ),
        ResumeBullet(
            text="Led migration from monolith to microservices, reducing deploy time 70%.",
            section=ResumeSection.EXPERIENCE,
            company="Acme Corp",
            role="Senior Engineer",
            dates="2022-Present",
            original_index=1,
        ),
        ResumeBullet(
            text="Mentored 4 junior engineers and ran weekly architecture reviews.",
            section=ResumeSection.EXPERIENCE,
            company="Acme Corp",
            role="Senior Engineer",
            dates="2022-Present",
            original_index=2,
        ),
    ]
    return ast


@pytest.fixture
def empty_resume_ast() -> ResumeAST:
    """A ResumeAST with no bullets (edge case)."""
    return ResumeAST(source_format="docx")


def _mock_anthropic_response(text: str, status_code: int = 200) -> MagicMock:
    """Build a fake httpx.Response shaped like the Anthropic Messages API."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = {"content": [{"text": text}]}
    response.raise_for_status = MagicMock()
    if status_code >= 400 and status_code not in (401, 429):
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response
        )
    return response


def _mock_openai_response(text: str, status_code: int = 200) -> MagicMock:
    """Build a fake httpx.Response shaped like the OpenAI Chat Completions API."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = {"choices": [{"message": {"content": text}}]}
    response.raise_for_status = MagicMock()
    if status_code >= 400 and status_code not in (401, 429):
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response
        )
    return response


# ──────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────


async def test_happy_path_anthropic_returns_expected_tuple_shape(
    sample_resume_ast: ResumeAST,
    encrypted_anthropic_key: str,
) -> None:
    """Successful Anthropic call returns ``(list[str], False, summary str)``."""
    llm_text = (
        "Architected a distributed data pipeline processing 10M events daily.\n"
        "Drove migration from monolith to microservices, slashing deploy time 70%.\n"
        "Coached 4 junior engineers and facilitated weekly architecture reviews."
    )
    fake_response = _mock_anthropic_response(llm_text)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)) as mock_post:
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=sample_resume_ast,
            job_description="We need a senior backend engineer with Python and distributed systems.",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key=encrypted_anthropic_key,
        )

    # Shape contract
    assert isinstance(bullets, list)
    assert all(isinstance(b, str) for b in bullets)
    assert isinstance(used_fallback, bool)
    assert isinstance(summary, str)

    # Behavior contract
    assert used_fallback is False
    assert len(bullets) == 3
    assert "moderate" in summary.lower()
    assert "anthropic" in summary
    mock_post.assert_awaited_once()
    # Verify we actually hit the Anthropic endpoint
    call_args = mock_post.await_args
    assert call_args is not None
    assert "api.anthropic.com" in call_args.args[0]


async def test_happy_path_openai_returns_expected_tuple_shape(
    sample_resume_ast: ResumeAST,
    encrypted_openai_key: str,
) -> None:
    """Successful OpenAI call returns ``(list[str], False, summary str)``."""
    llm_text = (
        "Engineered scalable pipelines for 10M events/day.\n"
        "Spearheaded the move to microservices, dropping deploy time by 70%.\n"
        "Guided junior engineers through architecture reviews."
    )
    fake_response = _mock_openai_response(llm_text)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)) as mock_post:
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=sample_resume_ast,
            job_description="Hiring Python engineers with cloud experience.",
            strategy=RewriteStrategy.SLIGHT_TWEAK,
            provider_name="openai",
            encrypted_api_key=encrypted_openai_key,
        )

    assert used_fallback is False
    assert len(bullets) == 3
    assert "openai" in summary
    assert "slight_tweak" in summary
    mock_post.assert_awaited_once()
    openai_call_args = mock_post.await_args
    assert openai_call_args is not None
    assert "api.openai.com" in openai_call_args.args[0]


# ──────────────────────────────────────────────────────────────────────────
# Edge case: empty resume
# ──────────────────────────────────────────────────────────────────────────


async def test_empty_bullet_list_returns_empty_bullets(
    empty_resume_ast: ResumeAST,
    encrypted_anthropic_key: str,
) -> None:
    """Empty resume AST → call still happens, returns empty bullet list.

    The LLM is asked to return 0 bullets; the function still issues the
    request, parses (no lines), and returns ``[]`` with no fallback.
    """
    fake_response = _mock_anthropic_response("")

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=empty_resume_ast,
            job_description="A job description.",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key=encrypted_anthropic_key,
        )

    assert bullets == []
    assert used_fallback is False
    assert isinstance(summary, str)


# ──────────────────────────────────────────────────────────────────────────
# Fallback paths — error → original bullets returned
# ──────────────────────────────────────────────────────────────────────────


async def test_provider_name_fallback_returns_original_bullets(
    sample_resume_ast: ResumeAST,
) -> None:
    """``provider_name='fallback'`` short-circuits to the keyword fallback path."""
    # No HTTP should be made — KeywordFallback returns the marker directly.
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=sample_resume_ast,
            job_description="A job description.",
            strategy=RewriteStrategy.MODERATE,
            provider_name="fallback",
            encrypted_api_key="",
        )

    mock_post.assert_not_awaited()
    assert used_fallback is True
    assert bullets == [b.text for b in sample_resume_ast.bullets]
    assert "LLM unavailable" in summary


async def test_invalid_api_key_format_falls_back_to_keyword(
    sample_resume_ast: ResumeAST,
    fernet_settings: str,
) -> None:
    """Decrypted key that fails ``validate_key_format`` triggers fallback.

    ``AnthropicProvider.validate_key_format`` requires ``sk-ant-`` prefix.
    A decrypted key without that prefix should swap to the fallback provider
    and no HTTP call should be made.
    """
    bad_key_encrypted = Fernet(fernet_settings.encode()).encrypt(b"not-an-anthropic-key").decode()

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=sample_resume_ast,
            job_description="A job description.",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key=bad_key_encrypted,
        )

    mock_post.assert_not_awaited()
    assert used_fallback is True
    assert bullets == [b.text for b in sample_resume_ast.bullets]
    assert "LLM unavailable" in summary


async def test_decrypt_failure_falls_back_to_keyword(
    sample_resume_ast: ResumeAST,
    fernet_settings: str,
) -> None:
    """A corrupt ``encrypted_api_key`` causes ``decrypt_value`` to raise → fallback."""
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=sample_resume_ast,
            job_description="A job description.",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key="not-a-valid-fernet-token",
        )

    mock_post.assert_not_awaited()
    assert used_fallback is True
    assert bullets == [b.text for b in sample_resume_ast.bullets]


async def test_http_401_returns_invalid_api_key_fallback(
    sample_resume_ast: ResumeAST,
    encrypted_anthropic_key: str,
) -> None:
    """HTTP 401 from the provider → InvalidAPIKeyError → original bullets returned."""
    response_401 = _mock_anthropic_response("", status_code=401)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response_401)):
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=sample_resume_ast,
            job_description="A job description.",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key=encrypted_anthropic_key,
        )

    assert used_fallback is True
    assert bullets == [b.text for b in sample_resume_ast.bullets]
    assert "invalid" in summary.lower()
    assert "anthropic" in summary


async def test_http_429_returns_rate_limit_fallback(
    sample_resume_ast: ResumeAST,
    encrypted_anthropic_key: str,
) -> None:
    """HTTP 429 from the provider → RateLimitError → original bullets returned."""
    response_429 = _mock_anthropic_response("", status_code=429)

    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response_429)):
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=sample_resume_ast,
            job_description="A job description.",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key=encrypted_anthropic_key,
        )

    assert used_fallback is True
    assert bullets == [b.text for b in sample_resume_ast.bullets]
    assert "rate limit" in summary.lower()


async def test_generic_http_failure_returns_llm_error_fallback(
    sample_resume_ast: ResumeAST,
    encrypted_anthropic_key: str,
) -> None:
    """A non-401/429 transport failure → generic exception branch → fallback."""
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
    ):
        bullets, used_fallback, summary = await tailor_resume(
            resume_ast=sample_resume_ast,
            job_description="A job description.",
            strategy=RewriteStrategy.MODERATE,
            provider_name="anthropic",
            encrypted_api_key=encrypted_anthropic_key,
        )

    assert used_fallback is True
    assert bullets == [b.text for b in sample_resume_ast.bullets]
    assert "LLM error" in summary


# ──────────────────────────────────────────────────────────────────────────
# _parse_llm_response — edge cases
# ──────────────────────────────────────────────────────────────────────────


def test_parse_llm_response_strips_numbered_prefixes() -> None:
    """``1. foo`` / ``2) bar`` / ``- baz`` / ``BULLET_3: qux`` prefixes are stripped."""
    raw = (
        "1. First bullet about backend engineering.\n"
        "2) Second bullet about distributed systems.\n"
        "- Third bullet about leadership.\n"
        "BULLET_3: Fourth bullet about mentoring.\n"
        "• Fifth bullet about architecture."
    )
    result = _parse_llm_response(raw, expected_count=5)
    assert result == [
        "First bullet about backend engineering.",
        "Second bullet about distributed systems.",
        "Third bullet about leadership.",
        "Fourth bullet about mentoring.",
        "Fifth bullet about architecture.",
    ]


def test_parse_llm_response_handles_extra_whitespace_and_blank_lines() -> None:
    """Blank lines and trailing/leading whitespace are normalized away."""
    raw = (
        "\n\n"
        "   First bullet has leading whitespace.   \n"
        "\n"
        "\t Second bullet has a tab and trailing space. \n"
        "\n\n"
        "Third bullet looks normal.\n"
        "\n"
    )
    result = _parse_llm_response(raw, expected_count=3)
    assert result == [
        "First bullet has leading whitespace.",
        "Second bullet has a tab and trailing space.",
        "Third bullet looks normal.",
    ]


def test_parse_llm_response_returns_fewer_than_expected_when_response_is_short() -> None:
    """If the LLM returns fewer bullets than requested, the parser does NOT pad.

    It returns what it got and logs a warning — the validator catches mismatches downstream.
    """
    raw = "Only one bullet here, but caller expected three."
    result = _parse_llm_response(raw, expected_count=3)
    assert result == ["Only one bullet here, but caller expected three."]
    assert len(result) < 3


def test_parse_llm_response_trims_when_response_has_extra_bullets() -> None:
    """If the LLM returns more bullets than requested, the parser trims to expected_count."""
    raw = "One.\nTwo two two two two.\nThree three three.\nFour four four.\nFive five five."
    result = _parse_llm_response(raw, expected_count=3)
    assert len(result) == 3
    assert result == ["Two two two two two.", "Three three three.", "Four four four."]


def test_parse_llm_response_handles_malformed_empty_response() -> None:
    """An empty/whitespace-only response yields ``[]``."""
    assert _parse_llm_response("", expected_count=3) == []
    assert _parse_llm_response("\n\n   \n\t\n", expected_count=3) == []


def test_parse_llm_response_drops_very_short_lines() -> None:
    """Lines that are <=5 chars after cleanup are skipped (formatting artifacts)."""
    raw = (
        "ok\n"  # too short
        "-\n"  # only formatting char
        "A proper bullet that should survive parsing.\n"
        "tiny\n"  # too short
        "Another well-formed bullet sentence."
    )
    result = _parse_llm_response(raw, expected_count=2)
    assert result == [
        "A proper bullet that should survive parsing.",
        "Another well-formed bullet sentence.",
    ]


def test_parse_llm_response_preserves_asterisk_prefix() -> None:
    """Asterisk prefixes (``*`` and ``**``) are NOT stripped by the cleanup regex.

    The cleanup regex character class is ``[-•●]`` — it intentionally excludes
    ``*``. This locks in that behavior so a refactor that adds ``*`` (e.g. to
    handle Markdown-style bullets) is caught as a behavior change.
    """
    raw = (
        "1. First bullet point text here.\n"
        "* Asterisk-prefixed bullet must NOT have asterisk stripped.\n"
        "**Bold marker** text preserved as-is."
    )
    result = _parse_llm_response(raw, expected_count=3)
    assert result == [
        "First bullet point text here.",
        "* Asterisk-prefixed bullet must NOT have asterisk stripped.",
        "**Bold marker** text preserved as-is.",
    ]
