"""
Unit tests for GitHub vault settings (issue #123).

Verifies the three reserved GitHub vault fields are declared on Settings,
default to empty strings, and are populated from environment variables.

The fields are currently unconsumed (reserved for a future server-side
fallback in the vault router); they intentionally produce no warning when
left empty.
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


def test_no_vault_warning_in_any_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The fields are reserved and unconsumed; instantiating Settings must
    never emit a 'GitHub vault not fully configured' warning, regardless
    of environment or which fields are set.
    """
    # Issue #90 added a production guard requiring CLERK_FRONTEND_API_URL.
    # Supply a dummy value when env=production so this test isolates the
    # vault-warning code path under test.
    for env in ("development", "staging", "production", "test"):
        monkeypatch.setenv("ENVIRONMENT", env)
        if env == "production":
            monkeypatch.setenv("CLERK_FRONTEND_API_URL", "https://clerk.example.com")
            monkeypatch.setenv("EXTENSION_ID", "cccccccccccccccccccccccccccccccc")
        else:
            monkeypatch.delenv("CLERK_FRONTEND_API_URL", raising=False)
        for key in ("GITHUB_TOKEN", "GITHUB_VAULT_OWNER", "GITHUB_VAULT_REPO"):
            monkeypatch.delenv(key, raising=False)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Settings(_env_file=None)  # type: ignore[call-arg]
        vault_warnings = [w for w in caught if "GitHub vault" in str(w.message)]
        assert vault_warnings == [], (
            f"Unexpected vault warning in ENVIRONMENT={env}: "
            f"{[str(w.message) for w in vault_warnings]}"
        )


def test_no_warning_when_all_fields_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """All three set: no vault warning in any environment."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("GITHUB_VAULT_OWNER", "acme")
    monkeypatch.setenv("GITHUB_VAULT_REPO", "vault")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Settings(_env_file=None)  # type: ignore[call-arg]
    vault_warnings = [w for w in caught if "GitHub vault" in str(w.message)]
    assert vault_warnings == []
