"""
Unit tests for UserProviderConfig model.

Pure Python — no database required.  SQLAlchemy's ORM allows direct
attribute assignment on un-persisted instances, so we can test field
definitions and defaults without a running engine.
"""

import sys
import types
import uuid

# ---------------------------------------------------------------------------
# Stub app.config / app.models.base so the engine is never created.
# This mirrors the pattern used by other unit tests in this directory.
# ---------------------------------------------------------------------------
for _mod in ("app.config",):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

import app.config as _cfg  # noqa: E402

if not hasattr(_cfg, "settings"):
    _cfg.settings = types.SimpleNamespace(  # type: ignore[attr-defined]
        DATABASE_URL="postgresql+asyncpg://x:y@localhost/z",
        DB_PASSWORD=None,
        DB_POOL_SIZE=5,
        DB_MAX_OVERFLOW=10,
        DB_ECHO=False,
        DB_SSL_REQUIRE=False,
        ENVIRONMENT="test",
        is_development=False,
    )

# Stub app.models.base before it is imported so no engine is created.
_base_stub = types.ModuleType("app.models.base")

import sqlalchemy as _sa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncAttrs  # noqa: E402
from sqlalchemy.orm import DeclarativeBase  # noqa: E402


class _Base(AsyncAttrs, DeclarativeBase):
    pass


class _TimestampMixin:
    from datetime import datetime

    from sqlalchemy import DateTime, func
    from sqlalchemy.orm import Mapped, mapped_column

    created_at: "Mapped[datetime]" = mapped_column(
        _sa.DateTime(timezone=True), server_default=_sa.func.now(), nullable=False
    )
    updated_at: "Mapped[datetime]" = mapped_column(
        _sa.DateTime(timezone=True), server_default=_sa.func.now(), nullable=False
    )


_base_stub.Base = _Base  # type: ignore[attr-defined]
_base_stub.TimestampMixin = _TimestampMixin  # type: ignore[attr-defined]
sys.modules["app.models.base"] = _base_stub

# ---------------------------------------------------------------------------
# Now import the model under test.
# ---------------------------------------------------------------------------
from app.models.user_provider_config import UserProviderConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_model_tablename():
    """Table is named user_provider_configs."""
    assert UserProviderConfig.__tablename__ == "user_provider_configs"


def test_model_has_required_fields():
    """UserProviderConfig stores all required fields on instantiation."""
    config = UserProviderConfig(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider_name="anthropic",
        encrypted_api_key="enc_key_abc123",
        is_enabled=True,
    )
    assert config.provider_name == "anthropic"
    assert config.encrypted_api_key == "enc_key_abc123"
    assert config.is_enabled is True


def test_model_optional_field_defaults_to_none():
    """model_override is None when not provided."""
    config = UserProviderConfig(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider_name="openai",
        encrypted_api_key="enc_key_xyz",
        is_enabled=True,
    )
    assert config.model_override is None


def test_model_accepts_model_override():
    """model_override stores a non-None string when provided."""
    config = UserProviderConfig(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        provider_name="openai",
        encrypted_api_key="enc_key_xyz",
        model_override="gpt-4o",
        is_enabled=False,
    )
    assert config.model_override == "gpt-4o"
    assert config.is_enabled is False


def test_model_unique_constraint_defined():
    """uq_user_provider unique constraint is declared on the table."""
    constraint_names = {c.name for c in UserProviderConfig.__table_args__ if hasattr(c, "name")}
    assert "uq_user_provider" in constraint_names
