"""
Tests for the dev auth bypass in ``get_current_user`` — Issue #103.

Covers the four acceptance scenarios:
1. Config validator rejects DEV_TEST_USER_ID when ENVIRONMENT=production.
2. Config validator accepts DEV_TEST_USER_ID when ENVIRONMENT=development.
3. Dev fallback with a valid DEV_TEST_USER_ID resolves to that user.
4. Dev fallback with an empty DEV_TEST_USER_ID returns 403.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.config import Settings
from app.dependencies import get_current_user

# ---------------------------------------------------------------------------
# Config validator
# ---------------------------------------------------------------------------


def test_settings_rejects_dev_test_user_id_in_production():
    """ENVIRONMENT=production with a non-empty DEV_TEST_USER_ID must fail validation."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(ENVIRONMENT="production", DEV_TEST_USER_ID="user_leaks_into_prod")

    assert "DEV_TEST_USER_ID" in str(exc_info.value)


def test_settings_allows_dev_test_user_id_in_development():
    """ENVIRONMENT=development with a non-empty DEV_TEST_USER_ID must validate cleanly."""
    s = Settings(ENVIRONMENT="development", DEV_TEST_USER_ID="user_dev_only")
    assert s.DEV_TEST_USER_ID == "user_dev_only"
    assert s.is_development is True


def test_settings_allows_empty_dev_test_user_id_in_production():
    """ENVIRONMENT=production with empty DEV_TEST_USER_ID must validate cleanly."""
    s = Settings(ENVIRONMENT="production", DEV_TEST_USER_ID="")
    assert s.DEV_TEST_USER_ID == ""
    assert s.is_production is True


# ---------------------------------------------------------------------------
# Auth dependency — dev fallback
# ---------------------------------------------------------------------------


def _request_without_auth() -> Request:
    """Build a minimal ASGI Request with no Authorization header."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_dev_fallback_with_valid_dev_test_user_id_returns_user(monkeypatch):
    """In dev mode with DEV_TEST_USER_ID set, the user matching that clerk_id is returned."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "user_dev_abc")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    expected_user = MagicMock(id=uuid.uuid4(), clerk_id="user_dev_abc", is_active=True)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = expected_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    user = await get_current_user(request=_request_without_auth(), db=mock_db, x_clerk_user_id=None)

    assert user is expected_user
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_dev_fallback_with_empty_dev_test_user_id_raises_403(monkeypatch):
    """In dev mode with empty DEV_TEST_USER_ID, the dependency must raise 403."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=_request_without_auth(), db=mock_db, x_clerk_user_id=None)

    assert exc_info.value.status_code == 403
    assert "DEV_TEST_USER_ID" in exc_info.value.detail
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_dev_fallback_with_unknown_dev_test_user_id_raises_401(monkeypatch):
    """A DEV_TEST_USER_ID that doesn't match any active user must raise 401 — never silently
    pick a different user."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "user_does_not_exist")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=_request_without_auth(), db=mock_db, x_clerk_user_id=None)

    assert exc_info.value.status_code == 401
    assert "user_does_not_exist" in exc_info.value.detail


@pytest.mark.asyncio
async def test_non_development_without_credentials_raises_401(monkeypatch):
    """Outside of development, the dev fallback must never run — request must be 401."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=_request_without_auth(), db=mock_db, x_clerk_user_id=None)

    assert exc_info.value.status_code == 401
    mock_db.execute.assert_not_awaited()
