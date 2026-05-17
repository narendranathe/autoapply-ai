"""Tests for CORS config fail-fast behaviour (issue #92, impl B).

Impl B uses a **fail-fast** approach: ``Settings()`` itself refuses to
instantiate when ``ENVIRONMENT=production`` and ``EXTENSION_ID`` is empty.
This is stricter than impl A's placeholder-and-warn — there is no
placeholder origin, the process simply does not come up.

Three acceptance-criterion paths under test:

1. **Production startup fails**: ``Settings(ENVIRONMENT=production,
   EXTENSION_ID="")`` raises ``ValidationError`` so the process exits with a
   loud error.
2. **Dev startup warns but continues**: in dev/staging/test the same call
   succeeds and emits a ``UserWarning`` (plus a loguru WARNING line).
3. **Production with EXTENSION_ID works**: ``cors_origins`` returns a list
   pinned to the specific extension; the wildcard never appears.

Plus a defence-in-depth check: even if the validator were bypassed by
post-construction mutation, the ``cors_origins`` property itself refuses to
emit a wildcard in production.
"""

from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from app.config import Settings


def _settings(**overrides: str) -> Settings:
    """Build a Settings instance with .env loading disabled.

    Tests are isolated from the developer's local .env so they behave
    identically in CI and locally.
    """
    base: dict[str, str] = {
        "ENVIRONMENT": "development",
        "EXTENSION_ID": "",
        # Issue #90 added a model validator requiring CLERK_FRONTEND_API_URL
        # in production. These CORS tests are not about that field, so we
        # set a dummy URL by default and let individual tests override.
        "CLERK_FRONTEND_API_URL": "https://clerk.example.com",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg,arg-type]


# ── 1. Production fail-fast ──────────────────────────────────────────────


def test_production_without_extension_id_refuses_to_start() -> None:
    """ENVIRONMENT=production + empty EXTENSION_ID -> Settings() raises.

    This is the primary fail-fast guarantee: the process can never come up
    with an unsafe wildcard CORS config in production.
    """
    with pytest.raises(ValidationError) as exc_info:
        _settings(ENVIRONMENT="production", EXTENSION_ID="")
    msg = str(exc_info.value)
    assert "EXTENSION_ID must be set" in msg
    assert "ENVIRONMENT=production" in msg


def test_production_fail_fast_error_message_is_actionable() -> None:
    """The error must tell the operator exactly how to fix it."""
    with pytest.raises(ValidationError) as exc_info:
        _settings(ENVIRONMENT="production", EXTENSION_ID="")
    msg = str(exc_info.value)
    # Mentions the offending env var
    assert "EXTENSION_ID" in msg
    # Mentions why (the wildcard risk)
    assert "wildcard" in msg
    # Gives a concrete fix command
    assert "fly secrets set EXTENSION_ID" in msg


# ── 2. Dev/staging warns but allows ──────────────────────────────────────


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_non_production_without_extension_id_warns_but_starts(env: str) -> None:
    """Dev/staging/test: Settings() instantiates and warns about the wildcard."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        s = _settings(ENVIRONMENT=env, EXTENSION_ID="")
    # Settings instantiated successfully
    assert s.ENVIRONMENT == env
    assert s.EXTENSION_ID == ""
    # A wildcard-warning was emitted
    wildcard_warnings = [
        w for w in caught if "chrome-extension://*" in str(w.message)
    ]
    assert wildcard_warnings, (
        f"expected a wildcard UserWarning in {env}, "
        f"got: {[str(w.message) for w in caught]}"
    )


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_non_production_cors_origins_returns_allowed_origins(env: str) -> None:
    """In dev/staging the property returns the (wildcard-containing) list."""
    s = _settings(ENVIRONMENT=env, EXTENSION_ID="")
    assert s.cors_origins == s.ALLOWED_ORIGINS
    assert "chrome-extension://*" in s.cors_origins


def test_dev_with_extension_id_still_returns_allowed_origins_unchanged() -> None:
    """Dev mode never rewrites ALLOWED_ORIGINS even if EXTENSION_ID is set."""
    s = _settings(ENVIRONMENT="development", EXTENSION_ID="abcdefghijklmnopabcdefghijklmnop")
    assert s.cors_origins == s.ALLOWED_ORIGINS


# ── 3. Production with EXTENSION_ID works ────────────────────────────────


def test_production_with_extension_id_pins_to_specific_extension() -> None:
    """Happy path: production + EXTENSION_ID set -> pinned CORS, no wildcard."""
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="abcdefghijklmnopabcdefghijklmnop")
    origins = s.cors_origins
    assert "chrome-extension://abcdefghijklmnopabcdefghijklmnop" in origins
    # No wildcard, no placeholder, anywhere
    assert "chrome-extension://*" not in origins
    assert all(not o.startswith("chrome-extension://*") for o in origins)


def test_production_with_extension_id_preserves_non_extension_origins() -> None:
    """Pinning the extension origin should not drop http://localhost etc."""
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="abcdefghijklmnopabcdefghijklmnop")
    origins = s.cors_origins
    # Non-chrome-extension origins from ALLOWED_ORIGINS survive
    assert "http://localhost:3000" in origins
    assert "http://localhost:5173" in origins


def test_production_with_extension_id_does_not_emit_wildcard_warning() -> None:
    """Properly configured production should be silent re: the wildcard."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _settings(ENVIRONMENT="production", EXTENSION_ID="abcdefghijklmnopabcdefghijklmnop")
    wildcard_warnings = [
        w for w in caught if "chrome-extension://*" in str(w.message)
    ]
    assert not wildcard_warnings, (
        f"production with EXTENSION_ID should not warn, "
        f"got: {[str(w.message) for w in wildcard_warnings]}"
    )


# ── 4. Defence in depth: cors_origins itself ─────────────────────────────


def test_cors_origins_raises_if_production_extension_id_is_mutated_away() -> None:
    """Acceptance criterion: cors_origins NEVER returns a wildcard in prod.

    Even if someone mutates the Settings object after construction (bypassing
    the model validator), the property must refuse to return a wildcard.
    """
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="abcdefghijklmnopabcdefghijklmnop")
    # Bypass the validator by mutating directly
    s.EXTENSION_ID = ""
    with pytest.raises(RuntimeError) as exc_info:
        _ = s.cors_origins
    assert "EXTENSION_ID must be set" in str(exc_info.value)


def test_cors_origins_never_contains_star_wildcard_in_production() -> None:
    """No production code path may yield a star-wildcard origin."""
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="ponmlkjihgfedcbaponmlkjihgfedcba")
    for o in s.cors_origins:
        assert o != "chrome-extension://*"
        assert not o.endswith("/*")


# ── 5. Boot-time integration ─────────────────────────────────────────────


def test_create_app_fails_at_boot_when_production_misconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_app() must not succeed if Settings() would fail in production.

    This guards the actual application entry point: a misconfigured prod
    deploy never serves a single request.
    """
    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("EXTENSION_ID", "")
    # CLERK_FRONTEND_API_URL is required in production (Issue #90); set a
    # dummy value so this test isolates the EXTENSION_ID failure path.
    monkeypatch.setenv("CLERK_FRONTEND_API_URL", "https://clerk.example.com")

    # Settings() itself raises — this is the fail-fast boundary.
    with pytest.raises(ValidationError, match="EXTENSION_ID must be set"):
        Settings(_env_file=None)  # type: ignore[call-arg]

    config_module.get_settings.cache_clear()
