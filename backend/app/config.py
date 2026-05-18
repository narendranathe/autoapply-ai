"""
Application configuration using Pydantic Settings.

Every configurable value comes from environment variables.
Local development uses .env file. Production uses platform secrets.

Usage:
    from app.config import settings
    print(settings.DATABASE_URL)
"""

import re
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

    # ── Stripe ────────────────────────────────────────────
    # STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are required for billing
    # to function. STRIPE_PRICE_PRO / STRIPE_PRICE_TEAM are the price IDs
    # for each subscription tier (from the Stripe dashboard).
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_TEAM: str = ""
    STRIPE_BILLING_PORTAL_RETURN_URL: str = "http://localhost:5173/billing"
    STRIPE_CHECKOUT_SUCCESS_URL: str = "http://localhost:5173/billing?status=success"
    STRIPE_CHECKOUT_CANCEL_URL: str = "http://localhost:5173/billing?status=cancel"

    # ── CORS ──────────────────────────────────────────────
    # In production EXTENSION_ID is REQUIRED — Settings() will refuse to
    # instantiate (and the process refuses to start) when
    # ENVIRONMENT=production and this is empty (see
    # ``require_extension_id_in_production`` below). This prevents the
    # chrome-extension://* wildcard in ALLOWED_ORIGINS from allowing arbitrary
    # extensions to call the API. In dev/staging the wildcard is allowed but a
    # warning is logged (see ``warn_wildcard_in_dev``).
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

        Production: EXTENSION_ID is required (enforced at Settings instantiation
        by ``require_extension_id_in_production``) so CORS is pinned to a single
        published extension. This property NEVER returns a chrome-extension://*
        wildcard in production — even as a placeholder. If, somehow, the
        validator was bypassed and EXTENSION_ID is still empty, the property
        raises RuntimeError as a defence-in-depth check.

        Dev/staging: returns ALLOWED_ORIGINS as-is (wildcard permitted).
        ``warn_wildcard_in_dev`` already logged a warning at startup when the
        wildcard is in effect.
        """
        if self.is_production:
            if not self.EXTENSION_ID:
                # Defence in depth — the model_validator should have caught
                # this at instantiation. Reaching here means someone mutated
                # the settings object after construction.
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

    @field_validator("EXTENSION_ID")
    @classmethod
    def validate_extension_id(cls, v: str) -> str:
        """
        Chrome extension IDs are exactly 32 lowercase letters (a-p) — they are
        a base16 encoding using a-p instead of 0-f. An operator typo such as
        ``*`` or ``"   "`` would otherwise be embedded literally into the CORS
        allowlist as ``chrome-extension://*`` / ``chrome-extension://   `` and
        defeat the fail-fast guarantee. Validate the format here so bad values
        are rejected at startup (issue #92).

        Empty string is allowed — it is the documented dev/staging default and
        is rejected separately in production by
        ``require_extension_id_in_production``.
        """
        if v and not re.fullmatch(r"^[a-p]{32}$", v):
            raise ValueError(f"EXTENSION_ID must be exactly 32 lowercase letters (a-p), got {v!r}")
        return v

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

    @model_validator(mode="after")
    def require_clerk_url_in_production(self) -> Self:
        """
        Fail-fast guard against the auth bypass in issue #90.

        ``get_current_user`` only runs RS256 JWKS validation when
        ``CLERK_FRONTEND_API_URL`` is set. Without it, the backend silently
        falls back to trusting the ``X-Clerk-User-Id`` header — a complete
        auth bypass. Refuse to construct Settings in production so the
        process crashes at boot, not on the first authenticated request.

        Dev / staging / test environments are allowed to leave the URL
        unset so local workflows (no Clerk tenant configured) keep working;
        the auth dependency emits a one-shot warning in that case.
        """
        if self.is_production and not self.CLERK_FRONTEND_API_URL:
            raise ValueError(
                "CLERK_FRONTEND_API_URL must be set when ENVIRONMENT=production. "
                "Without it, get_current_user trusts the X-Clerk-User-Id header from "
                "any caller — a complete auth bypass. Set it to your Clerk Frontend "
                "API URL, e.g. `fly secrets set "
                "CLERK_FRONTEND_API_URL=https://your-app.clerk.accounts.dev`."
            )
        return self

    @model_validator(mode="after")
    def require_extension_id_in_production(self) -> Self:
        """
        Fail-fast: refuse to start the process when ENVIRONMENT=production and
        EXTENSION_ID is unset. Otherwise the chrome-extension://* wildcard in
        ALLOWED_ORIGINS would allow any installed Chrome extension to call the
        production API (issue #92).
        """
        if self.is_production and not self.EXTENSION_ID:
            raise ValueError(
                "EXTENSION_ID must be set when ENVIRONMENT=production. "
                "The chrome-extension://* wildcard in ALLOWED_ORIGINS would "
                "otherwise let any installed extension call the API. "
                "Set it to your published Chrome Web Store extension id, e.g. "
                "`fly secrets set EXTENSION_ID=<your-extension-id>`."
            )
        return self

    @model_validator(mode="after")
    def warn_wildcard_in_dev(self) -> Self:
        """
        Dev/staging: emit a WARNING when the chrome-extension://* wildcard is
        present in ALLOWED_ORIGINS. The wildcard is allowed here for local
        development convenience, but operators should be aware that any locally
        installed Chrome extension can hit the API.
        """
        if not self.is_production and any(
            o.startswith("chrome-extension://*") for o in self.ALLOWED_ORIGINS
        ):
            import warnings

            warnings.warn(
                f"ALLOWED_ORIGINS contains a chrome-extension://* wildcard "
                f"(ENVIRONMENT={self.ENVIRONMENT}). Any installed Chrome "
                "extension can call the API. This is permitted in dev/staging "
                "only; production requires EXTENSION_ID to be set.",
                stacklevel=2,
            )
            try:
                from loguru import logger

                logger.warning(
                    "CORS wildcard chrome-extension://* enabled in {env} — "
                    "any installed extension can call the API. Set EXTENSION_ID "
                    "to pin to a specific extension.",
                    env=self.ENVIRONMENT,
                )
            except ImportError as e:
                # loguru is a declared runtime dep, but if a slim environment
                # is missing it we still want the warnings.warn() above to
                # land — fall back to stderr rather than swallowing real bugs
                # behind a bare ``except`` (issue #92 round 2).
                import sys

                print(
                    f"config: loguru unavailable ({e}); wildcard warning emitted "
                    "via warnings module only",
                    file=sys.stderr,
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_staging(self) -> bool:
        return self.ENVIRONMENT == "staging"

    @property
    def clerk_jwt_enforced(self) -> bool:
        """
        True when the auth dependency must verify Clerk-issued JWTs.

        Production deploys always enforce JWT verification — the config
        validator above guarantees ``CLERK_FRONTEND_API_URL`` is set, so this
        is effectively constant in production. Non-production environments
        enforce JWT verification only when ``CLERK_FRONTEND_API_URL`` is
        configured (e.g. staging pointed at a real Clerk tenant).
        """
        return self.is_production or bool(self.CLERK_FRONTEND_API_URL)


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Call this instead of Settings() directly."""
    return Settings()


settings = get_settings()
