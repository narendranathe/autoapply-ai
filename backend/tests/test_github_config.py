"""
Unit tests for GitHub vault settings (issue #123).

Verifies the three GitHub vault fields are read from the environment,
and that the empty-config warning is emitted outside the test environment.
"""

import warnings

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip any inherited values so each test starts from a known state."""
    for key in ("GITHUB_TOKEN", "GITHUB_VAULT_OWNER", "GITHUB_VAULT_REPO"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "test")


def _build(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Construct a fresh Settings with given env vars (bypassing the lru_cache)."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_github_vault_fields_exist_on_settings() -> None:
    """All three vault fields are declared as Settings attributes with str type."""
    fields = Settings.model_fields
    assert "GITHUB_TOKEN" in fields
    assert "GITHUB_VAULT_OWNER" in fields
    assert "GITHUB_VAULT_REPO" in fields
    assert fields["GITHUB_TOKEN"].annotation is str
    assert fields["GITHUB_VAULT_OWNER"].annotation is str
    assert fields["GITHUB_VAULT_REPO"].annotation is str


def test_github_vault_defaults_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env vars produce empty strings, not None."""
    s = _build(monkeypatch)
    assert s.GITHUB_TOKEN == ""
    assert s.GITHUB_VAULT_OWNER == ""
    assert s.GITHUB_VAULT_REPO == ""


def test_github_vault_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Values set in the environment land on the Settings instance."""
    s = _build(
        monkeypatch,
        GITHUB_TOKEN="ghp_test_token_123",
        GITHUB_VAULT_OWNER="acme",
        GITHUB_VAULT_REPO="resume-vault",
    )
    assert s.GITHUB_TOKEN == "ghp_test_token_123"
    assert s.GITHUB_VAULT_OWNER == "acme"
    assert s.GITHUB_VAULT_REPO == "resume-vault"


def test_warning_emitted_when_any_field_empty_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In a non-test environment, missing vault fields emit a UserWarning."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Settings(_env_file=None)  # type: ignore[call-arg]
    messages = [str(w.message) for w in caught]
    vault_warnings = [m for m in messages if "GitHub vault not fully configured" in m]
    assert vault_warnings, f"Expected vault warning, got: {messages}"
    assert "GITHUB_TOKEN" in vault_warnings[0]
    assert "GITHUB_VAULT_OWNER" in vault_warnings[0]
    assert "GITHUB_VAULT_REPO" in vault_warnings[0]


def test_no_warning_when_all_fields_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """All three set: no vault warning in any environment."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("GITHUB_VAULT_OWNER", "acme")
    monkeypatch.setenv("GITHUB_VAULT_REPO", "vault")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Settings(_env_file=None)  # type: ignore[call-arg]
    vault_warnings = [w for w in caught if "GitHub vault not fully configured" in str(w.message)]
    assert vault_warnings == []


def test_no_warning_in_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """ENVIRONMENT=test suppresses the vault warning even when empty."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Settings(_env_file=None)  # type: ignore[call-arg]
    vault_warnings = [w for w in caught if "GitHub vault not fully configured" in str(w.message)]
    assert vault_warnings == []


def test_partial_config_lists_only_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The warning enumerates only the empty fields."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Settings(_env_file=None)  # type: ignore[call-arg]
    vault_warnings = [
        str(w.message) for w in caught if "GitHub vault not fully configured" in str(w.message)
    ]
    assert vault_warnings
    msg = vault_warnings[0]
    assert "GITHUB_TOKEN" not in msg
    assert "GITHUB_VAULT_OWNER" in msg
    assert "GITHUB_VAULT_REPO" in msg
