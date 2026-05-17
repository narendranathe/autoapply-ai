"""
Security contract tests for Issue #197 (P0).

Confirms that all five LLM-driving vault endpoints:

  * accept the new ``providers`` contract — JSON list of ``{name, model}``
    entries WITHOUT ``api_key``;
  * reject the legacy ``providers_json`` field with HTTP 422;
  * 400 when the requested provider has no stored key for the user;
  * never write the decrypted key to the log stream.

The tests mock at the helper boundary so they exercise the routers'
contract without standing up a real DB. Helper unit tests pin
``_get_provider_key`` and ``_resolve_providers``.
"""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException


def _real_logger():
    """Return the loguru logger bound in the production module — robust against
    other unit tests that monkey-patch ``loguru.logger`` with a SimpleNamespace
    at module-replacement scope. We grab it from a fresh import context so the
    logger this test exercises is the one the production code is actually
    using.
    """
    # ``_shared.py`` imports loguru.logger at module-load and keeps it as a
    # local name; that reference survives any later monkey-patching of the
    # loguru module's attribute by sibling unit tests.
    from app.routers.vault import _shared as _shared_mod

    return _shared_mod.logger

# Ensure encryption is available BEFORE app imports — encrypt_value reads
# settings at call time, but the helpers we test under unit scope do the
# same lazily. Generating a fresh Fernet key per test process keeps the
# blob format deterministic and the decrypt path exercised.
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())

from app.config import settings  # noqa: E402

# Some other tests in this suite replace ``settings`` with a SimpleNamespace
# at import time. Tolerate that — we only need FERNET_KEY available where
# the helpers look for it.
if not getattr(settings, "FERNET_KEY", None):
    try:
        setattr(settings, "FERNET_KEY", os.environ["FERNET_KEY"])
    except (AttributeError, TypeError):
        # Frozen settings — fall back to mutating via __dict__ if possible.
        try:
            settings.__dict__["FERNET_KEY"] = os.environ["FERNET_KEY"]
        except Exception:
            pass

from app.routers.vault._shared import (  # noqa: E402
    _LEGACY_PROVIDERS_JSON_ERROR,
    _get_provider_key,
    _reject_legacy_providers_json,
    _resolve_providers,
)
from app.utils.encryption import encrypt_value  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: a mocked user_provider_configs row
# ---------------------------------------------------------------------------


