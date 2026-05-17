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


# ---------------------------------------------------------------------------
# Issue #197 P1-C — SQL predicate must include BOTH user_id and
# provider_name. A mutation that drops the user_id binding would let
# Alice's request resolve Bob's stored key — the row-level cross-user
# isolation only exists in the WHERE clause.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_decrypted_key_query_binds_user_id_and_provider_name():
    """The compiled statement passed to ``db.execute`` must reference
    both ``user_id`` and ``provider_name`` in its WHERE clause AND bind
    the actual values we passed in. If a refactor drops the user_id
    predicate this test fails — without it, mocked-row tests would
    happily accept Alice's request returning Bob's row.
    """
    from sqlalchemy.sql import Select

    user_id = uuid.uuid4()
    row = MagicMock()
    row.encrypted_api_key = encrypt_value("sk-secret")
    db = _mock_db_with_row(row)

    await resolve_decrypted_key(user_id, "anthropic", db)

    # ``execute`` was called exactly once with the SELECT statement.
    assert db.execute.await_count == 1
    stmt = db.execute.await_args[0][0]
    assert isinstance(stmt, Select), f"expected Select, got {type(stmt).__name__}"

    # Compile with the SQLite dialect (no real DB needed) so we can
    # inspect the rendered WHERE clause and the bound parameter values.
    from sqlalchemy.dialects import sqlite

    compiled = stmt.compile(
        dialect=sqlite.dialect(),
        compile_kwargs={"literal_binds": False},
    )
    rendered_sql = str(compiled).lower()
    params = compiled.params  # dict of bound param name → value

    # WHERE clause references both columns.
    assert "user_id" in rendered_sql, f"user_id missing from WHERE: {rendered_sql}"
    assert "provider_name" in rendered_sql, (
        f"provider_name missing from WHERE: {rendered_sql}"
    )

    # And the bound values are exactly what the caller passed — i.e. a
    # mutation that hard-codes a literal user_id would fail here.
    bound_values = list(params.values())
    assert user_id in bound_values, (
        f"caller-supplied user_id not bound in statement params: {params}"
    )
    assert "anthropic" in bound_values, (
        f"caller-supplied provider_name not bound in statement params: {params}"
    )


@pytest.mark.asyncio
async def test_resolve_decrypted_key_isolates_users_in_real_sqlite_db():
    """Belt-and-braces over the introspection test above: spin up a real
    in-memory sqlite engine with the actual ``user_provider_configs``
    table, insert rows for two distinct users with different encrypted
    keys, and confirm ``resolve_decrypted_key(alice_id, ...)`` returns
    Alice's plaintext (never Bob's). If a mutation drops the user_id
    predicate this test fails because the query returns >1 row and
    ``scalar_one_or_none`` raises.

    Skipped when ``aiosqlite`` is unavailable — the static-statement
    introspection test above is the primary guard; this is the
    end-to-end belt.
    """
    pytest.importorskip("aiosqlite")
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    # Importing the model also registers it on the shared declarative
    # ``Base`` we stubbed at the top of this file, so its metadata is
    # available to create the table.
    from app.models.user_provider_config import UserProviderConfig

    # The pgvector ``Vector`` column type used elsewhere in the schema is
    # not portable to sqlite — but ``UserProviderConfig`` itself has no
    # vector columns so we create only its single table.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: UserProviderConfig.__table__.create(sync_conn)
            )

        SessionLocal = sessionmaker(  # type: ignore[call-overload]
            engine, class_=AsyncSession, expire_on_commit=False
        )

        alice_id = uuid.uuid4()
        bob_id = uuid.uuid4()

        async with SessionLocal() as session:
            session.add_all(
                [
                    UserProviderConfig(
                        user_id=alice_id,
                        provider_name="anthropic",
                        encrypted_api_key=encrypt_value("sk-alice"),
                    ),
                    UserProviderConfig(
                        user_id=bob_id,
                        provider_name="anthropic",
                        encrypted_api_key=encrypt_value("sk-bob"),
                    ),
                ]
            )
            await session.commit()

        async with SessionLocal() as session:
            alice_key = await resolve_decrypted_key(alice_id, "anthropic", session)
            bob_key = await resolve_decrypted_key(bob_id, "anthropic", session)

        assert alice_key is not None
        assert bob_key is not None
        assert alice_key.expose() == "sk-alice"
        assert bob_key.expose() == "sk-bob"
        # Critically — the two never collapse to the same value. If a
        # mutation drops the user_id predicate, ``scalar_one_or_none``
        # raises ``MultipleResultsFound`` long before this assertion.
        assert alice_key.expose() != bob_key.expose()
    finally:
        await engine.dispose()
