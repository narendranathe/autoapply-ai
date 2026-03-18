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
        name="groq", model="llama-3.3-70b-versatile", api_key="gsk_test_12345", enabled=True
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
    row.is_enabled = True
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

    payload = ProviderConfigIn(
        name="totally_fake_provider", model="", api_key="key123", enabled=True
    )

    with pytest.raises(HTTPException) as exc_info:
        await upsert_provider_config(payload=payload, db=mock_db, user=mock_user)

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Test 6: _resolve_providers falls back to DB when providers_json is empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_providers_uses_db_when_providers_json_empty():
    """_resolve_providers must return DB providers when providers_json is empty."""
    from app.routers.vault_flat import _resolve_providers
    from app.utils.encryption import encrypt_value

    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    mock_row = MagicMock()
    mock_row.provider_name = "groq"
    mock_row.encrypted_api_key = encrypt_value("gsk_test_key_for_unit_test")
    mock_row.model_override = "llama-3.3-70b-versatile"
    mock_row.is_enabled = True

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