def _mock_user(uid: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id = uid or uuid.uuid4()
    return user


def _row(provider: str, plaintext_key: str, model: str | None = None) -> MagicMock:
    row = MagicMock()
    row.provider_name = provider
    row.encrypted_api_key = encrypt_value(plaintext_key)
    row.model_override = model
    return row


def _db_returning(row_or_rows):
    """Build an async DB mock whose execute() returns either one row
    (scalar_one_or_none) or many rows (scalars().all())."""
    mock_db = AsyncMock()

    if isinstance(row_or_rows, list):
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = row_or_rows
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
    else:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row_or_rows

    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ---------------------------------------------------------------------------
# 1. Legacy field rejection (security regression guard)
# ---------------------------------------------------------------------------


def test_reject_legacy_providers_json_raises_422():
    """A non-empty ``providers_json`` form field must raise HTTP 422."""
    payload = json.dumps([{"name": "anthropic", "api_key": "sk-ant-leaked", "model": ""}])

    with pytest.raises(HTTPException) as exc:
        _reject_legacy_providers_json(payload)

    assert exc.value.status_code == 422
    assert _LEGACY_PROVIDERS_JSON_ERROR in str(exc.value.detail)


def test_reject_legacy_providers_json_empty_is_noop():
    """Blank ``providers_json`` is the no-op path — must NOT raise."""
    _reject_legacy_providers_json("")
    _reject_legacy_providers_json("   ")
    _reject_legacy_providers_json(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_resolve_providers_rejects_legacy_providers_json():
    """Resolution honors the legacy reject — pass-through to 422."""
    db = _db_returning([])
    user = _mock_user()
    with pytest.raises(HTTPException) as exc:
        await _resolve_providers(
            "",
            db,
            user,
            legacy_providers_json='[{"name":"anthropic","api_key":"sk-ant-x"}]',
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_resolve_providers_rejects_api_key_in_new_payload():
    """Even via the new ``providers`` field, ``api_key`` keys are forbidden."""
    db = _db_returning([])
    user = _mock_user()
    bad = json.dumps([{"name": "anthropic", "api_key": "sk-ant-leaked", "model": ""}])
    with pytest.raises(HTTPException) as exc:
        await _resolve_providers(bad, db, user)
    assert exc.value.status_code == 422
    assert _LEGACY_PROVIDERS_JSON_ERROR in str(exc.value.detail)


# ---------------------------------------------------------------------------
# 2. Server-side key lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_provider_key_returns_decrypted_value():
    plaintext = "sk-ant-real-test-key-123"
    db = _db_returning(_row("anthropic", plaintext))
    user = _mock_user()

    out = await _get_provider_key(db, user, "anthropic")

    assert out == plaintext


@pytest.mark.asyncio
async def test_get_provider_key_400_when_not_configured():
    db = _db_returning(None)
    user = _mock_user()

    with pytest.raises(HTTPException) as exc:
        await _get_provider_key(db, user, "anthropic")
    assert exc.value.status_code == 400
    assert "not configured" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_get_provider_key_400_when_blank_name():
    db = _db_returning(None)
    user = _mock_user()
    with pytest.raises(HTTPException) as exc:
        await _get_provider_key(db, user, "")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_resolve_providers_looks_up_key_per_entry():
    """Client sends {name, model}; resolver attaches decrypted api_key per entry."""
    plaintext = "sk-ant-stored-server-side"

    user = _mock_user()
    db = AsyncMock()

    # First execute() (inside _get_provider_key) returns the row.
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _row("anthropic", plaintext, "claude-sonnet-4-6")
    db.execute = AsyncMock(return_value=mock_result)

    payload = json.dumps([{"name": "anthropic", "model": "claude-sonnet-4-6"}])
    out = await _resolve_providers(payload, db, user)

    assert out == [
        {"name": "anthropic", "api_key": plaintext, "model": "claude-sonnet-4-6"}
    ]


@pytest.mark.asyncio
async def test_resolve_providers_400_for_unconfigured_provider():
    """When the user has no key for the requested provider → HTTP 400."""
    db = _db_returning(None)  # nothing stored
    user = _mock_user()

    payload = json.dumps([{"name": "openai", "model": "gpt-4o"}])
    with pytest.raises(HTTPException) as exc:
        await _resolve_providers(payload, db, user)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 3. Log scrubbing — decrypted key never reaches the log stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decrypted_key_never_logged_during_resolution():
    """Capture loguru output and assert the plaintext key is NOT present."""
    plaintext = "sk-ant-SECRET_TOKEN_THAT_MUST_NOT_LEAK_42"

    user = _mock_user()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = _row("anthropic", plaintext)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)

    logger = _real_logger()
    sink_records: list[str] = []
    sink_id = logger.add(lambda msg: sink_records.append(str(msg)), level="DEBUG")
    try:
        payload = json.dumps([{"name": "anthropic", "model": "claude-sonnet-4-6"}])
        out = await _resolve_providers(payload, db, user)
    finally:
        logger.remove(sink_id)

    # Sanity — we did get the key out.
    assert out[0]["api_key"] == plaintext

    # And it never reached the log buffer.
    full_log = "\n".join(sink_records)
    assert plaintext not in full_log
    assert "SECRET_TOKEN" not in full_log


@pytest.mark.asyncio
async def test_decrypted_key_never_logged_when_provider_unconfigured():
    """The 400 path must log a generic error — never any key fragment."""
    user = _mock_user()
    db = _db_returning(None)

    logger = _real_logger()
    sink_records: list[str] = []
    sink_id = logger.add(lambda msg: sink_records.append(str(msg)), level="DEBUG")
    try:
        with pytest.raises(HTTPException):
            await _get_provider_key(db, user, "anthropic")
    finally:
        logger.remove(sink_id)

    full_log = "\n".join(sink_records)
    # Should mention provider name + user_id, but no key material at all.
    assert "anthropic" in full_log
    assert "sk-ant" not in full_log
    assert "sk-" not in full_log or "[REDACTED]" in full_log


# ---------------------------------------------------------------------------
# 4. Endpoint-level contract: each of the 5+ endpoints round-trips correctly
# ---------------------------------------------------------------------------


def _make_db_with_row(provider: str, key_plaintext: str):
    """Build a DB mock that returns a row from execute() for one provider."""
    db = AsyncMock()
    row = _row(provider, key_plaintext)

    # The resolver and downstream queries (work_history, past answers, etc.)
    # all call db.execute(); we always answer with a list-like result that
    # also exposes ``scalar_one_or_none``. This keeps the mock generic.
    def make_result():
        scalars = MagicMock()
        scalars.all.return_value = []  # empty work history / past answers
        result = MagicMock()
        result.scalars.return_value = scalars
        result.scalar_one_or_none.return_value = row
        return result

    db.execute = AsyncMock(side_effect=lambda *a, **kw: make_result())
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_endpoint_generate_answers_rejects_legacy_providers_json():
    from app.routers.vault.answers import generate_answers

    user = _mock_user()
    db = _make_db_with_row("anthropic", "sk-ant-x")

    with pytest.raises(HTTPException) as exc:
        await generate_answers(
            question_text="Why us?",
            question_category="custom",
            company_name="TestCo",
            role_title="SWE",
            jd_text="JD",
            work_history_text="wh",
            llm_provider="anthropic",
            ollama_model="llama3.1:8b",
            providers="",
            providers_json='[{"name":"anthropic","api_key":"sk-ant-leaked"}]',
            max_length=0,
            category_instructions="",
            db=db,
            user=user,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_generate_answers_400_when_provider_unconfigured():
    from app.routers.vault.answers import generate_answers

    user = _mock_user()
    db = _make_db_with_row("anthropic", "sk-ant-x")
    # Override: scalar_one_or_none for provider lookup returns None
    none_result = MagicMock()
    none_result.scalar_one_or_none.return_value = None
    scalars = MagicMock()
    scalars.all.return_value = []
    none_result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=none_result)

    with pytest.raises(HTTPException) as exc:
        await generate_answers(
            question_text="Why us?",
            question_category="custom",
            company_name="TestCo",
            role_title="SWE",
            jd_text="JD",
            work_history_text="wh",
            llm_provider="anthropic",
            ollama_model="llama3.1:8b",
            providers='[{"name":"openai","model":"gpt-4o"}]',
            providers_json="",
            max_length=0,
            category_instructions="",
            db=db,
            user=user,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_endpoint_generate_answers_uses_server_side_key():
    """Happy path: client sends {name, model}, backend looks up the key,
    generator is invoked with the providers list containing the decrypted key."""
    from app.routers.vault import answers as answers_mod

    user = _mock_user()
    plaintext = "sk-ant-PLAINTEXT_SERVER_RESOLVED_KEY"
    db = _make_db_with_row("anthropic", plaintext)

    captured: dict = {}

    async def fake_cascade(**kwargs):
        captured.update(kwargs)
        return (["DRAFT 1", "DRAFT 2", "DRAFT 3"], "anthropic")

    with (
        patch.object(answers_mod, "generate_answer_drafts_cascade", side_effect=fake_cascade),
        patch.object(
            answers_mod,
            "get_rag_context_for_query",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch.object(answers_mod, "_agent") as mock_agent_factory,
    ):
        mock_agent = MagicMock()
        mock_agent.get_previous_answer = AsyncMock(return_value=None)
        mock_agent.get_best_answers_for_question = AsyncMock(return_value=[])
        mock_agent_factory.return_value = mock_agent

        result = await answers_mod.generate_answers(
            question_text="Why us?",
            question_category="custom",
            company_name="TestCo",
            role_title="SWE",
            jd_text="JD",
            work_history_text="wh",
            llm_provider="anthropic",
            ollama_model="llama3.1:8b",
            providers='[{"name":"anthropic","model":"claude-sonnet-4-6"}]',
            providers_json="",
            max_length=0,
            category_instructions="",
            db=db,
            user=user,
        )

    assert result["drafts"] == ["DRAFT 1", "DRAFT 2", "DRAFT 3"]
    sent_providers = captured["providers"]
    assert sent_providers[0]["name"] == "anthropic"
    assert sent_providers[0]["api_key"] == plaintext
    assert sent_providers[0]["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_endpoint_generate_summary_rejects_legacy_providers_json():
    from app.routers.vault.generate import generate_summary_endpoint

    user = _mock_user()
    db = _make_db_with_row("anthropic", "sk-ant-x")
    with pytest.raises(HTTPException) as exc:
        await generate_summary_endpoint(
            company_name="TestCo",
            role_title="SWE",
            jd_text="",
            word_limit=80,
            candidate_name="",
            providers="",
            providers_json='[{"name":"anthropic","api_key":"sk-ant-leaked"}]',
            db=db,
            user=user,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_generate_bullets_rejects_legacy_providers_json():
    from app.routers.vault.generate import generate_bullets_endpoint

    user = _mock_user()
    db = _make_db_with_row("anthropic", "sk-ant-x")
    with pytest.raises(HTTPException) as exc:
        await generate_bullets_endpoint(
            company_name="TestCo",
            role_title="SWE",
            jd_text="",
            num_bullets=5,
            target_company_for_context="",
            providers="",
            providers_json='[{"name":"anthropic","api_key":"sk-ant-leaked"}]',
            db=db,
            user=user,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_generate_cover_letter_rejects_legacy_providers_json():
    from app.routers.vault.generate import generate_cover_letter_endpoint

    user = _mock_user()
    db = _make_db_with_row("anthropic", "sk-ant-x")
    with pytest.raises(HTTPException) as exc:
        await generate_cover_letter_endpoint(
            company_name="TestCo",
            role_title="SWE",
            jd_text="",
            tone="professional",
            word_limit=400,
            candidate_name="",
            providers="",
            providers_json='[{"name":"anthropic","api_key":"sk-ant-leaked"}]',
            db=db,
            user=user,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_generate_tailored_rejects_legacy_providers_json():
    from app.routers.vault.generate import generate_tailored_resume

    user = _mock_user()
    db = _make_db_with_row("anthropic", "sk-ant-x")
    with pytest.raises(HTTPException) as exc:
        await generate_tailored_resume(
            base_resume_id=str(uuid.uuid4()),
            jd_text="JD",
            company_name="TestCo",
            role_title="SWE",
            providers="",
            providers_json='[{"name":"anthropic","api_key":"sk-ant-leaked"}]',
            db=db,
            user=user,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_interview_prep_rejects_legacy_providers_json():
    from app.routers.vault.interview import generate_interview_prep

    user = _mock_user()
    db = _make_db_with_row("anthropic", "sk-ant-x")
    with pytest.raises(HTTPException) as exc:
        await generate_interview_prep(
            company_name="TestCo",
            role_title="SWE",
            jd_text="",
            providers="",
            providers_json='[{"name":"anthropic","api_key":"sk-ant-leaked"}]',
            db=db,
            user=user,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_trim_answer_rejects_legacy_providers_json():
    from app.routers.vault.answers import trim_answer

    user = _mock_user()
    db = _make_db_with_row("anthropic", "sk-ant-x")
    long_text = "x" * 200
    with pytest.raises(HTTPException) as exc:
        await trim_answer(
            answer_text=long_text,
            max_chars=50,
            providers="",
            providers_json='[{"name":"anthropic","api_key":"sk-ant-leaked"}]',
            db=db,
            user=user,
        )
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# 5. Happy-path: interview-prep with stored anthropic key works end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_interview_prep_uses_server_side_key():
    """`providers: [{name, model}]` + stored key → 200, generation works,
    decrypted key passed to gateway, never leaks to log."""
    from app.routers.vault import interview as interview_mod

    user = _mock_user()
    plaintext = "sk-ant-INTERVIEW_PLAINTEXT_KEY_99"
    db = _make_db_with_row("anthropic", plaintext)

    captured_kwargs: dict = {}

    async def fake_generate(**kwargs):
        captured_kwargs.update(kwargs)
        return (
            json.dumps([{"question": "Q", "category": "general", "suggested_answer": "A"}]),
            "anthropic",
        )

    logger = _real_logger()
    sink_records: list[str] = []
    sink_id = logger.add(lambda msg: sink_records.append(str(msg)), level="DEBUG")
    try:
        with patch.object(
            interview_mod.LLMGateway,
            "generate",
            new=AsyncMock(side_effect=fake_generate),
        ):
            result = await interview_mod.generate_interview_prep(
                company_name="TestCo",
                role_title="SWE",
                jd_text="JD",
                providers='[{"name":"anthropic","model":"claude-sonnet-4-6"}]',
                providers_json="",
                db=db,
                user=user,
            )
    finally:
        logger.remove(sink_id)

    assert result["total"] == 1
    # Key reached the gateway intact:
    assert captured_kwargs["api_key"] == plaintext
    assert captured_kwargs["provider"] == "anthropic"
    # Key did NOT leak into the log:
    full_log = "\n".join(sink_records)
    assert plaintext not in full_log
    assert "INTERVIEW_PLAINTEXT_KEY" not in full_log
