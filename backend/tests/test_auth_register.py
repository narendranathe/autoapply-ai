"""
Tests for POST /api/v1/auth/register — Issue #89.

SECURITY CONTEXT
----------------
The original endpoint accepted ``clerk_id`` as a body parameter with NO
authentication: any unauthenticated caller could create or overwrite any
user record by posting an arbitrary ``clerk_id``. That is a direct account
takeover vector.

The fix:
  * ``clerk_id`` is taken from the validated JWT or ``X-Clerk-User-Id``
    header via the ``get_authenticated_clerk_id`` dependency.
  * ``clerk_id`` is removed from the request body schema entirely.
  * Unauthenticated requests are rejected with 401.
  * The ``RegisterRequest`` schema sets ``extra='forbid'`` so a stray
    ``clerk_id`` key in the body is rejected (422) rather than silently
    ignored.

This module mixes:

* HTTP-level integration checks via the ``client`` fixture for the
  unauthenticated rejection and body-validation paths (no DB writes, so
  they cooperate with the transactional ``db_session`` fixture used by
  the rest of the test suite).
* Unit-level checks on the route handler and dependency to lock in the
  happy path / idempotent upsert without fighting the test-DB
  transaction wrapper.
* A pure schema test that pins ``clerk_id`` out of ``RegisterRequest``
  for all time.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User
from app.routers.auth import register_user
from app.schemas.user import RegisterRequest

# ---------------------------------------------------------------------------
# HTTP: 401 — unauthenticated requests must be rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_without_clerk_header_returns_401(
    client: AsyncClient, db_session, monkeypatch
):
    """POST /auth/register with no X-Clerk-User-Id and no JWT must return 401.

    Critical regression test for the account-takeover vector described in #89.
    No User row may be created when the caller is unauthenticated.
    """
    # Ensure the JWT path is disabled so the test isolates the header path.
    from app.dependencies import settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    response = await client.post(
        "/api/v1/auth/register",
        json={"email_hash": "a" * 64, "github_username": "attacker"},
    )

    assert response.status_code == 401, response.text

    # And no user row was created as a side effect of the rejected request.
    result = await db_session.execute(select(User))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_register_with_empty_clerk_header_returns_401(
    client: AsyncClient, monkeypatch
):
    """An empty X-Clerk-User-Id header must be treated the same as a missing
    one — 401 (FastAPI treats an empty header value as ``None``)."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    response = await client.post(
        "/api/v1/auth/register",
        json={"email_hash": "a" * 64},
        headers={"X-Clerk-User-Id": ""},
    )

    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# HTTP: body validation — clerk_id and other unknown fields are rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_rejects_clerk_id_in_body(
    client: AsyncClient, db_session, monkeypatch
):
    """A body containing ``clerk_id`` must be rejected — ``RegisterRequest``
    has ``extra='forbid'``, so FastAPI returns 422.

    This guards against an attacker trying to override the authenticated
    identity by re-introducing the legacy body field, AND against a future
    refactor that re-adds ``clerk_id`` as a declared field.
    """
    from app.dependencies import settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    auth_clerk = "clerk_authenticated_caller"
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "clerk_id": "clerk_victim_account",  # attempt to hijack
            "email_hash": "b" * 64,
            "github_username": "attacker",
        },
        headers={"X-Clerk-User-Id": auth_clerk},
    )

    # 422 because the schema forbids extra fields.
    assert response.status_code == 422, response.text

    # Crucially, no row was created for the victim.
    result = await db_session.execute(
        select(User).where(User.clerk_id == "clerk_victim_account")
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_register_rejects_unknown_body_fields(
    client: AsyncClient, monkeypatch
):
    """Any unknown body field (other than ``clerk_id``) must also be rejected
    by ``extra='forbid'`` — broader regression hedge against schema drift."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email_hash": "e" * 64,
            "is_admin": True,  # not in schema
        },
        headers={"X-Clerk-User-Id": "clerk_unknown_field"},
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Schema-level lock: clerk_id can never be a body field
# ---------------------------------------------------------------------------


def test_register_request_schema_forbids_clerk_id():
    """``RegisterRequest`` must not accept ``clerk_id`` — extra='forbid'.

    Pure unit check: no DB, no HTTP. This locks the schema contract so a
    future refactor cannot accidentally re-introduce the field.
    """
    from pydantic import ValidationError

    # Sanity: minimal valid payload constructs.
    valid = RegisterRequest(email_hash="0" * 64)
    assert valid.email_hash == "0" * 64
    assert valid.github_username == ""

    # ``clerk_id`` must be rejected.
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(email_hash="0" * 64, clerk_id="clerk_should_be_forbidden")
    assert "clerk_id" in str(exc_info.value)

    # And ``clerk_id`` is not even a declared field on the model.
    assert "clerk_id" not in RegisterRequest.model_fields


def test_register_request_email_hash_must_be_sha256_hex():
    """``email_hash`` must be exactly 64 hex chars — the DB column is
    ``String(64)`` and the field is a SHA-256 hex digest.

    Regression guard: previously the schema allowed up to 128 chars, so a
    65-128 char value would pass Pydantic and then 500 on the DB write.
    """
    from pydantic import ValidationError

    # 64 hex chars → accepted.
    RegisterRequest(email_hash="a" * 64)
    RegisterRequest(email_hash="0123456789abcdef" * 4)

    # Too short → rejected.
    with pytest.raises(ValidationError):
        RegisterRequest(email_hash="a" * 63)

    # Too long (the old upper bound, exceeds the DB column) → rejected.
    with pytest.raises(ValidationError):
        RegisterRequest(email_hash="a" * 65)
    with pytest.raises(ValidationError):
        RegisterRequest(email_hash="a" * 128)

    # Non-hex chars → rejected (``g`` is not a hex digit).
    with pytest.raises(ValidationError):
        RegisterRequest(email_hash="g" * 64)


# ---------------------------------------------------------------------------
# Unit: get_authenticated_clerk_id rejects unauthenticated callers
# ---------------------------------------------------------------------------


def _request_without_auth():
    from fastapi import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/register",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_get_authenticated_clerk_id_raises_401_when_no_credentials(monkeypatch):
    """The dependency that backs ``POST /auth/register`` must raise 401 when
    no JWT and no header are presented — even outside ``get_current_user``."""
    from fastapi import HTTPException

    from app.dependencies import get_authenticated_clerk_id, settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    with pytest.raises(HTTPException) as exc_info:
        await get_authenticated_clerk_id(
            request=_request_without_auth(),
            x_clerk_user_id=None,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_authenticated_clerk_id_returns_header_value(monkeypatch):
    """With the header set and no JWT configured, the dependency returns the header."""
    from app.dependencies import get_authenticated_clerk_id, settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    clerk = await get_authenticated_clerk_id(
        request=_request_without_auth(),
        x_clerk_user_id="clerk_from_header_xyz",
    )
    assert clerk == "clerk_from_header_xyz"


# ---------------------------------------------------------------------------
# Unit: register_user happy path (mocked DB, no transaction fixture friction)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_register_user_creates_new_user_when_clerk_id_unknown():
    """Direct call to the route handler with an authenticated clerk_id and
    an unknown user creates a new ``User`` row keyed on that clerk_id."""
    captured_user: dict = {}

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(None))

    def _add(obj):
        captured_user["obj"] = obj

    db.add = MagicMock(side_effect=_add)
    db.commit = AsyncMock()

    async def _refresh(obj):
        # Simulate the post-flush refresh assigning the same id.
        return None

    db.refresh = AsyncMock(side_effect=_refresh)

    body = RegisterRequest(email_hash="d" * 64, github_username="octocat")
    result = await register_user(
        body=body,
        clerk_id="clerk_new_caller",
        db=db,
    )

    # Response shape
    assert result["created"] is True
    assert isinstance(result["user_id"], str)
    uuid.UUID(result["user_id"])  # well-formed UUID

    # The added object uses the AUTHENTICATED clerk_id, not anything from the body.
    new_user = captured_user["obj"]
    assert isinstance(new_user, User)
    assert new_user.clerk_id == "clerk_new_caller"
    assert new_user.email_hash == "d" * 64
    assert new_user.github_username == "octocat"
    assert new_user.is_active is True

    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_user_is_idempotent_for_existing_clerk_id():
    """If a user already exists for the authenticated clerk_id, the route is
    idempotent: ``created=False`` and the existing row's mutable fields are
    updated."""
    existing = User(
        id=uuid.uuid4(),
        clerk_id="clerk_existing",
        email_hash="c" * 64,
        github_username="old_handle",
        resume_repo_name="resume-vault",
        is_active=True,
        total_resumes_generated=0,
        total_applications_tracked=0,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(existing))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    body = RegisterRequest(email_hash="c" * 64, github_username="new_handle")
    result = await register_user(
        body=body,
        clerk_id="clerk_existing",
        db=db,
    )

    assert result["created"] is False
    assert result["user_id"] == str(existing.id)
    # github_username is the one mutable field updated on idempotent calls.
    assert existing.github_username == "new_handle"
    # No NEW row was added.
    db.add.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_register_user_ignores_clerk_id_attempted_via_body_overload():
    """Even if someone monkey-patches ``RegisterRequest`` to smuggle a
    ``clerk_id`` attribute, the route MUST use the authenticated dependency
    value — never read ``clerk_id`` off the body.

    We assert this by attaching a stray ``clerk_id`` attribute to a valid
    body and confirming the new user is created under the dependency-supplied
    ``clerk_id`` (not the smuggled one).
    """
    captured_user: dict = {}

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(None))
    db.add = MagicMock(side_effect=lambda obj: captured_user.update({"obj": obj}))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    body = RegisterRequest(email_hash="f" * 64)
    # Pydantic v2 ``extra='forbid'`` rejects this at construction. Verify that:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RegisterRequest(email_hash="f" * 64, clerk_id="clerk_smuggled")

    # And even if a downstream caller attaches the attribute post-hoc, the
    # route code never reads it — it only references ``body.email_hash`` and
    # ``body.github_username``. We exercise the route to confirm.
    object.__setattr__(body, "clerk_id", "clerk_smuggled")  # bypass pydantic

    await register_user(
        body=body,
        clerk_id="clerk_authenticated",
        db=db,
    )

    new_user = captured_user["obj"]
    assert new_user.clerk_id == "clerk_authenticated"
    assert new_user.clerk_id != "clerk_smuggled"
