"""Tests for Settings validators in app.config."""

import warnings
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings


def _make_settings() -> Settings:
    # _env_file=None disables .env loading so tests are isolated from local env files.
    kwargs: dict[str, Any] = {"_env_file": None}
    return Settings(**kwargs)


def test_fernet_key_invalid_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FERNET_KEY", "not-a-valid-fernet-key!!!")
    with pytest.raises(ValidationError) as exc:
        _make_settings()
    assert "FERNET_KEY is invalid" in str(exc.value)


def test_fernet_key_empty_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FERNET_KEY", "")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = _make_settings()
    assert settings.FERNET_KEY == ""
    assert any("FERNET_KEY is unset" in str(w.message) for w in caught)


def test_fernet_key_valid_passes_silently(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = _make_settings()
    assert key == settings.FERNET_KEY
    assert not any("FERNET_KEY" in str(w.message) for w in caught)


# ---------------------------------------------------------------------------
# CLERK_FRONTEND_API_URL — Issue #90 (P0 auth bypass guard)
# ---------------------------------------------------------------------------


def test_production_without_clerk_frontend_api_url_fails_startup() -> None:
    """ENVIRONMENT=production with empty CLERK_FRONTEND_API_URL must refuse to start.

    Without this URL, JWKS validation is skipped and X-Clerk-User-Id is trusted
    blindly — an auth bypass.
    """
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            CLERK_FRONTEND_API_URL="",
            EXTENSION_ID="prod-extension-id",
        )
    assert "CLERK_FRONTEND_API_URL" in str(exc_info.value)


def test_production_with_clerk_frontend_api_url_starts_cleanly() -> None:
    """ENVIRONMENT=production with a non-empty URL must validate cleanly."""
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        CLERK_FRONTEND_API_URL="https://app.clerk.accounts.dev",
        EXTENSION_ID="prod-extension-id",
    )
    assert settings.is_production is True
    assert settings.CLERK_FRONTEND_API_URL == "https://app.clerk.accounts.dev"


def test_development_without_clerk_frontend_api_url_warns() -> None:
    """ENVIRONMENT=development with empty CLERK_FRONTEND_API_URL must warn (not fail)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = Settings(
            _env_file=None,
            ENVIRONMENT="development",
            CLERK_FRONTEND_API_URL="",
        )
    assert settings.CLERK_FRONTEND_API_URL == ""
    assert any("CLERK_FRONTEND_API_URL" in str(w.message) for w in caught)


def test_staging_without_clerk_frontend_api_url_warns() -> None:
    """ENVIRONMENT=staging with empty CLERK_FRONTEND_API_URL must warn (not fail)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = Settings(
            _env_file=None,
            ENVIRONMENT="staging",
            CLERK_FRONTEND_API_URL="",
        )
    assert settings.CLERK_FRONTEND_API_URL == ""
    assert any("CLERK_FRONTEND_API_URL" in str(w.message) for w in caught)


def test_development_with_clerk_frontend_api_url_no_warning() -> None:
    """ENVIRONMENT=development with a non-empty URL must not warn about Clerk."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Settings(
            _env_file=None,
            ENVIRONMENT="development",
            CLERK_FRONTEND_API_URL="https://app.clerk.accounts.dev",
        )
    assert not any("CLERK_FRONTEND_API_URL" in str(w.message) for w in caught)
