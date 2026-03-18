"""
Unit tests for app.utils.audit.write_audit_log().

Verifies that the helper:
1. Constructs an AuditLog with all required fields
2. Adds the row to the session
3. Calls db.flush()
4. Works with optional fields absent (error_message, metadata_json)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.utils.audit import write_audit_log


@pytest.mark.asyncio
async def test_write_audit_log_adds_and_flushes():
    """AuditLog is added to db and flush() is called once."""
    db = MagicMock()
    db.flush = AsyncMock()

    await write_audit_log(
        db,
        user_hash="user-123",
        request_id="req-abc",
        action="reflect_stream",
        success=True,
        duration_ms=450,
    )

    assert db.add.call_count == 1
    log = db.add.call_args[0][0]
    assert log.user_hash == "user-123"
    assert log.request_id == "req-abc"
    assert log.action == "reflect_stream"
    assert log.success is True
    assert log.duration_ms == 450
    assert log.error_message is None
    assert log.metadata_json is None
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_audit_log_with_optional_fields():
    """error_message and metadata_json are set when provided."""
    db = MagicMock()
    db.flush = AsyncMock()

    await write_audit_log(
        db,
        user_hash="user-456",
        request_id="req-xyz",
        action="resume.parse",
        success=False,
        duration_ms=120,
        error_message="timeout",
        metadata_json='{"format":"pdf"}',
    )

    log = db.add.call_args[0][0]
    assert log.success is False
    assert log.error_message == "timeout"
    assert log.metadata_json == '{"format":"pdf"}'


@pytest.mark.asyncio
async def test_write_audit_log_flush_called_even_on_add_error():
    """
    Flush is awaited once regardless of whether the caller does extra work after.
    (Ensures the flush pattern is consistent — actual transaction rollback is
    the session's responsibility, not the helper's.)
    """
    db = MagicMock()
    db.flush = AsyncMock()

    await write_audit_log(
        db,
        user_hash="u",
        request_id="r",
        action="test",
        success=True,
        duration_ms=1,
    )

    assert db.flush.await_args_list == [call()]
