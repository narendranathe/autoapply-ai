"""
Regression tests for Issue #89 — ``POST /api/v1/auth/register`` must derive
``clerk_id`` from validated Clerk credentials, never from the request body.

Before the fix, anyone could call::

    POST /auth/register?clerk_id=user_target&email_hash=...

and create or overwrite a row under ``user_target`` — a direct account-takeover
vector. After the fix:

* No credentials → 401.
* The endpoint accepts only ``email_hash`` (+ optional ``github_username``)
  in the JSON body. Any ``clerk_id`` field in the body is silently ignored
  by Pydantic's default (``extra='ignore'``).
* The persisted ``clerk_id`` always matches the header / JWT value, even when
  the body tries to inject a different one.

These tests deliberately mock the database layer (no real Postgres needed) so
the regression coverage stays cheap and runs in unit-test mode.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.dependencies import get_clerk_user_id, get_db
from app.main import create_app


# ---------------------------------------------------------------------------
# Endpoint-level tests with mocked DB
# ---------------------------------------------------------------------------


def _build_client_with_fake_db(captured: dict | None = None) -> TestClient:
    """Build a TestClient whose ``get_db`` yields a MagicMock session.

    If ``captured`` is provided, the User instance passed to ``db.add`` is
    stored under the ``user`` key so individual tests can assert on the
    persisted clerk_id.
    """
    app = create_app()

    mock_result = MagicMock()
    # First lookup ("does this user already exist?") returns None.
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    def _capture_add(obj):
        if captured is not None:
            captured["user"] = obj

    mock_db.add = MagicMock(side_effect=_capture_add)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    async def _override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_register_without_auth_header_returns_401(monkeypatch):
    """No ``X-Clerk-User-Id`` header and no Bearer JWT → 401.

    With ``DEV_TEST_USER_ID`` empty and ``CLERK_FRONTEND_API_URL`` unset,
    ``get_clerk_user_id`` has no credentials to fall back on and must reject
    the caller.
    """
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    client = _build_client_with_fake_db()
    resp = client.post("/api/v1/auth/register", json={"email_hash": "a" * 64})
    assert resp.status_code == 401, resp.text


def test_register_with_clerk_id_in_body_is_ignored(monkeypatch):
    """A ``clerk_id`` field in the JSON body must NEVER be honoured.

    The persisted user's ``clerk_id`` must equal the value supplied in the
    ``X-Clerk-User-Id`` header, even if an attacker passes a different one
    in the body.
    """
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    authenticated_id = f"user_authed_{uuid.uuid4().hex[:8]}"
    attacker_target = f"user_victim_{uuid.uuid4().hex[:8]}"

    captured: dict = {}
    client = _build_client_with_fake_db(captured)

    resp = client.post(
        "/api/v1/auth/register",
        # Body tries to spoof clerk_id and overwrite an arbitrary identity.
        json={"clerk_id": attacker_target, "email_hash": "b" * 64},
        headers={"X-Clerk-User-Id": authenticated_id},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] is True

    persisted = captured["user"]
    assert persisted.clerk_id == authenticated_id
    assert persisted.clerk_id != attacker_target


def test_register_with_valid_header_creates_user(monkeypatch):
    """Happy path: ``X-Clerk-User-Id`` header → user row added with that clerk_id."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    new_clerk_id = f"user_new_{uuid.uuid4().hex[:8]}"
    captured: dict = {}
    client = _build_client_with_fake_db(captured)

    resp = client.post(
        "/api/v1/auth/register",
        json={"email_hash": "c" * 64, "github_username": "octocat"},
        headers={"X-Clerk-User-Id": new_clerk_id},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["created"] is True

    persisted = captured["user"]
    assert persisted.clerk_id == new_clerk_id
    assert persisted.email_hash == "c" * 64
    assert persisted.github_username == "octocat"


def test_register_rejects_empty_email_hash(monkeypatch):
    """Body must still be validated — empty email_hash → 422."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    client = _build_client_with_fake_db()
    resp = client.post(
        "/api/v1/auth/register",
        json={"email_hash": ""},
        headers={"X-Clerk-User-Id": f"user_{uuid.uuid4().hex[:8]}"},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Dependency-level tests for ``get_clerk_user_id``
# ---------------------------------------------------------------------------


def _request_without_auth() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/register",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.mark.asyncio
async def test_get_clerk_user_id_returns_header_value(monkeypatch):
    """When ``X-Clerk-User-Id`` is supplied, that value is returned verbatim."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    result = await get_clerk_user_id(
        request=_request_without_auth(),
        x_clerk_user_id="user_from_header",
    )
    assert result == "user_from_header"


@pytest.mark.asyncio
async def test_get_clerk_user_id_no_creds_raises_401(monkeypatch):
    """No JWT, no header, no dev fallback → 401."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    with pytest.raises(HTTPException) as exc_info:
        await get_clerk_user_id(
            request=_request_without_auth(),
            x_clerk_user_id=None,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_clerk_user_id_dev_fallback(monkeypatch):
    """In development with DEV_TEST_USER_ID set, the dev id is returned."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "user_dev_xyz")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    result = await get_clerk_user_id(
        request=_request_without_auth(),
        x_clerk_user_id=None,
    )
    assert result == "user_dev_xyz"


@pytest.mark.asyncio
async def test_get_clerk_user_id_dev_empty_raises_401(monkeypatch):
    """Development with empty DEV_TEST_USER_ID and no header → 401."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    with pytest.raises(HTTPException) as exc_info:
        await get_clerk_user_id(
            request=_request_without_auth(),
            x_clerk_user_id=None,
        )
    assert exc_info.value.status_code == 401
    assert "DEV_TEST_USER_ID" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Schema-level test
# ---------------------------------------------------------------------------


def test_register_request_schema_has_no_clerk_id_field():
    """The Pydantic body model must not expose a ``clerk_id`` field.

    Even though Pydantic ignores unknown fields by default (so an attacker
    cannot smuggle one through), the schema itself must not advertise
    ``clerk_id`` as part of the public contract.
    """
    from app.routers.auth import RegisterRequest

    assert "clerk_id" not in RegisterRequest.model_fields
    assert "email_hash" in RegisterRequest.model_fields
