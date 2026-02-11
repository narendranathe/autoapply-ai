"""
Applications API endpoints.

GET  /api/v1/applications          → List user's applications (paginated)
GET  /api/v1/applications/{id}     → Get single application
PATCH /api/v1/applications/{id}    → Update application status
GET  /api/v1/applications/stats    → Application statistics
GET  /api/v1/applications/similar  → Find similar previous applications
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.dependencies import get_db
from app.services.application_service import ApplicationService
from app.schemas.application import (
    ApplicationResponse,
    ApplicationListResponse,
    ApplicationStatusUpdate,
)
from app.utils.hashing import hash_jd

router = APIRouter()
service = ApplicationService()


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    company: str | None = Query(default=None, description="Filter by company name"),
    status: str | None = Query(default=None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
):
    """
    List all applications for the current user.

    Supports pagination and filtering by company name or status.
    Results are ordered by most recent first.
    """
    # TODO: Get user_id from authenticated session
    # For now, use a placeholder
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

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
):
    """Get application statistics (total, by status, unique companies)."""
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return await service.get_stats(db, user_id)


@router.get("/similar")
async def find_similar(
    company_name: str = Query(..., description="Company to check"),
    job_description: str = Query(..., min_length=20, description="JD text"),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if the user has applied to a similar role before.

    Returns the most similar previous application, if any.
    Used by the Chrome extension to offer "reuse previous resume" flow.
    """
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
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
):
    """Get a single application by ID."""
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    application = await service.get_application(db, application_id, user_id)
    if not application:
        raise HTTPException(404, "Application not found")

    return ApplicationResponse.model_validate(application)


@router.patch("/{application_id}")
async def update_application_status(
    application_id: uuid.UUID,
    body: ApplicationStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update the status of an application.

    Valid statuses: draft, tailored, applied, rejected, interview, offer
    """
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    try:
        application = await service.update_status(
            db, application_id, user_id, body.status
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not application:
        raise HTTPException(404, "Application not found")

    return {
        "id": str(application.id),
        "status": application.status,
        "message": f"Status updated to '{application.status}'",
    }