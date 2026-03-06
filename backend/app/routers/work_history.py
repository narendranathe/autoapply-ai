"""
Work History Router — CRUD for structured employment + education history.

Endpoints:
  GET    /api/v1/work-history          List all entries for the current user
  POST   /api/v1/work-history          Create a new entry
  PATCH  /api/v1/work-history/{id}     Update an entry
  DELETE /api/v1/work-history/{id}     Delete an entry
  GET    /api/v1/work-history/text     Formatted text block for LLM injection
  POST   /api/v1/work-history/seed     Bulk-create entries (idempotent on company+role)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.work_history import WorkHistoryEntry

router = APIRouter()


# ── Pydantic schemas ───────────────────────────────────────────────────────


class WorkHistoryEntryIn(BaseModel):
    entry_type: str = "work"
    company_name: str
    role_title: str
    start_date: str
    end_date: str | None = None
    is_current: bool = False
    location: str | None = None
    bullets: list[str] = []
    technologies: list[str] = []
    team_size: int | None = None
    sort_order: int = 0


class WorkHistoryEntryOut(WorkHistoryEntryIn):
    id: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ── Helpers ────────────────────────────────────────────────────────────────


async def _get_entry(entry_id: str, user_id: uuid.UUID, db: AsyncSession) -> WorkHistoryEntry:
    stmt = select(WorkHistoryEntry).where(
        WorkHistoryEntry.id == uuid.UUID(entry_id),
        WorkHistoryEntry.user_id == user_id,
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


def _format_work_history_text(entries: list[WorkHistoryEntry]) -> str:
    """Format all entries into a dense text block for LLM injection."""
    if not entries:
        return ""
    blocks = [e.to_text_block() for e in entries]
    return "\n\n".join(blocks)


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/text")
async def get_work_history_text(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return formatted work history as a single text block for LLM injection."""
    stmt = (
        select(WorkHistoryEntry)
        .where(WorkHistoryEntry.user_id == user.id)
        .order_by(WorkHistoryEntry.sort_order, WorkHistoryEntry.created_at.desc())
    )
    result = await db.execute(stmt)
    entries = list(result.scalars().all())
    return {"text": _format_work_history_text(entries), "entry_count": len(entries)}


@router.get("")
async def list_work_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all work history entries for the current user."""
    stmt = (
        select(WorkHistoryEntry)
        .where(WorkHistoryEntry.user_id == user.id)
        .order_by(WorkHistoryEntry.sort_order, WorkHistoryEntry.created_at.desc())
    )
    result = await db.execute(stmt)
    entries = list(result.scalars().all())
    return {
        "entries": [
            {
                "id": str(e.id),
                "entry_type": e.entry_type,
                "company_name": e.company_name,
                "role_title": e.role_title,
                "start_date": e.start_date,
                "end_date": e.end_date,
                "is_current": e.is_current,
                "location": e.location,
                "bullets": e.bullets,
                "technologies": e.technologies,
                "team_size": e.team_size,
                "sort_order": e.sort_order,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "total": len(entries),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_work_history_entry(
    payload: WorkHistoryEntryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new work history entry."""
    entry = WorkHistoryEntry(
        user_id=user.id,
        **payload.model_dump(),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {"id": str(entry.id), "created": True}


@router.patch("/{entry_id}")
async def update_work_history_entry(
    entry_id: str,
    payload: WorkHistoryEntryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a work history entry."""
    entry = await _get_entry(entry_id, user.id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await db.commit()
    return {"id": entry_id, "updated": True}


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_history_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a work history entry."""
    entry = await _get_entry(entry_id, user.id, db)
    await db.delete(entry)
    await db.commit()


@router.post("/seed", status_code=status.HTTP_201_CREATED)
async def seed_work_history(
    entries: list[WorkHistoryEntryIn],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Bulk-create entries. Skips any entry where (company_name, role_title) already exists
    for this user — idempotent re-seeding.
    """
    # Fetch existing (company, role) pairs
    stmt = select(WorkHistoryEntry.company_name, WorkHistoryEntry.role_title).where(
        WorkHistoryEntry.user_id == user.id
    )
    result = await db.execute(stmt)
    existing = {(r.company_name, r.role_title) for r in result.all()}

    created = 0
    for e in entries:
        key = (e.company_name, e.role_title)
        if key in existing:
            continue
        db.add(WorkHistoryEntry(user_id=user.id, **e.model_dump()))
        created += 1

    await db.commit()
    return {"created": created, "skipped": len(entries) - created}
