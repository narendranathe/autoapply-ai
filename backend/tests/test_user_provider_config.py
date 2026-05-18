"""
Tests for user_provider_config router — Issue #25: server-side provider authority.

Uses AsyncMock to avoid real DB connections (consistent with passing tests pattern).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers.user_provider_config import ProviderConfigIn

# ---------------------------------------------------------------------------
# Test 1: PUT upserts a new provider config row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_provider_config_creates_new_row():
    """PUT must INSERT a new row when none exists and return id/name/model/enabled."""
    from app.routers.user_provider_config import upsert_provider_config

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    # DB returns no existing row — select() returns None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    # db.refresh sets the id on the row so ProviderConfigOut can read it
    created_row_holder: list = []

    async def fake_refresh(row):
        row.id = uuid.uuid4()
        created_row_holder.append(row)

    mock_db.refresh = AsyncMock(side_effect=fake_refresh)

    payload = ProviderConfigIn(
        name="groq", model="llama-3.3-70b-versatile", api_key="gsk_test_12345"
    )

    result = await upsert_provider_config(payload=payload, db=mock_db, user=mock_user)

    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()
    assert result.name == "groq"
    assert result.model == "llama-3.3-70b-versatile"
    assert result.enabled is True


# ---------------------------------------------------------------------------
# Test 2: GET returns configs without api_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_provider_configs_never_returns_api_key():
    """GET must return id/name/model/enabled but NEVER api_key."""
    from app.routers.user_provider_config import list_provider_configs
    from app.utils.encryption import encrypt_value

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    row = MagicMock()
    row.id = uuid.uuid4()
    row.provider_name = "openai"
    row.model_override = "gpt-4o"
    row.encrypted_api_key = encrypt_value("sk-test")

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [row]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    response = await list_provider_configs(db=mock_db, user=mock_user)

    assert "configs" in response
    assert len(response["configs"]) == 1
    cfg = response["configs"][0]
    assert cfg.name == "openai"
    assert not hasattr(cfg, "api_key") or cfg.__dict__.get("api_key") is None


# ---------------------------------------------------------------------------
# Test 3: DELETE removes the row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_provider_config_removes_row():
    """DELETE must call db.delete(row) then db.commit()."""
    from app.routers.user_provider_config import delete_provider_config

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    mock_row = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.delete = AsyncMock()
    mock_db.commit = AsyncMock()

    await delete_provider_config(provider_name="kimi", db=mock_db, user=mock_user)

    mock_db.delete.assert_awaited_once_with(mock_row)
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 4: DELETE 404 when row not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_nonexistent_provider_returns_404():
    """DELETE with a provider that doesn't exist must raise 404."""
    from fastapi import HTTPException

    from app.routers.user_provider_config import delete_provider_config

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await delete_provider_config(provider_name="nonexistent", db=mock_db, user=mock_user)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Test 5: PUT with invalid provider name returns 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_invalid_provider_name_raises_422():
    """PUT with an unknown provider name must raise HTTP 422."""
    from fastapi import HTTPException

    from app.routers.user_provider_config import upsert_provider_config

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_db = AsyncMock()

    payload = ProviderConfigIn(name="totally_fake_provider", model="", api_key="key123")

    with pytest.raises(HTTPException) as exc_info:
        await upsert_provider_config(payload=payload, db=mock_db, user=mock_user)

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Test 6: _resolve_providers falls back to DB when providers_json is empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_providers_uses_db_when_providers_json_empty():
    """_resolve_providers must return DB providers when providers_json is empty."""
    from app.routers.vault._shared import _resolve_providers
    from app.utils.encryption import encrypt_value

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    mock_row = MagicMock()
    mock_row.provider_name = "groq"
    mock_row.encrypted_api_key = encrypt_value("gsk_test_key_for_unit_test")
    mock_row.model_override = "llama-3.3-70b-versatile"

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_row]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    providers = await _resolve_providers("", mock_db, mock_user)

    assert len(providers) == 1
    assert providers[0]["name"] == "groq"
    assert providers[0]["api_key"] == "gsk_test_key_for_unit_test"


# ---------------------------------------------------------------------------
# Test 7 (Issue #104): GET /provider-configs returns enabled derived from api_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_provider_configs_is_enabled_derived_from_api_key():
    """GET /provider-configs must compute ``is_enabled`` as ``bool(api_key)``."""
    from app.routers.users import get_provider_configs

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    row_with_key = MagicMock()
    row_with_key.provider_name = "openai"
    row_with_key.encrypted_api_key = "ENCRYPTED_BLOB"
    row_with_key.model_override = "gpt-4o-mini"

    row_without_key = MagicMock()
    row_without_key.provider_name = "anthropic"
    row_without_key.encrypted_api_key = ""
    row_without_key.model_override = None

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [row_with_key, row_without_key]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    response = await get_provider_configs(db=mock_db, user=mock_user)
    configs = {c.provider_name: c for c in response.configs}

    assert configs["openai"].has_key is True
    assert configs["openai"].is_enabled is True
    assert configs["openai"].is_enabled == configs["openai"].has_key

    assert configs["anthropic"].has_key is False
    assert configs["anthropic"].is_enabled is False
    assert configs["anthropic"].is_enabled == configs["anthropic"].has_key


