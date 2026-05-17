"""Tests for CORS config fail-fast behaviour (issue #135)."""

import pytest

from app.config import Settings


def _settings(**overrides: str) -> Settings:
    base: dict[str, str] = {
        "ENVIRONMENT": "production",
        "EXTENSION_ID": "",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg,arg-type]


def test_cors_origins_raises_in_production_without_extension_id() -> None:
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="")
    with pytest.raises(RuntimeError, match="EXTENSION_ID must be set"):
        _ = s.cors_origins


def test_cors_origins_error_message_is_actionable() -> None:
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="")
    with pytest.raises(RuntimeError) as exc_info:
        _ = s.cors_origins
    msg = str(exc_info.value)
    assert "ENVIRONMENT=production" in msg
    assert "fly secrets set EXTENSION_ID" in msg


def test_cors_origins_in_production_with_extension_id_pins_to_extension() -> None:
    s = _settings(ENVIRONMENT="production", EXTENSION_ID="abcdefghijklmnop")
    origins = s.cors_origins
    assert "chrome-extension://abcdefghijklmnop" in origins
    assert all(not o.startswith("chrome-extension://*") for o in origins)
    assert "chrome-extension://*" not in origins


@pytest.mark.parametrize("env", ["development", "staging", "test"])
def test_cors_origins_non_production_falls_back_to_allowed_origins(env: str) -> None:
    s = _settings(ENVIRONMENT=env, EXTENSION_ID="")
    assert s.cors_origins == s.ALLOWED_ORIGINS


def test_create_app_raises_at_boot_when_production_missing_extension_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.config as config_module
    import app.main as main_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("EXTENSION_ID", "")
    monkeypatch.setattr(main_module, "settings", Settings(_env_file=None))  # type: ignore[call-arg,arg-type]

    with pytest.raises(RuntimeError, match="EXTENSION_ID must be set"):
        main_module.create_app()

    config_module.get_settings.cache_clear()
