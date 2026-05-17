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
async def test_register_with_empty_clerk_header_returns_401(client: AsyncClient, monkeypatch):
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
async def test_register_rejects_clerk_id_in_body(client: AsyncClient, db_session, monkeypatch):
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
    result = await db_session.execute(select(User).where(User.clerk_id == "clerk_victim_account"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_register_rejects_unknown_body_fields(client: AsyncClient, monkeypatch):
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


@pytest.mark.asyncio
async def test_get_authenticated_clerk_id_rejects_whitespace_only_header(monkeypatch):
    """A whitespace-only ``X-Clerk-User-Id`` header is truthy in Python but
    is not a valid identity. The dependency must reject it with 401 — not
    pass ``"   "`` through to the DB lookup.
    """
    from fastapi import HTTPException

    from app.dependencies import get_authenticated_clerk_id, settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    for blank in ("   ", "\t", "\n", " \t \n "):
        with pytest.raises(HTTPException) as exc_info:
            await get_authenticated_clerk_id(
                request=_request_without_auth(),
                x_clerk_user_id=blank,
            )
        assert exc_info.value.status_code == 401, f"expected 401 for {blank!r}"


@pytest.mark.asyncio
async def test_get_authenticated_clerk_id_strips_surrounding_whitespace(monkeypatch):
    """A header padded with whitespace (e.g. from a stray newline in a curl
    header file) should resolve to the trimmed clerk_id, not the padded
    value — otherwise the DB lookup would fail to match the stored id.
    """
    from app.dependencies import get_authenticated_clerk_id, settings

    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    clerk = await get_authenticated_clerk_id(
        request=_request_without_auth(),
        x_clerk_user_id="  clerk_padded  ",
    )
    assert clerk == "clerk_padded"


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


# ---------------------------------------------------------------------------
# Unit: register_user is race-safe against concurrent first-register calls
# ---------------------------------------------------------------------------


def _unique_violation_orig():
    """Build an ``orig`` exception that mimics psycopg's ``UniqueViolation``
    well enough for the route's narrowed handler (``pgcode == "23505"``).

    Using ``types.SimpleNamespace`` keeps the test fixture independent of
    whichever DBAPI driver the project ships with — we only need the
    attribute the route reads."""
    import types

    return types.SimpleNamespace(pgcode="23505")


def _not_null_violation_orig():
    """Mimic psycopg's ``NotNullViolation`` (SQLSTATE 23502). The route
    must classify this as a real bug and 500, not as a race recovery."""
    import types

    return types.SimpleNamespace(pgcode="23502")


@pytest.mark.asyncio
async def test_register_user_handles_concurrent_insert_race():
    """When two concurrent first-register calls for the same ``clerk_id``
    both see NULL on the initial SELECT, the loser's INSERT raises
    ``IntegrityError`` on the unique constraint (pgcode 23505). The route
    must catch it, re-SELECT, and return an idempotent ``created=False``
    response — not bubble a 500.
    """
    from sqlalchemy.exc import IntegrityError

    winner = User(
        id=uuid.uuid4(),
        clerk_id="clerk_race",
        email_hash="a" * 64,
        github_username=None,
        resume_repo_name="resume-vault",
        is_active=True,
        total_resumes_generated=0,
        total_applications_tracked=0,
    )

    # First SELECT (pre-insert) → NULL (we don't see the winner yet).
    # commit() raises IntegrityError (winner already committed).
    # Second SELECT (post-rollback) → winner row.
    execute_calls = {"n": 0}

    async def _execute(_stmt):
        execute_calls["n"] += 1
        if execute_calls["n"] == 1:
            return _FakeResult(None)
        return _FakeResult(winner)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.add = MagicMock()
    db.commit = AsyncMock(
        side_effect=IntegrityError("INSERT", params=None, orig=_unique_violation_orig())
    )
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    body = RegisterRequest(email_hash="a" * 64)
    result = await register_user(
        body=body,
        clerk_id="clerk_race",
        db=db,
    )

    # Idempotent response: the loser saw the winner's row.
    assert result["created"] is False
    assert result["user_id"] == str(winner.id)
    # We rolled back the failed insert before re-SELECTing.
    db.rollback.assert_awaited_once()
    # Two SELECTs total: one before insert, one after rollback.
    assert execute_calls["n"] == 2


@pytest.mark.asyncio
async def test_register_user_500s_if_integrity_error_without_recoverable_row():
    """Defensive: if commit raises IntegrityError with pgcode 23505 but the
    post-rollback SELECT still returns NULL (should be unreachable), the
    route returns 500 rather than silently fabricating a fake idempotent
    response."""
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(None))  # always NULL
    db.add = MagicMock()
    db.commit = AsyncMock(
        side_effect=IntegrityError("INSERT", params=None, orig=_unique_violation_orig())
    )
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    body = RegisterRequest(email_hash="a" * 64)
    with pytest.raises(HTTPException) as exc_info:
        await register_user(
            body=body,
            clerk_id="clerk_phantom",
            db=db,
        )
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_register_user_500s_on_non_unique_integrity_error():
    """A non-unique IntegrityError (e.g. NOT NULL, FK, CHECK violation)
    must NOT be silently absorbed by the race-recovery branch — those
    indicate real schema bugs and must surface as a 500 with the original
    exception chained.

    This pins the narrowing of the ``except IntegrityError`` block from
    Round 3: an earlier overly-broad catch would re-SELECT and mask the
    bug as a successful idempotent response (if any row happened to
    exist) or as a misleading "conflict could not be resolved" 500 with
    the wrong detail string.
    """
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(None))
    db.add = MagicMock()
    db.commit = AsyncMock(
        side_effect=IntegrityError("INSERT", params=None, orig=_not_null_violation_orig())
    )
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    body = RegisterRequest(email_hash="a" * 64)
    with pytest.raises(HTTPException) as exc_info:
        await register_user(
            body=body,
            clerk_id="clerk_schema_bug",
            db=db,
        )

    assert exc_info.value.status_code == 500
    # The detail string distinguishes a schema bug from the
    # "conflict could not be resolved" race-path detail, so operators
    # can grep production logs / responses to triage.
    assert exc_info.value.detail == "Registration failed due to database constraint."
    # We still rolled back so the session is clean for the next request.
    db.rollback.assert_awaited_once()
    # Crucially, the route must NOT have re-SELECTed for the winning row —
    # that branch is reserved for 23505. Only the initial pre-insert SELECT
    # happened.
    assert db.execute.await_count == 1


