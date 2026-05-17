"""
Application configuration using Pydantic Settings.

Every configurable value comes from environment variables.
Local development uses .env file. Production uses platform secrets.

Usage:
    from app.config import settings
    print(settings.DATABASE_URL)
"""

from functools import lru_cache
from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All application settings. Grouped by concern.
    Type hints enforce validation at startup — if a required
    env var is missing, the app won't start (fail fast).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Don't crash on unknown env vars
    )

    # ── Core ──────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_VERSION: str = "v1"
    APP_NAME: str = "AutoApply AI"

    # ── Database ──────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://autoapply:localdev@localhost:5432/autoapply"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        """
        Render (and some other hosts) provide DATABASE_URL as postgres:// or
        postgresql:// (psycopg2 sync scheme). asyncpg requires
        postgresql+asyncpg://. Normalise here so the app works on any host.
        """
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # Separate password field — avoids URL percent-encoding issues with
    # special chars (e.g. @ in passwords). When set, overrides any password
    # in DATABASE_URL via connect_args so the URL never needs encoding.
    DB_PASSWORD: str = ""

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False  # Set True to log all SQL queries
    DB_SSL_REQUIRE: bool = False  # Set True for Supabase / managed Postgres in production

    # ── Redis ─────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── Auth ──────────────────────────────────────────────
    CLERK_SECRET_KEY: str = ""
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60

    # ── Clerk ─────────────────────────────────────────────
    # CLERK_FRONTEND_API_URL example: https://your-app.clerk.accounts.dev
    CLERK_FRONTEND_API_URL: str = ""
    # JWT audience — set to your backend API domain in production
    CLERK_JWT_AUDIENCE: str = ""

    # ── Dev auth bypass ───────────────────────────────────
    # Clerk user id used by get_current_user when ENVIRONMENT=development and
    # no JWT / X-Clerk-User-Id header is present. Must be explicitly set —
    # there is no implicit "first DB user" fallback. Never set in production.
    DEV_TEST_USER_ID: str = ""

    # ── Encryption (for storing user API keys) ────────────
    FERNET_KEY: str = ""

    # ── GitHub OAuth ──────────────────────────────────────
    GITHUB_APP_CLIENT_ID: str = ""
    GITHUB_APP_CLIENT_SECRET: str = ""

    # ── GitHub Vault (reserved for future server-side fallback) ───────────
    # These typed fields are declared so operators can set them today, but
    # they are NOT yet consumed anywhere in the codebase. Vault operations
    # currently use the per-user `encrypted_github_token` stored on the
    # `User` model (see `app/routers/vault/github.py` and `_shared.py`).
    #
    # Follow-up: wire a server-side fallback in the vault router that uses
    # these values when the per-user token is absent. Until then, leaving
    # them empty is the expected default and produces no warning.
    GITHUB_TOKEN: str = ""
    GITHUB_VAULT_OWNER: str = ""
    GITHUB_VAULT_REPO: str = ""

    # ── Vector Backend ────────────────────────────────────
    VECTOR_BACKEND: str = "pgvector"  # "pgvector" | "pinecone"
    PINECONE_API_KEY: str | None = None
    PINECONE_INDEX_NAME: str = "autoapply-answers"

    # ── Monitoring ────────────────────────────────────────
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    LOG_LEVEL: str = "INFO"

    # ── Rate Limiting ─────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    GITHUB_API_RATE_BUFFER: int = 500

    # ── Ollama ────────────────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # ── CORS ──────────────────────────────────────────────
    # In production set EXTENSION_ID to your published Chrome extension ID
    # so only your extension can call the API.
    EXTENSION_ID: str = ""
    ALLOWED_ORIGINS: list[str] = [
        "chrome-extension://*",
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    @property
    def cors_origins(self) -> list[str]:
        """
        Returns effective CORS origins.
        In production EXTENSION_ID is required so CORS is restricted to a single
        published extension; falling back to a chrome-extension://* wildcard
        would let any extension call the API. Raises RuntimeError at startup
        when the production deploy is missing the secret.
        """
        if self.is_production:
            if not self.EXTENSION_ID:
                raise RuntimeError(
                    "EXTENSION_ID must be set when ENVIRONMENT=production. "
                    "The chrome-extension://* wildcard in ALLOWED_ORIGINS would "
                    "otherwise let any installed extension call the API. "
                    "Set it to your published Chrome Web Store extension id, e.g. "
                    "`fly secrets set EXTENSION_ID=<your-extension-id>`."
                )
            return [
                f"chrome-extension://{self.EXTENSION_ID}",
                *[o for o in self.ALLOWED_ORIGINS if not o.startswith("chrome-extension://")],
            ]
        return self.ALLOWED_ORIGINS

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production", "test"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}, got '{v}'")
        return v

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if v == "change-me-in-production":
            import warnings

            warnings.warn(
                "JWT_SECRET is set to default. Generate a real secret for production: "
                "openssl rand -hex 32",
                stacklevel=2,
            )
        return v

    @field_validator("FERNET_KEY", mode="after")
    @classmethod
    def validate_fernet_key(cls, v: str) -> str:
        if not v:
            import warnings

            warnings.warn(
                "FERNET_KEY is unset — API key and GitHub token encryption will fail "
                "at runtime. Generate one: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"',
                stacklevel=2,
            )
            return v
        try:
            from cryptography.fernet import Fernet

            Fernet(v.encode())
        except Exception as e:
            raise ValueError(
                f"FERNET_KEY is invalid: {e}. Generate one with Fernet.generate_key().decode()"
            ) from e
        return v

    @model_validator(mode="after")
    def forbid_dev_test_user_in_production(self) -> Self:
        if self.is_production and self.DEV_TEST_USER_ID:
            raise ValueError(
                "DEV_TEST_USER_ID must not be set when ENVIRONMENT=production "
                "(dev auth bypass is unsafe in production)."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Call this instead of Settings() directly."""
    return Settings()


settings = get_settings()
