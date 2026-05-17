"""Tests for CORS config production/dev behaviour (issue #92).

Behaviour under test:

1. **Production without ``EXTENSION_ID``**: ``Settings()`` instantiates
   successfully (no fail-fast crash). ``cors_origins`` returns a non-routable
   placeholder origin — never the ``chrome-extension://*`` wildcard — so the
   misconfigured deploy fails closed. A single CRITICAL log line is emitted
   at settings construction so operators see the misconfiguration at startup.
2. **Production with ``EXTENSION_ID``**: ``cors_origins`` pins to a single
   extension origin (no wildcard, no placeholder), and no CRITICAL log line
   is emitted.
3. **Non-production (dev/staging/test)**: ``cors_origins`` returns the
   configured ``ALLOWED_ORIGINS`` unchanged (wildcard permitted for local
   dev) and no CRITICAL log line is emitted.
"""

from __future__ import annotations

import logging

import pytest
from _pytest.logging import LogCaptureFixture
from loguru import logger

from app.config import Settings


def _settings(**overrides: str) -> Settings:
    base: dict[str, str] = {
        "ENVIRONMENT": "production",
        "EXTENSION_ID": "",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg,arg-type]


@pytest.fixture
def loguru_caplog(caplog: LogCaptureFixture) -> LogCaptureFixture:
    """Pipe loguru records into the stdlib logging caplog fixture."""

    class PropagateHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropagateHandler(), format="{message}", level=0)
    caplog.set_level(logging.DEBUG)
    yield caplog
    logger.remove(handler_id)


# ── Production: EXTENSION_ID missing ──────────────────────────────────────


def test_cors_origins_returns_placeholder_in_production_without_extension_id(
    loguru_caplog: LogCaptureFixture,
) -> None:
    """Wildcard MUST NOT appear; placeholder MUST appear so deploy fails closed."""
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="")
    origins = s.cors_origins
    assert "chrome-extension://*" not in origins
    assert all(not o.startswith("chrome-extension://*") for o in origins)
    assert "chrome-extension://PLACEHOLDER_SET_EXTENSION_ID" in origins


def test_missing_extension_id_in_production_emits_critical_log(
    loguru_caplog: LogCaptureFixture,
) -> None:
    """A CRITICAL log line MUST be emitted at Settings construction."""
    _ = _settings(ENVIRONMENT="production", EXTENSION_ID="")
    critical_records = [r for r in loguru_caplog.records if r.levelno >= logging.CRITICAL]
    assert critical_records, "expected a CRITICAL log line at settings construction"
    msg = "\n".join(r.getMessage() for r in critical_records)
    assert "EXTENSION_ID" in msg
    assert "production" in msg


def test_critical_log_emitted_once_per_settings_construction(
    loguru_caplog: LogCaptureFixture,
) -> None:
    """Reading cors_origins repeatedly must not re-emit the CRITICAL warning."""
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="")
    loguru_caplog.clear()
    for _ in range(5):
        _ = s.cors_origins
    critical_records = [r for r in loguru_caplog.records if r.levelno >= logging.CRITICAL]
    assert critical_records == []


def test_production_without_extension_id_does_not_raise(
    loguru_caplog: LogCaptureFixture,
) -> None:
    """Settings() must instantiate (no fail-fast); misconfig is surfaced via log + placeholder."""
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="")
    assert s.ENVIRONMENT == "production"
    assert s.EXTENSION_ID == ""


# ── Production: EXTENSION_ID present ──────────────────────────────────────


def test_cors_origins_in_production_with_extension_id_pins_to_extension(
    loguru_caplog: LogCaptureFixture,
) -> None:
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="abcdefghijklmnop")
    origins = s.cors_origins
    assert "chrome-extension://abcdefghijklmnop" in origins
    assert all(not o.startswith("chrome-extension://*") for o in origins)
    assert "chrome-extension://*" not in origins
    assert "chrome-extension://PLACEHOLDER_SET_EXTENSION_ID" not in origins


def test_production_with_extension_id_preserves_non_extension_origins(
    loguru_caplog: LogCaptureFixture,
) -> None:
    """Pinning the extension origin must not drop http://localhost etc."""
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="abcdefghijklmnop")
    origins = s.cors_origins
    assert "http://localhost:3000" in origins
    assert "http://localhost:5173" in origins


def test_no_critical_log_when_production_has_extension_id(
    loguru_caplog: LogCaptureFixture,
) -> None:
    _ = _settings(ENVIRONMENT="production", EXTENSION_ID="abcdefghijklmnop")
    critical_records = [r for r in loguru_caplog.records if r.levelno >= logging.CRITICAL]
    assert critical_records == []


# ── Non-production ────────────────────────────────────────────────────────


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_cors_origins_non_production_falls_back_to_allowed_origins(
    env: str, loguru_caplog: LogCaptureFixture
) -> None:
    s = _settings(ENVIRONMENT=env, EXTENSION_ID="")
    assert s.cors_origins == s.ALLOWED_ORIGINS
    # Wildcard is still allowed in non-prod for local dev convenience.
    assert "chrome-extension://*" in s.cors_origins


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_no_critical_log_in_non_production(
    env: str, loguru_caplog: LogCaptureFixture
) -> None:
    _ = _settings(ENVIRONMENT=env, EXTENSION_ID="")
    critical_records = [r for r in loguru_caplog.records if r.levelno >= logging.CRITICAL]
    assert critical_records == []


def test_dev_with_extension_id_still_returns_allowed_origins_unchanged(
    loguru_caplog: LogCaptureFixture,
) -> None:
    """Dev mode never rewrites ALLOWED_ORIGINS even if EXTENSION_ID is set."""
    s = _settings(ENVIRONMENT="development", EXTENSION_ID="abcdefghijklmnop")
    assert s.cors_origins == s.ALLOWED_ORIGINS


# ── App boot ──────────────────────────────────────────────────────────────


def test_create_app_does_not_raise_when_production_missing_extension_id(
    monkeypatch: pytest.MonkeyPatch, loguru_caplog: LogCaptureFixture
) -> None:
    """
    create_app must succeed even when EXTENSION_ID is missing in production:
    the misconfiguration is surfaced via a CRITICAL log + placeholder origin,
    not by crashing the process (issue #92).
    """
    import app.config as config_module
    import app.main as main_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("EXTENSION_ID", "")
    monkeypatch.setattr(main_module, "settings", Settings(_env_file=None))  # type: ignore[call-arg,arg-type]

    app = main_module.create_app()
    assert app is not None

    config_module.get_settings.cache_clear()
