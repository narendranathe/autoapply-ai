"""Unit tests for the ``DecryptedKey`` wrapper (Issue #197).

The wrapper is defence-in-depth: ``repr(key)``, ``str(key)``, and any
f-string interpolation must emit ``[REDACTED]`` so an accidental
``logger.info(f"key={key}")`` cannot leak the plaintext. The only way to
read the plaintext is via the explicit ``.expose()`` method.
"""

from __future__ import annotations

import io
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Stub app.config / app.models.base so the engine is never created (same
# pattern as test_user_provider_config.py).
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
        FERNET_KEY="",
        is_development=False,
    )

import sqlalchemy as _sa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncAttrs  # noqa: E402
from sqlalchemy.orm import DeclarativeBase  # noqa: E402

_base_stub = types.ModuleType("app.models.base")


class _Base(AsyncAttrs, DeclarativeBase):
    pass


class _TimestampMixin:
    from datetime import datetime

    from sqlalchemy import DateTime, func
    from sqlalchemy.orm import Mapped, mapped_column

    created_at: Mapped[datetime] = mapped_column(
        _sa.DateTime(timezone=True), server_default=_sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        _sa.DateTime(timezone=True), server_default=_sa.func.now(), nullable=False
    )


_base_stub.Base = _Base  # type: ignore[attr-defined]
_base_stub.TimestampMixin = _TimestampMixin  # type: ignore[attr-defined]
sys.modules["app.models.base"] = _base_stub

from app.services.user_provider_configs import DecryptedKey  # noqa: E402

# ---------------------------------------------------------------------------
# Redaction tests — the wrapper's core invariant.
# ---------------------------------------------------------------------------


SECRET = "sk-ant-this-must-never-appear-in-logs-or-reprs"


def test_repr_is_redacted():
    """``repr(key)`` returns ``[REDACTED]`` — never the plaintext."""
    key = DecryptedKey(SECRET)
    assert repr(key) == "[REDACTED]"
    assert SECRET not in repr(key)


def test_str_is_redacted():
    """``str(key)`` returns ``[REDACTED]`` — never the plaintext."""
    key = DecryptedKey(SECRET)
    assert str(key) == "[REDACTED]"
    assert SECRET not in str(key)


def test_f_string_interpolation_is_redacted():
    """``f"key: {key}"`` produces ``[REDACTED]`` — defence-in-depth."""
    key = DecryptedKey(SECRET)
    rendered = f"key: {key}"
    assert rendered == "key: [REDACTED]"
    assert SECRET not in rendered


def test_format_with_spec_is_redacted():
    """``f"{key:>30}"`` also redacts (no format spec leaks the secret)."""
    key = DecryptedKey(SECRET)
    rendered = f"{key:>30}"
    assert SECRET not in rendered
    assert "[REDACTED]" in rendered


def test_percent_format_is_redacted():
    """``"%s" % key`` also redacts."""
    key = DecryptedKey(SECRET)
    rendered = "%s" % key  # noqa: UP031 - explicitly testing % formatting
    assert rendered == "[REDACTED]"
    assert SECRET not in rendered


def test_str_format_is_redacted():
    """``"{0}".format(key)`` also redacts."""
    key = DecryptedKey(SECRET)
    rendered = "{0}".format(key)  # noqa: UP030, UP032 - explicitly testing str.format
    assert SECRET not in rendered


def test_expose_returns_plaintext():
    """``.expose()`` is the only sanctioned plaintext escape hatch."""
    key = DecryptedKey(SECRET)
    assert key.expose() == SECRET


def test_expose_is_only_plaintext_path():
    """No __str__ / __repr__ / __format__ path leaks the secret —
    only ``.expose()`` does."""
    key = DecryptedKey(SECRET)
    sinks = (
        repr(key),
        str(key),
        f"{key}",
        f"{key:>50}",
        "{0}".format(key),  # noqa: UP030,UP032 - explicitly testing str.format
        "%s" % key,  # noqa: UP031 - explicitly testing % formatting
        "%r" % key,  # noqa: UP031 - explicitly testing % formatting
    )
    for sink in sinks:
        assert SECRET not in sink, f"plaintext leaked via: {sink!r}"
    # Only the sanctioned method exposes it.
    assert key.expose() == SECRET


def test_rejects_empty_plaintext():
    """An empty string is meaningless as an API key — wrapper rejects it."""
    with pytest.raises(ValueError):
        DecryptedKey("")


def test_logger_interpolation_does_not_leak():
    """A typical ``logger.info(f"key={key}")`` mistake produces ``[REDACTED]``.

    Wires loguru → a captured sink so we can assert on the rendered line.
    Some sibling tests in this directory replace ``loguru.logger`` with a
    ``SimpleNamespace`` of no-op callables, so we restore the real one
    locally to ensure deterministic behaviour regardless of test order.
    """
    import loguru as _loguru_mod
    from loguru._logger import Core as _Core
    from loguru._logger import Logger as _Logger

    saved = _loguru_mod.logger
    fresh = _Logger(_Core(), None, 0, False, False, False, False, True, [], {})
    _loguru_mod.logger = fresh
    try:
        sink = io.StringIO()
        handler_id = fresh.add(sink, format="{message}", level="DEBUG")
        try:
            key = DecryptedKey(SECRET)
            # The classic mistake: an f-string in a log line.
            fresh.info(f"key={key}")
            # Also try loguru's positional formatter.
            fresh.info("key2={}", key)
            output = sink.getvalue()
        finally:
            fresh.remove(handler_id)
    finally:
        _loguru_mod.logger = saved

    assert SECRET not in output
    assert "[REDACTED]" in output


def test_dataclass_is_frozen():
    """Reassigning the underlying value must raise — keys are immutable."""
    from dataclasses import FrozenInstanceError

    key = DecryptedKey(SECRET)
    with pytest.raises(FrozenInstanceError):
        key._value = "tampered"  # type: ignore[misc]
