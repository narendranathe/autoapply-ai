"""
Application configuration using Pydantic Settings.

Every configurable value comes from environment variables.
Local development uses .env file. Production uses platform secrets.

Usage:
    from app.config import settings
    print(settings.DATABASE_URL)
"""

from functools import lru_cache

from pydantic import field_validator
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
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False  # Set True to log all SQL queries

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

    # ── Encryption (for storing user API keys) ────────────
    FERNET_KEY: str = ""

    # ── GitHub OAuth ──────────────────────────────────────
    GITHUB_APP_CLIENT_ID: str = ""
    GITHUB_APP_CLIENT_SECRET: str = ""

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
        In production with a known extension ID, restricts to that extension only.
        """
        if self.is_production and self.EXTENSION_ID:
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
