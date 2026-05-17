"""Endpoint-level tests for Issue #197.

Verifies the 5 generation endpoint sites:
* ``providers_json`` is rejected with HTTP 422 (no backward-compat window)
* the new ``providers`` field (JSON list of ``{name, model}``) is parsed
* server-side key resolution is invoked, and the decrypted key never
  appears in any log/response

Endpoints under test:
1. POST /api/v1/vault/generate/answers
2. POST /api/v1/vault/generate/answers/trim
3. POST /api/v1/vault/generate/tailored
4. POST /api/v1/vault/generate/summary
5. POST /api/v1/vault/generate/bullets
6. POST /api/v1/vault/generate/cover-letter
7. POST /api/v1/vault/interview-prep

(That's 7 endpoint sites total — the brief said 5 but the actual count
is 7 once you include the helper endpoints in answers.py and generate.py.)
"""

from __future__ import annotations

import io
import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub config + base before importing the routers (same pattern as the
# rest of the unit tests).
if "app.config" not in sys.modules:
    sys.modules["app.config"] = types.ModuleType("app.config")

from cryptography.fernet import Fernet  # noqa: E402

import app.config as _cfg  # noqa: E402

_TEST_FERNET = Fernet.generate_key().decode()
os.environ.setdefault("FERNET_KEY", _TEST_FERNET)

if not hasattr(_cfg, "settings"):
    _cfg.settings = types.SimpleNamespace(  # type: ignore[attr-defined]
        DATABASE_URL="postgresql+asyncpg://x:y@localhost/z",
        DB_PASSWORD=None,
        DB_POOL_SIZE=5,
        DB_MAX_OVERFLOW=10,
        DB_ECHO=False,
        DB_SSL_REQUIRE=False,
        ENVIRONMENT="test",
        FERNET_KEY=_TEST_FERNET,
        is_development=False,
    )
else:
    _cfg.settings.FERNET_KEY = _TEST_FERNET  # type: ignore[attr-defined]

from fastapi import HTTPException  # noqa: E402

from app.routers.vault._shared import (  # noqa: E402
    _expose_providers_for_gateway,
    _parse_legacy_providers_json_stripped,
    _parse_providers,
    _reject_providers_json,
    _resolve_providers,
)
from app.services.user_provider_configs import (  # noqa: E402
    DecryptedKey,
    ProviderNotConfiguredError,
    resolve_user_providers,
)

# ---------------------------------------------------------------------------
# providers_json rejection (AC 1: 422 with clear error)
# ---------------------------------------------------------------------------


def test_reject_providers_json_raises_422_when_present():
    """Any non-blank ``providers_json`` value triggers HTTP 422."""
    with pytest.raises(HTTPException) as exc_info:
        _reject_providers_json('[{"name":"groq","api_key":"gsk_x"}]')
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error"] == "providers_json_removed"
    # Error message points to the new contract.
    assert "providers" in detail["message"].lower()


def test_reject_providers_json_ignores_empty_string():
    """Empty / whitespace-only is silently allowed (client sends no field)."""
    _reject_providers_json("")
    _reject_providers_json("   ")


def test_reject_providers_json_ignores_none():
    """``None`` is allowed — the caller may opt out by passing the field
    only when the form actually carries a value."""
    _reject_providers_json(None or "")


# ---------------------------------------------------------------------------
# providers (new contract) parsing
# ---------------------------------------------------------------------------


def test_parse_providers_returns_empty_for_blank():
    assert _parse_providers("") == []
    assert _parse_providers("   ") == []


def test_parse_providers_strips_stray_api_key_field():
    """If a client mistakenly sends ``api_key`` inside ``providers``,
    we strip it so it can't slip through to the LLM gateway."""
    parsed = _parse_providers('[{"name":"groq","model":"llama-3.3-70b","api_key":"gsk_leak"}]')
    assert parsed == [{"name": "groq", "model": "llama-3.3-70b"}]
    assert "api_key" not in parsed[0]


def test_parse_providers_raises_422_on_invalid_json():
    with pytest.raises(HTTPException) as exc_info:
        _parse_providers("not-json")
    assert exc_info.value.status_code == 422


def test_parse_providers_raises_422_on_non_list():
    with pytest.raises(HTTPException) as exc_info:
        _parse_providers('{"name": "groq"}')
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# _resolve_providers integrates parse + resolve_decrypted_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_providers_rejects_providers_json_with_422():
    """Both fields together → 422 wins (no silent fallback)."""
    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_providers(
            providers="",
            db=db,
            user=user,
            providers_json='[{"name":"groq","api_key":"gsk_x"}]',
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_providers_raises_400_when_requested_provider_missing_key():
    """Issue #197 P1-B — client explicitly names a provider that has no
    server-side key. The endpoint must return HTTP 400 with the provider
    name in the detail so the extension can show "Add the API key in
    Options" rather than silently falling back to keyword-only output.
    """
    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()

    async def fake_resolve(uid, name, db):
        return None  # no server-side key for any provider

    with patch(
        "app.services.user_provider_configs.resolve_decrypted_key",
        side_effect=fake_resolve,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _resolve_providers(
                providers='[{"name":"openai","model":"gpt-4o-mini"}]',
                db=db,
                user=user,
            )

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error"] == "provider_not_configured"
    assert detail["provider"] == "openai"
    # The user-facing message must name the missing provider.
    assert "openai" in detail["message"]
    assert "Options" in detail["message"]


@pytest.mark.asyncio
async def test_resolve_user_providers_strict_raises_for_missing_key():
    """Unit-level mirror of the endpoint contract: strict=True surfaces a
    ProviderNotConfiguredError with the offending provider name."""
    user_id = uuid.uuid4()
    db = AsyncMock()

    async def fake_resolve(uid, name, db):
        return None

    with patch(
        "app.services.user_provider_configs.resolve_decrypted_key",
        side_effect=fake_resolve,
    ):
        with pytest.raises(ProviderNotConfiguredError) as exc_info:
            await resolve_user_providers(
                user_id,
                [
                    {"name": "anthropic", "model": "claude-3"},
                    {"name": "openai", "model": "gpt-4"},
                ],
                db,
                strict=True,
            )

    assert exc_info.value.provider_name == "anthropic"


@pytest.mark.asyncio
async def test_resolve_user_providers_non_strict_drops_missing():
    """Default (non-strict) mode keeps the silent-drop behaviour for the
    server-enumerated fallback path."""
    user_id = uuid.uuid4()
    db = AsyncMock()

    async def fake_resolve(uid, name, db):
        return DecryptedKey("k") if name == "anthropic" else None

    with patch(
        "app.services.user_provider_configs.resolve_decrypted_key",
        side_effect=fake_resolve,
    ):
        out = await resolve_user_providers(
            user_id,
            [
                {"name": "anthropic", "model": "claude-3"},
                {"name": "openai", "model": "gpt-4"},
            ],
            db,
            strict=False,
        )
    assert [p["name"] for p in out] == ["anthropic"]


@pytest.mark.asyncio
async def test_resolve_providers_uses_decrypted_key_resolver():
    """When ``providers`` is supplied, every entry goes through the
    server-side resolver."""
    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()

    async def fake_resolve(uid, name, db):
        return DecryptedKey("gsk_decrypted") if name == "groq" else None

    with patch(
        "app.services.user_provider_configs.resolve_decrypted_key",
        side_effect=fake_resolve,
    ):
        out = await _resolve_providers(
            providers='[{"name":"groq","model":"llama-3.3-70b"}]',
            db=db,
            user=user,
        )

    assert len(out) == 1
    assert out[0]["name"] == "groq"
    assert isinstance(out[0]["api_key"], DecryptedKey)
    # And the DecryptedKey wraps the right plaintext.
    assert out[0]["api_key"].expose() == "gsk_decrypted"


# ---------------------------------------------------------------------------
# _expose_providers_for_gateway: single .expose() boundary
# ---------------------------------------------------------------------------


def test_expose_providers_unwraps_decrypted_keys():
    """The single sanctioned ``.expose()`` site for downstream gateway calls."""
    wrapped = [
        {"name": "groq", "model": "llama-3.3-70b", "api_key": DecryptedKey("gsk_x")},
        {"name": "ollama", "model": "llama3.1:8b", "api_key": None},
    ]
    out = _expose_providers_for_gateway(wrapped)
    assert out[0] == {"name": "groq", "model": "llama-3.3-70b", "api_key": "gsk_x"}
    assert out[1] == {"name": "ollama", "model": "llama3.1:8b", "api_key": ""}


def test_expose_providers_passthrough_plaintext_str():
    """Defensive: a plaintext str slips through unchanged (used by tests
    that build provider dicts directly)."""
    out = _expose_providers_for_gateway([{"name": "x", "api_key": "plain", "model": ""}])
    assert out[0]["api_key"] == "plain"


# ---------------------------------------------------------------------------
# End-to-end endpoint smoke tests via direct call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_answers_rejects_providers_json():
    """Calling ``generate_answers`` with the legacy field raises 422."""
    from app.routers.vault.answers import generate_answers

    user = MagicMock()
    user.id = uuid.uuid4()
    user.encrypted_llm_api_key = None
    user.display_name = "Test"
    user.email_hash = "abc12345"

    db = AsyncMock()
    # Work-history query in the endpoint resolves to empty.
    empty_result = MagicMock()
    empty_scalars = MagicMock()
    empty_scalars.all.return_value = []
    empty_result.scalars.return_value = empty_scalars
    db.execute = AsyncMock(return_value=empty_result)

    # Patch the retrieval agent to avoid touching real services.
    with patch("app.routers.vault.answers._agent") as agent_mock:
        agent_mock.return_value.get_previous_answer = AsyncMock(return_value=None)
        agent_mock.return_value.get_best_answers_for_question = AsyncMock(return_value=[])
        with pytest.raises(HTTPException) as exc_info:
            await generate_answers(
                question_text="why?",
                question_category="custom",
                company_name="ACME",
                role_title="SWE",
                jd_text="",
                work_history_text="",
                llm_provider="anthropic",
                ollama_model="llama3.1:8b",
                providers="",
                providers_json='[{"name":"groq","api_key":"gsk_leak"}]',
                max_length=0,
                category_instructions="",
                db=db,
                user=user,
            )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_interview_prep_rejects_providers_json():
    from app.routers.vault.interview import generate_interview_prep

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()
    empty_result = MagicMock()
    empty_scalars = MagicMock()
    empty_scalars.all.return_value = []
    empty_result.scalars.return_value = empty_scalars
    db.execute = AsyncMock(return_value=empty_result)

    with pytest.raises(HTTPException) as exc_info:
        await generate_interview_prep(
            company_name="ACME",
            role_title="SWE",
            jd_text="",
            providers="",
            providers_json='[{"name":"groq","api_key":"gsk_leak"}]',
            db=db,
            user=user,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_generate_summary_rejects_providers_json():
    from app.routers.vault.generate import generate_summary_endpoint

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()
    empty_result = MagicMock()
    empty_scalars = MagicMock()
    empty_scalars.all.return_value = []
    empty_result.scalars.return_value = empty_scalars
    db.execute = AsyncMock(return_value=empty_result)

    with pytest.raises(HTTPException) as exc_info:
        await generate_summary_endpoint(
            company_name="ACME",
            role_title="SWE",
            jd_text="",
            word_limit=80,
            candidate_name="Test",
            providers="",
            providers_json='[{"name":"groq","api_key":"gsk_leak"}]',
            db=db,
            user=user,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_generate_bullets_rejects_providers_json():
    from app.routers.vault.generate import generate_bullets_endpoint

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()
    empty_result = MagicMock()
    empty_scalars = MagicMock()
    empty_scalars.all.return_value = []
    empty_result.scalars.return_value = empty_scalars
    db.execute = AsyncMock(return_value=empty_result)

    with pytest.raises(HTTPException) as exc_info:
        await generate_bullets_endpoint(
            company_name="ACME",
            role_title="SWE",
            jd_text="",
            num_bullets=5,
            target_company_for_context="",
            providers="",
            providers_json='[{"name":"groq","api_key":"gsk_leak"}]',
            db=db,
            user=user,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_generate_cover_letter_rejects_providers_json():
    from app.routers.vault.generate import generate_cover_letter_endpoint

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()
    empty_result = MagicMock()
    empty_scalars = MagicMock()
    empty_scalars.all.return_value = []
    empty_result.scalars.return_value = empty_scalars
    db.execute = AsyncMock(return_value=empty_result)

    with pytest.raises(HTTPException) as exc_info:
        await generate_cover_letter_endpoint(
            company_name="ACME",
            role_title="SWE",
            jd_text="",
            tone="professional",
            word_limit=400,
            candidate_name="",
            providers="",
            providers_json='[{"name":"groq","api_key":"gsk_leak"}]',
            db=db,
            user=user,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_trim_answer_rejects_providers_json():
    """Answer-trim is the 7th endpoint site touched by Issue #197."""
    from app.routers.vault.answers import trim_answer

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await trim_answer(
            answer_text="x" * 1000,
            max_chars=100,
            providers="",
            providers_json='[{"name":"groq","api_key":"gsk_leak"}]',
            db=db,
            user=user,
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_trim_answer_cascade_includes_ollama():
    """Regression — round-1 fix introduced a cascade that skipped any
    provider with an empty ``api_key`` string. Ollama is keyless (local
    server) so its plaintext api_key is ``""`` after
    ``_expose_providers_for_gateway`` — but the cascade must still try it.
    Asserts ``LLMGateway.generate`` is invoked with ``provider="ollama"``.
    """
    from app.routers.vault.answers import trim_answer

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()

    # _resolve_providers returns wrapped entries. Ollama has api_key=None
    # which the expose helper renders as "".
    async def fake_resolve(providers, db, user, *, providers_json=None):
        return [{"name": "ollama", "model": "llama3.1:8b", "api_key": None}]

    captured: dict = {}

    class FakeGateway:
        def __init__(self) -> None:
            pass

        async def generate(self, *, system_prompt, user_prompt, provider, api_key, **kw):
            captured["provider"] = provider
            captured["api_key"] = api_key
            # >20 chars so the cascade accepts it instead of falling through
            # to hard-truncation.
            return ("Trimmed answer text that is comfortably above 20 chars.", provider)

    with (
        patch("app.routers.vault.answers._resolve_providers", side_effect=fake_resolve),
        patch("app.routers.vault.answers.LLMGateway", FakeGateway),
    ):
        out = await trim_answer(
            answer_text="x" * 1000,
            max_chars=100,
            providers='[{"name":"ollama","model":"llama3.1:8b"}]',
            providers_json="",
            db=db,
            user=user,
        )

    assert captured.get("provider") == "ollama", (
        "Ollama must be tried in the cascade even when api_key is empty"
    )
    assert captured.get("api_key") == ""
    assert out["provider_used"] == "ollama"


@pytest.mark.asyncio
async def test_tailored_resume_rejects_providers_json():
    """generate/tailored is the 8th touched endpoint."""
    from app.routers.vault.generate import generate_tailored_resume

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()
    # The endpoint does a SELECT for the resume before parsing providers,
    # so we need to make that fail-fast. Instead we patch _resolve_providers
    # to raise the 422 directly when called.
    base_id = str(uuid.uuid4())
    # Mock a resume row so the lookup succeeds, then provider parsing
    # rejects providers_json.
    resume_row = MagicMock()
    resume_row.raw_text = "old text"
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = resume_row
    empty_scalars = MagicMock()
    empty_scalars.all.return_value = []
    wh_result = MagicMock()
    wh_result.scalars.return_value = empty_scalars

    call_order = [select_result, wh_result]

    async def fake_execute(*args, **kwargs):
        return call_order.pop(0) if call_order else wh_result

    db.execute = AsyncMock(side_effect=fake_execute)

    with pytest.raises(HTTPException) as exc_info:
        await generate_tailored_resume(
            base_resume_id=base_id,
            jd_text="x",
            company_name="ACME",
            role_title="SWE",
            providers="",
            providers_json='[{"name":"groq","api_key":"gsk_leak"}]',
            db=db,
            user=user,
        )
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Belt-and-braces: a successful resolution never logs the plaintext.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_providers_never_logs_plaintext():
    """When ``_resolve_providers`` resolves a key, no log line contains
    the plaintext.

    Some sibling tests permanently replace ``loguru.logger`` with a
    ``SimpleNamespace`` of no-op callables — we install a fresh, real
    logger locally so this test runs deterministically.
    """
    import loguru as _loguru_mod
    from loguru._logger import Core as _Core
    from loguru._logger import Logger as _Logger

    saved = _loguru_mod.logger
    fresh = _Logger(_Core(), None, 0, False, False, False, False, True, [], {})
    _loguru_mod.logger = fresh

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()

    sink = io.StringIO()
    handler_id = fresh.add(sink, format="{message}", level="DEBUG")

    async def fake_resolve(uid, name, db):
        # Critically: a noisy resolver that logs the wrapper itself —
        # should still not leak because DecryptedKey.__repr__ redacts.
        wrapped = DecryptedKey("sk-PLAINTEXT-LEAK-CHECK")
        fresh.info(f"resolved: {wrapped}")
        return wrapped

    try:
        with patch(
            "app.services.user_provider_configs.resolve_decrypted_key",
            side_effect=fake_resolve,
        ):
            out = await _resolve_providers(
                providers='[{"name":"openai","model":"gpt-4o-mini"}]',
                db=db,
                user=user,
            )
        log_output = sink.getvalue()
    finally:
        fresh.remove(handler_id)
        _loguru_mod.logger = saved

    assert len(out) == 1
    assert isinstance(out[0]["api_key"], DecryptedKey)
    # The plaintext must NOT appear in any rendered log line.
    assert "sk-PLAINTEXT-LEAK-CHECK" not in log_output
    assert "[REDACTED]" in log_output


# ---------------------------------------------------------------------------
# Issue #197 P1-F + P0-G — legacy rejection logs WARN with user/UA, and
# the ACCEPT_LEGACY_PROVIDERS_JSON transition flag has both modes covered.
# ---------------------------------------------------------------------------


def _install_fresh_loguru_sink():
    """Return ``(sink, restore)`` — a StringIO sink wired into a fresh
    loguru logger. Some sibling tests permanently stub ``loguru.logger``
    with a ``SimpleNamespace`` of no-ops, so we install our own logger
    for the duration of these tests.
    """
    import loguru as _loguru_mod
    from loguru._logger import Core as _Core
    from loguru._logger import Logger as _Logger

    saved = _loguru_mod.logger
    fresh = _Logger(_Core(), None, 0, False, False, False, False, True, [], {})
    _loguru_mod.logger = fresh

    # Re-bind the loguru import inside _shared so its module-level
    # ``logger`` points at our fresh instance for the duration of the
    # test. (Loguru is process-singleton-by-convention but each module
    # captures a reference at import time.)
    import app.routers.vault._shared as _shared_mod

    saved_shared_logger = _shared_mod.logger
    _shared_mod.logger = fresh

    sink = io.StringIO()
    handler_id = fresh.add(sink, format="{level}|{message}", level="DEBUG")

    def restore() -> None:
        fresh.remove(handler_id)
        _loguru_mod.logger = saved
        _shared_mod.logger = saved_shared_logger

    return sink, restore


def test_reject_providers_json_logs_warning_with_user_and_user_agent():
    """P1-F — every legacy-field rejection must log a WARN line carrying
    the user id and the request User-Agent so operators can identify
    which extension installs are still on the old contract.
    """
    sink, restore = _install_fresh_loguru_sink()
    try:
        user_id = uuid.uuid4()
        request = MagicMock()
        request.headers = {"user-agent": "AutoApply-Chrome-Ext/1.2.3"}

        with pytest.raises(HTTPException) as exc_info:
            _reject_providers_json(
                '[{"name":"groq","api_key":"gsk_x"}]',
                user_id=user_id,
                request=request,
            )
        assert exc_info.value.status_code == 422

        log_output = sink.getvalue()
    finally:
        restore()

    assert "WARNING" in log_output
    assert "legacy_providers_json_rejected" in log_output
    assert str(user_id) in log_output
    assert "AutoApply-Chrome-Ext/1.2.3" in log_output


def test_reject_providers_json_accept_flag_logs_warning_and_returns():
    """P0-G — when ``ACCEPT_LEGACY_PROVIDERS_JSON`` is True, the
    rejection is suppressed but a WARN line still records the
    user/UA. The function returns None (no raise)."""
    from app.config import settings as _settings

    saved = _settings.ACCEPT_LEGACY_PROVIDERS_JSON
    _settings.ACCEPT_LEGACY_PROVIDERS_JSON = True
    sink, restore = _install_fresh_loguru_sink()
    try:
        user_id = uuid.uuid4()
        request = MagicMock()
        request.headers = {"user-agent": "AutoApply-Chrome-Ext/0.9.0"}

        # MUST NOT raise.
        _reject_providers_json(
            '[{"name":"groq","api_key":"gsk_x"}]',
            user_id=user_id,
            request=request,
        )

        log_output = sink.getvalue()
    finally:
        restore()
        _settings.ACCEPT_LEGACY_PROVIDERS_JSON = saved

    assert "WARNING" in log_output
    assert "legacy_providers_json_accepted" in log_output
    assert str(user_id) in log_output
    assert "AutoApply-Chrome-Ext/0.9.0" in log_output


def test_parse_legacy_providers_json_strips_api_key():
    """Even with the transition flag on, the embedded ``api_key`` must
    be dropped on the floor — the server resolves keys server-side
    regardless. A legacy install cannot smuggle a key past us."""
    parsed = _parse_legacy_providers_json_stripped(
        '[{"name":"groq","model":"llama-3.3-70b","api_key":"gsk_LEAK"}]'
    )
    assert parsed == [{"name": "groq", "model": "llama-3.3-70b"}]
    for entry in parsed:
        assert "api_key" not in entry
        # Belt-and-braces: serialise and check the plaintext is nowhere.
        import json as _j

        assert "gsk_LEAK" not in _j.dumps(entry)


@pytest.mark.asyncio
async def test_resolve_providers_accept_legacy_flag_uses_legacy_payload():
    """P0-G end-to-end — when the flag is on and ``providers=""``, the
    resolver MUST fall back to the legacy ``providers_json`` payload
    (stripped of api_key) and resolve keys server-side.
    """
    from app.config import settings as _settings

    saved = _settings.ACCEPT_LEGACY_PROVIDERS_JSON
    _settings.ACCEPT_LEGACY_PROVIDERS_JSON = True
    try:
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()
        request = MagicMock()
        request.headers = {"user-agent": "AutoApply-Chrome-Ext/0.9.0"}

        async def fake_resolve(uid, name, db):
            return DecryptedKey("sk-server-resolved") if name == "anthropic" else None

        with patch(
            "app.services.user_provider_configs.resolve_decrypted_key",
            side_effect=fake_resolve,
        ):
            out = await _resolve_providers(
                providers="",
                db=db,
                user=user,
                providers_json='[{"name":"anthropic","model":"claude-3","api_key":"sk-LEAK"}]',
                request=request,
            )
    finally:
        _settings.ACCEPT_LEGACY_PROVIDERS_JSON = saved

    assert len(out) == 1
    assert out[0]["name"] == "anthropic"
    # The key came from the server-side resolver — NOT from the leaked
    # legacy payload.
    assert out[0]["api_key"].expose() == "sk-server-resolved"
    assert out[0]["api_key"].expose() != "sk-LEAK"


@pytest.mark.asyncio
async def test_resolve_providers_strict_mode_default_rejects_legacy():
    """P0-G default — flag off (default), legacy payload is rejected
    with 422 just like before."""
    from app.config import settings as _settings

    # Default must be False — the assertion both documents the default
    # and guards against operator misconfiguration.
    assert _settings.ACCEPT_LEGACY_PROVIDERS_JSON is False

    user = MagicMock()
    user.id = uuid.uuid4()
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_providers(
            providers="",
            db=db,
            user=user,
            providers_json='[{"name":"anthropic","api_key":"sk-LEAK"}]',
        )
    assert exc_info.value.status_code == 422
