"""Unit tests for ``resolve_decrypted_key`` and ``resolve_user_providers``.

Issue #197 — the resolver is the single seam through which a user's
encrypted API key is decrypted in-memory. Everything else in the stack
should go through it.
"""

from __future__ import annotations

import os
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub config so importing the model doesn't try to spin up an engine.
if "app.config" not in sys.modules:
    sys.modules["app.config"] = types.ModuleType("app.config")

from cryptography.fernet import Fernet  # noqa: E402

import app.config as _cfg  # noqa: E402

# Generate a stable Fernet key for the test process if the env var is
# unset. The encryption util reads ``settings.FERNET_KEY`` lazily so we
# can patch it on the settings singleton.
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

import sqlalchemy as _sa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncAttrs  # noqa: E402
from sqlalchemy.orm import DeclarativeBase  # noqa: E402

_base_stub = types.ModuleType("app.models.base")


class _Base(AsyncAttrs, DeclarativeBase):
    pass


class _TimestampMixin:
    from datetime import datetime

    from sqlalchemy import DateTime, func
    from sqlalchemy.orm import Mapped, mapped_column

    created_at: Mapped[datetime] = mapped_column(
        _sa.DateTime(timezone=True), server_default=_sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        _sa.DateTime(timezone=True), server_default=_sa.func.now(), nullable=False
    )


_base_stub.Base = _Base  # type: ignore[attr-defined]
_base_stub.TimestampMixin = _TimestampMixin  # type: ignore[attr-defined]
sys.modules["app.models.base"] = _base_stub

from app.services.user_provider_configs import (  # noqa: E402
    DecryptedKey,
    resolve_decrypted_key,
    resolve_user_providers,
)
from app.utils.encryption import encrypt_value  # noqa: E402


@pytest.fixture(autouse=True)
def _ensure_fernet_key():
    """Pin ``FERNET_KEY`` before each test.

    ``app.utils.encryption`` binds ``settings`` at import time via
    ``from app.config import settings`` — so it is sensitive to anything
    that swaps ``app.config.settings`` after the encryption module was
    imported. We patch BOTH bindings.
    """
    import app.config as _live_cfg
    import app.utils.encryption as _enc

    saved_cfg = _live_cfg.settings
    saved_enc_settings = _enc.settings

    pinned = types.SimpleNamespace(FERNET_KEY=_TEST_FERNET)
    _live_cfg.settings = pinned  # type: ignore[attr-defined]
    _enc.settings = pinned  # type: ignore[attr-defined]
    try:
        yield
    finally:
        _live_cfg.settings = saved_cfg  # type: ignore[attr-defined]
        _enc.settings = saved_enc_settings  # type: ignore[attr-defined]


def _mock_db_with_row(row):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


@pytest.mark.asyncio
async def test_resolve_decrypted_key_returns_wrapped_secret():
    """Happy path: row exists with encrypted key → return DecryptedKey."""
    user_id = uuid.uuid4()
    row = MagicMock()
    row.encrypted_api_key = encrypt_value("sk-ant-secret-12345")
    db = _mock_db_with_row(row)

    key = await resolve_decrypted_key(user_id, "anthropic", db)

    assert isinstance(key, DecryptedKey)
    assert key.expose() == "sk-ant-secret-12345"
    # And critically — no plaintext in repr/str.
    assert "sk-ant-secret-12345" not in repr(key)
    assert "sk-ant-secret-12345" not in str(key)


@pytest.mark.asyncio
async def test_resolve_decrypted_key_returns_none_when_row_missing():
    user_id = uuid.uuid4()
    db = _mock_db_with_row(None)

    key = await resolve_decrypted_key(user_id, "openai", db)
    assert key is None


@pytest.mark.asyncio
async def test_resolve_decrypted_key_returns_none_for_empty_stored_key():
    user_id = uuid.uuid4()
    row = MagicMock()
    row.encrypted_api_key = ""
    db = _mock_db_with_row(row)

    key = await resolve_decrypted_key(user_id, "openai", db)
    assert key is None


@pytest.mark.asyncio
async def test_resolve_decrypted_key_returns_none_on_decrypt_failure():
    """Corrupted ciphertext must NOT propagate — return None and log."""
    user_id = uuid.uuid4()
    row = MagicMock()
    row.encrypted_api_key = "this-is-not-valid-fernet-ciphertext"
    db = _mock_db_with_row(row)

    key = await resolve_decrypted_key(user_id, "openai", db)
    assert key is None


@pytest.mark.asyncio
async def test_resolve_user_providers_enriches_with_decrypted_keys():
    user_id = uuid.uuid4()
    encrypted = encrypt_value("gsk_real_groq_key")

    async def fake_resolve(uid, name, db):
        if name == "groq":
            return DecryptedKey("gsk_real_groq_key")
        return None

    db = AsyncMock()
    with patch(
        "app.services.user_provider_configs.resolve_decrypted_key",
        side_effect=fake_resolve,
    ):
        enriched = await resolve_user_providers(
            user_id,
            [
                {"name": "groq", "model": "llama-3.3-70b-versatile"},
                {"name": "openai", "model": "gpt-4o-mini"},  # no key configured
            ],
            db,
        )

    # Only groq survives — openai has no server-side key.
    assert len(enriched) == 1
    assert enriched[0]["name"] == "groq"
    assert enriched[0]["model"] == "llama-3.3-70b-versatile"
    assert isinstance(enriched[0]["api_key"], DecryptedKey)
    assert enriched[0]["api_key"].expose() == "gsk_real_groq_key"
    # Belt-and-braces: encrypted ciphertext also never appears in repr.
    assert encrypted not in repr(enriched[0]["api_key"])


@pytest.mark.asyncio
async def test_resolve_user_providers_passes_ollama_without_key():
    """Ollama is local — needs no API key, so passes through with api_key=None."""
    user_id = uuid.uuid4()
    db = AsyncMock()

    enriched = await resolve_user_providers(
        user_id,
        [{"name": "ollama", "model": "llama3.1:8b"}],
        db,
    )

    assert len(enriched) == 1
    assert enriched[0]["name"] == "ollama"
    assert enriched[0]["api_key"] is None


@pytest.mark.asyncio
async def test_resolve_user_providers_drops_unknown_keyless_providers():
    user_id = uuid.uuid4()
    db = AsyncMock()
    with patch(
        "app.services.user_provider_configs.resolve_decrypted_key",
        return_value=None,
    ):
        enriched = await resolve_user_providers(
            user_id,
            [{"name": "openai", "model": "gpt-4o"}],
            db,
        )
    assert enriched == []


@pytest.mark.asyncio
async def test_resolve_user_providers_ignores_blank_name_entries():
    user_id = uuid.uuid4()
    db = AsyncMock()
    enriched = await resolve_user_providers(
        user_id,
        [{"name": "", "model": "x"}, {"model": "y"}],
        db,
    )
    assert enriched == []
