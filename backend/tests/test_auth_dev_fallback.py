"""
Tests for the dev auth bypass in ``get_current_user`` — Issue #103.

Covers the acceptance scenarios:
1. Config validator rejects DEV_TEST_USER_ID when ENVIRONMENT=production.
2. Config validator accepts DEV_TEST_USER_ID when ENVIRONMENT=development.
3. Dev fallback with a valid DEV_TEST_USER_ID resolves to that user.
4. Dev fallback with an empty DEV_TEST_USER_ID returns 401 (unauthenticated).
5. Dev fallback with an unknown DEV_TEST_USER_ID returns 401.
6. JWT path takes precedence over the dev fallback when both are configured.
7. An inactive user matching DEV_TEST_USER_ID is rejected (401).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    """ENVIRONMENT=production with empty DEV_TEST_USER_ID must validate cleanly.

    Issue #90 added an unrelated production guard that requires
    CLERK_FRONTEND_API_URL — supply a dummy value so this test isolates the
    DEV_TEST_USER_ID code path.
    """
    s = Settings(
        ENVIRONMENT="production",
        DEV_TEST_USER_ID="",
        CLERK_FRONTEND_API_URL="https://clerk.example.com",
    )
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
async def test_dev_fallback_with_empty_dev_test_user_id_raises_401(monkeypatch):
    """In dev mode with empty DEV_TEST_USER_ID, the dependency must raise 401.

    Rationale: no credentials presented → semantically unauthenticated (401),
    not forbidden (403). The detail still names DEV_TEST_USER_ID so the
    developer knows what to set.
    """
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=_request_without_auth(), db=mock_db, x_clerk_user_id=None)

    assert exc_info.value.status_code == 401
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


# ---------------------------------------------------------------------------
# JWT precedence + inactive-user coverage
# ---------------------------------------------------------------------------


def _request_with_bearer_token(token: str) -> Request:
    """Build a minimal ASGI Request with an Authorization: Bearer <token> header."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "query_string": b"",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_jwt_path_takes_precedence_over_dev_fallback(monkeypatch):
    """When CLERK_FRONTEND_API_URL is configured AND a valid JWT is presented,
    the JWT path must win — DEV_TEST_USER_ID must NOT be consulted, even if set.

    Verified by:
      - configuring both CLERK_FRONTEND_API_URL and DEV_TEST_USER_ID,
      - mocking the JWT decoder to return a different clerk_id than DEV_TEST_USER_ID,
      - asserting the returned user matches the JWT subject (not DEV_TEST_USER_ID).
    """
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "https://clerk.example.com")
    monkeypatch.setattr(settings, "CLERK_JWT_AUDIENCE", "")
    # Dev fallback is also configured but must be ignored when JWT is valid.
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "user_dev_fallback_should_not_be_used")

    jwt_user = MagicMock(id=uuid.uuid4(), clerk_id="user_from_jwt", is_active=True)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = jwt_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch(
            "app.dependencies.jwt.get_unverified_header",
            return_value={"kid": "kid-test"},
        ),
        patch(
            "app.dependencies._resolve_jwk_for_kid",
            new=AsyncMock(return_value={"kid": "kid-test"}),
        ),
        patch("app.dependencies.jwt.decode", return_value={"sub": "user_from_jwt"}),
    ):
        user = await get_current_user(
            request=_request_with_bearer_token("fake.jwt.token"),
            db=mock_db,
            x_clerk_user_id=None,
        )

    assert user is jwt_user
    # Exactly one DB query — the JWT lookup. Dev fallback must not run a second query.
    assert mock_db.execute.await_count == 1
    # Confirm the WHERE clause used the JWT subject, not DEV_TEST_USER_ID.
    executed_stmt = mock_db.execute.await_args.args[0]
    compiled = str(executed_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "user_from_jwt" in compiled
    assert "user_dev_fallback_should_not_be_used" not in compiled


@pytest.mark.asyncio
async def test_inactive_user_with_matching_dev_test_user_id_rejected(monkeypatch):
    """An inactive user whose clerk_id matches DEV_TEST_USER_ID must be rejected (401).

    The query filters ``User.is_active.is_(True)``, so an inactive row returns
    ``None`` from the lookup — same code path as 'unknown user' → 401.
    """
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "user_inactive")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    # The is_active filter in the SELECT means the query returns None for inactive users.
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=_request_without_auth(), db=mock_db, x_clerk_user_id=None)

    assert exc_info.value.status_code == 401
    assert "user_inactive" in exc_info.value.detail
    # Confirm the query did filter on is_active=True.
    executed_stmt = mock_db.execute.await_args.args[0]
    compiled = str(executed_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "is_active" in compiled