# ---------------------------------------------------------------------------
# Unit: production header-bypass is closed even on /auth/register
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_rejects_header_only_auth_in_production(monkeypatch):
    """Round 3 / Critic 2 regression: when ``CLERK_FRONTEND_API_URL`` is set
    (production posture), a request that presents ONLY the ``X-Clerk-User-Id``
    header (no ``Authorization: Bearer`` JWT) MUST be rejected with 401.

    The header is a trusted claim with no cryptographic binding — honouring
    it in production would re-open exactly the auth-bypass vector Issue #90
    closes. ``get_authenticated_clerk_id`` backs ``POST /auth/register``, so
    this also closes the original #89 takeover vector on the production
    posture.
    """
    from fastapi import HTTPException

    from app.dependencies import get_authenticated_clerk_id, settings

    # Production posture: URL is set, so ``settings.clerk_jwt_enforced`` is True.
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "https://clerk.example.com")
    assert settings.clerk_jwt_enforced is True

    with pytest.raises(HTTPException) as exc_info:
        await get_authenticated_clerk_id(
            request=_request_without_auth(),
            x_clerk_user_id="user_attacker_supplied",
        )
    assert exc_info.value.status_code == 401
    # The attacker-supplied identity must never appear in the error detail.
    assert "user_attacker_supplied" not in exc_info.value.detail