@pytest.mark.asyncio
async def test_put_provider_configs_response_enabled_derived_from_api_key():
    """PUT /provider-configs/{name} must derive ``is_enabled`` from the stored key."""
    from app.routers.users import upsert_provider_config
    from app.schemas.user import ProviderConfigUpsert

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    with_key_resp = await upsert_provider_config(
        provider_name="openai",
        payload=ProviderConfigUpsert(api_key="sk-real-key", model_override="gpt-4o-mini"),
        db=mock_db,
        user=mock_user,
    )
    assert with_key_resp.has_key is True
    assert with_key_resp.is_enabled is True

    cleared_resp = await upsert_provider_config(
        provider_name="anthropic",
        payload=ProviderConfigUpsert(api_key="", model_override=None),
        db=mock_db,
        user=mock_user,
    )
    assert cleared_resp.has_key is False
    assert cleared_resp.is_enabled is False


# ---------------------------------------------------------------------------
# P0-A: key_fingerprint in PUT and GET responses  (issue #198 round 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_provider_config_returns_sha256_fingerprint() -> None:
    """PUT must echo first-8-hex-chars of sha256(plaintext) so the
    migration client can verify the server stored what it sent."""
    import hashlib

    from app.routers.users import upsert_provider_config
    from app.schemas.user import ProviderConfigUpsert

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    plaintext = "sk-real-key-xyz"
    expected = hashlib.sha256(plaintext.encode()).hexdigest()[:8]

    resp = await upsert_provider_config(
        provider_name="openai",
        payload=ProviderConfigUpsert(api_key=plaintext, model_override="gpt-4o-mini"),
        db=mock_db,
        user=mock_user,
    )
    assert resp.has_key is True
    assert resp.key_fingerprint == expected
    # 8 hex chars only — not the full hash.
    assert len(resp.key_fingerprint) == 8


@pytest.mark.asyncio
async def test_put_provider_config_with_empty_key_returns_null_fingerprint() -> None:
    """PUT with empty api_key returns has_key=False and key_fingerprint=None."""
    from app.routers.users import upsert_provider_config
    from app.schemas.user import ProviderConfigUpsert

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    resp = await upsert_provider_config(
        provider_name="anthropic",
        payload=ProviderConfigUpsert(api_key="", model_override=None),
        db=mock_db,
        user=mock_user,
    )
    assert resp.has_key is False
    assert resp.key_fingerprint is None


@pytest.mark.asyncio
async def test_get_provider_configs_returns_fingerprint_per_row(monkeypatch) -> None:
    """GET /provider-configs returns the fingerprint for each row with a key.

    Rows without a key (encrypted_api_key='') return key_fingerprint=None.
    """
    import hashlib

    from app.routers.users import get_provider_configs

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    row_a = MagicMock()
    row_a.provider_name = "openai"
    row_a.encrypted_api_key = "ENC_BLOB_A"
    row_a.model_override = "gpt-4o"

    row_b = MagicMock()
    row_b.provider_name = "anthropic"
    row_b.encrypted_api_key = ""  # cleared
    row_b.model_override = None

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [row_a, row_b]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    # Patch decrypt to return a predictable plaintext for row_a.
    plaintext = "sk-decrypted-openai-key"
    expected_fp = hashlib.sha256(plaintext.encode()).hexdigest()[:8]

    def fake_decrypt(value: str) -> str:
        if value == "ENC_BLOB_A":
            return plaintext
        raise ValueError("not the right blob")

    monkeypatch.setattr("app.routers.users.decrypt_value", fake_decrypt)

    response = await get_provider_configs(db=mock_db, user=mock_user)
    configs = {c.provider_name: c for c in response.configs}

    assert configs["openai"].has_key is True
    assert configs["openai"].key_fingerprint == expected_fp

    # Cleared row has no fingerprint at all.
    assert configs["anthropic"].has_key is False
    assert configs["anthropic"].key_fingerprint is None


@pytest.mark.asyncio
async def test_get_provider_configs_fingerprint_is_none_when_decrypt_fails(
    monkeypatch,
) -> None:
    """If decrypt raises (e.g. FERNET_KEY mismatch), the row still
    surfaces as has_key=True but key_fingerprint must be None — the
    migration client interprets that as "verification failed, keep the
    local copy", which is the correct safe default."""
    from app.routers.users import get_provider_configs

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    row = MagicMock()
    row.provider_name = "openai"
    row.encrypted_api_key = "CORRUPT_BLOB"
    row.model_override = "gpt-4o"

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [row]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    def raising_decrypt(value: str) -> str:
        raise ValueError("decrypt failed")

    monkeypatch.setattr("app.routers.users.decrypt_value", raising_decrypt)

    response = await get_provider_configs(db=mock_db, user=mock_user)
    configs = {c.provider_name: c for c in response.configs}

    assert configs["openai"].has_key is True
    assert configs["openai"].key_fingerprint is None
