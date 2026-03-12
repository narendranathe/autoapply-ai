"""
Applications API endpoints.

GET  /api/v1/applications          → List user's applications (paginated)
GET  /api/v1/applications/{id}     → Get single application
PATCH /api/v1/applications/{id}    → Update application status
GET  /api/v1/applications/stats    → Application statistics
GET  /api/v1/applications/similar  → Find similar previous applications
"""

import hashlib
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.application import Application
from app.models.user import User
from app.schemas.application import (
    ApplicationListResponse,
    ApplicationResponse,
    ApplicationStatusUpdate,
)
from app.services.application_service import ApplicationService
from app.utils.hashing import hash_jd

router = APIRouter()
service = ApplicationService()


class TrackApplicationRequest(BaseModel):
    company_name: str
    role_title: str
    job_url: str | None = None
    platform: str | None = None


@router.post("/track", status_code=200)
async def track_application(
    body: TrackApplicationRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Upsert a lightweight application record when the extension detects an application page.

    Called automatically on ApplyMode mount — creates a 'discovered' status record so
    the user can see they visited this page even before submitting.
    Idempotent: if a record for this user + job_url already exists today, returns it unchanged.
    If job_url is absent, falls back to company_name dedup (one record per company per day).
    """
    user_id = user.id
    company = body.company_name.strip()
    role = body.role_title.strip() or "Unknown Role"
    job_url = (body.job_url or "").strip()

    # Build a stable dedup key from job_url (preferred) or company+role
    if job_url:
        dedup_hash = hashlib.sha256(job_url.encode()).hexdigest()
    else:
        dedup_hash = hashlib.sha256(f"{company}::{role}".encode()).hexdigest()

    # Check for existing record — avoid creating duplicates per session
    result = await db.execute(
        select(Application).where(
            Application.user_id == user_id,
            Application.jd_hash == dedup_hash,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return {
            "application_id": str(existing.id),
            "status": existing.status,
            "created": False,
        }

    app = Application(
        user_id=user_id,
        company_name=company,
        role_title=role,
        job_url=job_url or None,
        platform=body.platform or "generic",
        jd_hash=dedup_hash,
        git_path="",  # populated later when a resume is generated/attached
        status="discovered",  # lightweight sentinel — user visited but hasn't applied yet
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)

    return {
        "application_id": str(app.id),
        "status": app.status,
        "created": True,
    }


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    company: str | None = Query(default=None, description="Filter by company name"),
    status: str | None = Query(default=None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    List all applications for the current user.

    Supports pagination and filtering by company name or status.
    Results are ordered by most recent first.
    """
    user_id = user.id

    applications, total = await service.list_applications(
        db=db,
        user_id=user_id,
        page=page,
        per_page=per_page,
        company_filter=company,
        status_filter=status,
    )

    return ApplicationListResponse(
        items=[ApplicationResponse.model_validate(app) for app in applications],
        total=total,
        page=page,
        per_page=per_page,
        has_next=(page * per_page) < total,
    )


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get application statistics (total, by status, unique companies)."""
    user_id = user.id
    return await service.get_stats(db, user_id)


@router.get("/similar")
async def find_similar(
    company_name: str = Query(..., description="Company to check"),
    job_description: str = Query(..., min_length=20, description="JD text"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Check if the user has applied to a similar role before.

    Returns the most similar previous application, if any.
    Used by the Chrome extension to offer "reuse previous resume" flow.
    """
    user_id = user.id
    jd_hash_val = hash_jd(job_description)

    similar = await service.find_similar(db, user_id, jd_hash_val, company_name)

    if similar:
        return {
            "found": True,
            "application": ApplicationResponse.model_validate(similar),
            "message": f"You applied to {similar.company_name} for "
            f"{similar.role_title} on {similar.created_at.strftime('%Y-%m-%d')}. "
            f"Would you like to tweak that resume?",
        }

    return {
        "found": False,
        "application": None,
        "message": f"No previous applications to {company_name} found.",
    }


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single application by ID."""
    user_id = user.id

    application = await service.get_application(db, application_id, user_id)
    if not application:
        raise HTTPException(404, "Application not found")

    return ApplicationResponse.model_validate(application)


@router.patch("/{application_id}")
async def update_application_status(
    application_id: uuid.UUID,
    body: ApplicationStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Update the status of an application.

    Valid statuses: draft, tailored, applied, rejected, interview, offer
    """
    user_id = user.id

    try:
        application = await service.update_status(db, application_id, user_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    if not application:
        raise HTTPException(404, "Application not found")

    return {
        "id": str(application.id),
        "status": application.status,
        "message": f"Status updated to '{application.status}'",
    }
