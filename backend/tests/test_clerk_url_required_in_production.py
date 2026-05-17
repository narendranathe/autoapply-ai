"""
Tests for Issue #90 — CLERK_FRONTEND_API_URL must be required in production.

Covers three acceptance paths:
1. Backend refuses to construct ``Settings`` in production without the URL
   (fail-startup).
2. Dev / staging without the URL logs a warning but does NOT crash the
   process (preserves local-only bypass).
3. ``get_current_user`` raises 401 on every request in production when the
   URL is somehow missing (defense-in-depth against monkey-patched settings)
   AND refuses to honour ``X-Clerk-User-Id`` in production even when the
   URL is set (the actual auth-bypass vector — the header is a trusted
   claim with no cryptographic binding).

These tests exercise the security boundary directly, without spinning up the
full ASGI app, so they remain fast and focused.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException, Request
from jose import jwt
from jose.utils import long_to_base64
from pydantic import ValidationError

from app.config import Settings
from app.dependencies import get_current_user

# ---------------------------------------------------------------------------
# 1. Config-level fail-startup (production refuses to boot without the URL)
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Settings:
    """Build a Settings instance with .env loading disabled so tests do not
    accidentally pick up the developer's local ``CLERK_FRONTEND_API_URL``."""
    kwargs: dict[str, Any] = {"_env_file": None, **overrides}
    return Settings(**kwargs)


def test_production_without_clerk_url_fails_validation() -> None:
    """ENVIRONMENT=production with empty CLERK_FRONTEND_API_URL must raise
    ValidationError so the process refuses to start (Issue #90)."""
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(
            ENVIRONMENT="production",
            CLERK_FRONTEND_API_URL="",
            EXTENSION_ID="cccccccccccccccccccccccccccccccc",
        )

    err_text = str(exc_info.value)
    assert "CLERK_FRONTEND_API_URL" in err_text
    # Surface the bypass risk in the error so operators see it in the
    # boot crash log.
    assert "bypass" in err_text.lower()


def test_production_with_clerk_url_validates_cleanly() -> None:
    """ENVIRONMENT=production with a configured URL must validate cleanly."""
    s = _make_settings(
        ENVIRONMENT="production",
        CLERK_FRONTEND_API_URL="https://clerk.example.com",
        EXTENSION_ID="cccccccccccccccccccccccccccccccc",
    )
    assert s.is_production is True
    assert s.CLERK_FRONTEND_API_URL == "https://clerk.example.com"
    assert s.clerk_jwt_enforced is True


