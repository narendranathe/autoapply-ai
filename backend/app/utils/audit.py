"""
Shared audit log helper.

Usage
-----
::

    from app.utils.audit import write_audit_log

    await write_audit_log(
        db,
        user_hash=str(user.id),
        request_id=request_id,
        action="my.action",
        success=True,
        duration_ms=duration_ms,
    )

All arguments after ``db`` are keyword-only to prevent positional confusion
between the two ``str`` fields (``user_hash`` vs ``request_id``).

The function adds the row to the session and flushes (making the row visible
within the current transaction) but does NOT commit. The caller (or FastAPI's
``get_db`` dependency) owns the transaction boundary.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def write_audit_log(
    db: AsyncSession,
    *,
    user_hash: str,
    request_id: str,
    action: str,
    success: bool,
    duration_ms: int,
    error_message: str | None = None,
    metadata_json: str | None = None,
) -> None:
    """Add and flush an AuditLog row. Does not commit — caller owns the transaction."""
    log = AuditLog(
        user_hash=user_hash,
        request_id=request_id,
        action=action,
        success=success,
        error_message=error_message,
        duration_ms=duration_ms,
        metadata_json=metadata_json,
    )
    db.add(log)
    await db.flush()
