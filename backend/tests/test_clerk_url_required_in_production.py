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

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request
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
    401 — never trust the X-Clerk-User-Id header in production."""
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