# ---------------------------------------------------------------------------
# 2. Dev / staging warn-but-allow (preserves local-only bypass)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_non_production_without_clerk_url_validates_cleanly(env: str) -> None:
    """Dev / staging / test environments without CLERK_FRONTEND_API_URL must
    NOT fail validation — they keep the documented header bypass for local
    workflows. The auth dependency emits an import-time warning instead."""
    s = _make_settings(ENVIRONMENT=env, CLERK_FRONTEND_API_URL="")
    assert s.CLERK_FRONTEND_API_URL == ""
    assert s.is_production is False
    assert s.clerk_jwt_enforced is False


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_warn_if_clerk_url_missing_emits_in_non_production(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """``_warn_if_clerk_url_missing`` returns ``True`` and calls
    ``logger.warning`` with an actionable message when the URL is unset
    in any non-production environment.

    Asserting on the helper's return value (instead of trying to capture
    loguru output through caplog) keeps the test robust against other
    test modules that replace ``loguru.logger`` with a ``SimpleNamespace``.
    """
    from app import dependencies as deps_module

    monkeypatch.setattr(deps_module.settings, "ENVIRONMENT", env)
    monkeypatch.setattr(deps_module.settings, "CLERK_FRONTEND_API_URL", "")

    warning_calls: list[tuple[Any, ...]] = []

    class _CaptureLogger:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            warning_calls.append(args)

    monkeypatch.setattr(deps_module, "logger", _CaptureLogger())

    emitted = deps_module._warn_if_clerk_url_missing()

    assert emitted is True
    assert len(warning_calls) == 1
    message = warning_calls[0][0]
    assert "CLERK_FRONTEND_API_URL is unset" in message
    assert "X-Clerk-User-Id" in message
    assert "JWT verification is" in message


def test_warn_if_clerk_url_missing_is_silent_when_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the URL is configured (any env), the helper must NOT warn —
    we don't want noise on every dev request once Clerk is wired up."""
    from app import dependencies as deps_module

    monkeypatch.setattr(deps_module.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(deps_module.settings, "CLERK_FRONTEND_API_URL", "https://clerk.example.com")

    warning_calls: list[tuple[Any, ...]] = []

    class _CaptureLogger:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            warning_calls.append(args)

    monkeypatch.setattr(deps_module, "logger", _CaptureLogger())

    emitted = deps_module._warn_if_clerk_url_missing()

    assert emitted is False
    assert warning_calls == []


def test_warn_if_clerk_url_missing_is_silent_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production without the URL is handled by the config validator
    (fail-startup), not by the import-time warning. The helper must stay
    silent so the only signal in prod is the validator error."""
    from app import dependencies as deps_module

    monkeypatch.setattr(deps_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(deps_module.settings, "CLERK_FRONTEND_API_URL", "")

    warning_calls: list[tuple[Any, ...]] = []

    class _CaptureLogger:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            warning_calls.append(args)

    monkeypatch.setattr(deps_module, "logger", _CaptureLogger())

    emitted = deps_module._warn_if_clerk_url_missing()

    assert emitted is False
    assert warning_calls == []


# ---------------------------------------------------------------------------
# 3. Runtime 401 in production (defense in depth)
# ---------------------------------------------------------------------------


def _request_without_auth() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/protected",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_production_without_clerk_url_request_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense-in-depth: even if a runtime monkey-patch leaves the URL
    empty while ENVIRONMENT=production (the config validator would normally
    block this at startup), get_current_user must refuse the request with
    401 — never trust the X-Clerk-User-Id header in production.

    Asserting the **exact detail string** (not just the 401 status) pins
    the early-guard path independently from the later
    ``not settings.clerk_jwt_enforced`` check at the header-trust step. If
    the early guard is ever removed, the request would still 401 — but
    with a different detail ("Authentication required.") — and this test
    would fail loudly, surfacing the regression. See Critic 3's mutation
    finding on round 1."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            request=_request_without_auth(),
            db=mock_db,
            x_clerk_user_id="user_attacker_supplied",
        )

    assert exc_info.value.status_code == 401
    # Pin the early-guard detail so deleting the guard breaks this test
    # even though the later check would still produce a 401.
    assert exc_info.value.detail == "Authentication unavailable: server misconfigured."
    # No DB lookup should have run — we want to fail before any user resolution.
    mock_db.execute.assert_not_awaited()
    # The error must NOT leak the impersonated id back to the caller.
    assert "user_attacker_supplied" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_production_ignores_x_clerk_user_id_header_when_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with CLERK_FRONTEND_API_URL configured and no Bearer token, the
    X-Clerk-User-Id header must NEVER produce an authenticated user in
    production. This is the actual auth-bypass vector flagged by #90: the
    header is a trusted claim with no cryptographic binding.

    Expected behaviour: 401 (Authentication required), no DB lookup."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "https://clerk.example.com")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            request=_request_without_auth(),
            db=mock_db,
            x_clerk_user_id="user_attacker_supplied",
        )

    assert exc_info.value.status_code == 401
    # Critical: header value must NOT have caused a user lookup.
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_development_still_honours_x_clerk_user_id_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: tightening prod must not break the dev workflow.
    In development with no URL, X-Clerk-User-Id is still trusted (the
    documented bypass for local development)."""
    from app.dependencies import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "CLERK_FRONTEND_API_URL", "")
    monkeypatch.setattr(settings, "DEV_TEST_USER_ID", "")

    expected_user = MagicMock(clerk_id="user_dev_header", is_active=True)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = expected_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    user = await get_current_user(
        request=_request_without_auth(),
        db=mock_db,
        x_clerk_user_id="user_dev_header",
    )

    assert user is expected_user
    mock_db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. Production JWT happy-path + header-ignored-when-JWT-present
# ---------------------------------------------------------------------------

_MOCK_CLERK_URL = "https://test-tenant.clerk.accounts.dev"
_MOCK_KID = "kid-test"


def _rsa_keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk_from_private(key: rsa.RSAPrivateKey, kid: str) -> dict[str, str]:
    nums = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": long_to_base64(nums.n).decode("ascii"),
        "e": long_to_base64(nums.e).decode("ascii"),
    }


