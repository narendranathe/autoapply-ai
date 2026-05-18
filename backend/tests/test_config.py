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