def _sign_clerk_token(
    key: rsa.RSAPrivateKey,
    *,
    sub: str,
    iss: str = _MOCK_CLERK_URL,
    kid: str = _MOCK_KID,
) -> str:
    """Forge a Clerk-shaped RS256 token. ``iss`` defaults to the mock tenant
    URL so the issuer check in ``jwt.decode`` accepts the token."""
    payload = {
        "sub": sub,
        "iss": iss,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


def _request_with_bearer(token: str, *, x_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = [
        (b"authorization", f"Bearer {token}".encode())
    ]
    if x_header is not None:
        headers.append((b"x-clerk-user-id", x_header.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/protected",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_production_accepts_valid_bearer_jwt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end happy path on the JWT verification branch in production.

    Round 1 had no test that actually exercised this path — the existing
    suite only verified rejection cases. Without a positive assertion, a
    refactor that broke ``jwt.decode``'s integration (e.g. wrong kwargs,
    wrong algorithm allowlist) could ship green.

    The test:
      - sets ``CLERK_FRONTEND_API_URL`` to a mock tenant URL,
      - patches ``_resolve_jwk_for_kid`` to return a valid JWK,
      - signs a token whose ``sub`` matches the DB user's ``clerk_id``,
      - sends it as ``Authorization: Bearer ...``,
      - asserts the dependency returns that user (no HTTPException).
    """
    from app import dependencies as deps_module

    monkeypatch.setattr(deps_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(deps_module.settings, "CLERK_FRONTEND_API_URL", _MOCK_CLERK_URL)
    monkeypatch.setattr(deps_module.settings, "CLERK_JWT_AUDIENCE", "")

    key = _rsa_keypair()
    jwk = _jwk_from_private(key, _MOCK_KID)
    token = _sign_clerk_token(key, sub="test_clerk_id")

    expected_user = MagicMock(clerk_id="test_clerk_id", is_active=True)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = expected_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch.object(
        deps_module, "_resolve_jwk_for_kid", AsyncMock(return_value=jwk)
    ) as resolve_mock:
        user = await get_current_user(
            request=_request_with_bearer(token),
            db=mock_db,
            x_clerk_user_id=None,
        )

    assert user is expected_user
    resolve_mock.assert_awaited_once_with(_MOCK_KID)
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_production_jwt_takes_precedence_over_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both ``Authorization: Bearer <jwt>`` and ``X-Clerk-User-Id``
    are present in production, the resolved clerk_id MUST come from the
    JWT's ``sub`` claim — the header is silently ignored.

    A bug where the code preferred the header (or fell back to it on a
    mismatch) would let an attacker who steals a valid JWT for "victim"
    swap it out for their own ``X-Clerk-User-Id`` and impersonate an
    arbitrary user. This test pins that the JWT subject wins.

    Tracks Critic 5's request for "both Bearer JWT and X-Clerk-User-Id
    present in prod — only the JWT's sub is used".
    """
    from app import dependencies as deps_module

    monkeypatch.setattr(deps_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(deps_module.settings, "CLERK_FRONTEND_API_URL", _MOCK_CLERK_URL)
    monkeypatch.setattr(deps_module.settings, "CLERK_JWT_AUDIENCE", "")

    key = _rsa_keypair()
    jwk = _jwk_from_private(key, _MOCK_KID)
    jwt_sub = "user_from_jwt"
    header_sub = "user_attacker_supplied"
    token = _sign_clerk_token(key, sub=jwt_sub)

    captured_clerk_ids: list[str] = []

    def _capture_execute(stmt: Any) -> Any:
        # Pull the clerk_id literal out of the where clause so the test
        # can assert against the *resolved* identity, not just the user
        # object the mock returns.
        try:
            for clause in stmt.whereclause.clauses:
                if "clerk_id" in str(clause):
                    captured_clerk_ids.append(clause.right.value)
        except Exception:
            pass
        result = MagicMock()
        result.scalar_one_or_none.return_value = MagicMock(
            clerk_id=jwt_sub, is_active=True
        )
        return result

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_capture_execute)

    with patch.object(
        deps_module, "_resolve_jwk_for_kid", AsyncMock(return_value=jwk)
    ):
        user = await get_current_user(
            request=_request_with_bearer(token, x_header=header_sub),
            db=mock_db,
            x_clerk_user_id=header_sub,
        )

    # The DB lookup must use the JWT's subject, never the header.
    assert captured_clerk_ids == [jwt_sub], (
        f"Expected DB lookup to use JWT sub {jwt_sub!r}; "
        f"actual lookups: {captured_clerk_ids!r}. If header_sub appears, "
        f"the header bypass is live in production — Issue #90 regression."
    )
    assert header_sub not in captured_clerk_ids
    assert user.clerk_id == jwt_sub


@pytest.mark.asyncio
async def test_production_rejects_jwt_from_foreign_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token signed by a different Clerk tenant (different ``iss`` claim)
    must be rejected with 401, even when the signature is valid and the
    ``kid`` resolves through our JWKS — i.e. the JWK we control is also
    served by the attacker's tenant URL.

    Without ``verify_iss=True`` + ``issuer=settings.CLERK_FRONTEND_API_URL``,
    a tenant-confusion attack would pass: the signature checks out, the
    kid is known, and we'd silently resolve the foreign tenant's ``sub``
    against our local user table. This test pins that the issuer claim
    must match our configured tenant URL.
    """
    from app import dependencies as deps_module

    monkeypatch.setattr(deps_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(deps_module.settings, "CLERK_FRONTEND_API_URL", _MOCK_CLERK_URL)
    monkeypatch.setattr(deps_module.settings, "CLERK_JWT_AUDIENCE", "")

    key = _rsa_keypair()
    jwk = _jwk_from_private(key, _MOCK_KID)
    # Token signed with the SAME key (kid resolves) but claims a different
    # tenant URL as issuer — this is the tenant-confusion vector.
    token = _sign_clerk_token(
        key,
        sub="user_from_foreign_tenant",
        iss="https://attacker-tenant.clerk.accounts.dev",
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()

    with patch.object(
        deps_module, "_resolve_jwk_for_kid", AsyncMock(return_value=jwk)
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=_request_with_bearer(token),
                db=mock_db,
                x_clerk_user_id=None,
            )

    assert exc_info.value.status_code == 401
    # The foreign sub must NEVER be resolved against the local DB.
    mock_db.execute.assert_not_awaited()
    # Generic detail — must not leak the foreign issuer to the caller.
    assert "attacker-tenant" not in exc_info.value.detail
