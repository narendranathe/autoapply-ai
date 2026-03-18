"""
Applications API endpoints.

GET  /api/v1/applications          → List user's applications (paginated)
GET  /api/v1/applications/{id}     → Get single application
PATCH /api/v1/applications/{id}    → Update application status
GET  /api/v1/applications/stats    → Application statistics
GET  /api/v1/applications/similar  → Find similar previous applications
GET  /api/v1/applications/export.csv → Export all applications as CSV
"""

import csv
import hashlib
import io
import uuid
from collections import Counter

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.application import Application
from app.models.user import User
from app.schemas.application import (
    ApplicationListResponse,
    ApplicationNotesUpdate,
    ApplicationResponse,
    ApplicationStatusUpdate,
    ParseEmailRequest,
    ParseEmailResponse,
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


@router.post("/parse-email", response_model=ParseEmailResponse)
async def parse_email(
    body: ParseEmailRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Parse an email body and classify it into an application status.

    Optionally links the result to an existing application record via fuzzy
    company name matching. Uses LLM classification with keyword fallback.

    Request body:
      - email_body:   Raw email text (HTML or plain text, max 50 000 chars)
      - company_name: Optional company name for matching + prompt context

    Response:
      - suggested_status: one of discovered|applied|phone_screen|interview|offer|rejected
      - confidence:       0.0–1.0
      - reasoning:        short explanation of the classification decision
      - company_match:    matched Application record, or null
    """
    from app.services.email_classifier_service import classify_email_status

    # Classify the email — provider/key taken from user's stored config if
    # available. For now we accept them as query-params or default to fallback.
    # The endpoint uses the keyword fallback when no provider is configured.
    provider = "fallback"
    api_key = ""

    result = await classify_email_status(
        email_body=body.email_body,
        company_name=body.company_name,
        provider=provider,
        api_key=api_key,
    )

    # Try to link to an existing application
    if body.company_name:
        matched_app = await service.find_by_company_name_fuzzy(
            db=db,
            user_id=user.id,
            company_name=body.company_name,
        )
        if matched_app:
            result.company_match = ApplicationResponse.model_validate(matched_app)

    return result


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


@router.patch("/{application_id}/notes")
async def update_application_notes(
    application_id: uuid.UUID,
    body: ApplicationNotesUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update (or clear) the notes field on an application."""
    result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == user.id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "Application not found")

    app.notes = body.notes
    await db.commit()
    await db.refresh(app)

    return {"id": str(app.id), "notes": app.notes}


@router.get("/export.csv")
async def export_applications_csv(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Export all applications as a CSV file.
    Returns a streaming CSV with columns:
      company, role, status, platform, job_url, applied_date, notes
    """
    stmt = (
        select(Application)
        .where(Application.user_id == user.id)
        .order_by(Application.created_at.desc())
    )
    result = await db.execute(stmt)
    apps = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(["Company", "Role", "Status", "Platform", "Job URL", "Applied Date", "Notes"])
    for a in apps:
        writer.writerow(
            [
                a.company_name,
                a.role_title,
                a.status,
                a.platform or "",
                a.job_url or "",
                a.created_at.strftime("%Y-%m-%d") if a.created_at else "",
                (a.notes or "").replace("\n", " "),
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )


@router.get("/funnel")
async def get_application_funnel(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Application funnel metrics: how many applications reach each status.

    Returns ordered funnel stages with counts + conversion rates.
    Also returns a 30-day daily application volume series.
    """
    from datetime import UTC, datetime, timedelta

    stmt = select(Application).where(Application.user_id == user.id)
    result = await db.execute(stmt)
    apps = list(result.scalars().all())

    # Stage funnel (ordered by progression)
    FUNNEL_ORDER = [
        "discovered",
        "applied",
        "tailored",
        "phone_screen",
        "interview",
        "offer",
        "rejected",
    ]
    status_counts = Counter(a.status for a in apps)
    total = len(apps)

    funnel = []
    for stage in FUNNEL_ORDER:
        count = status_counts.get(stage, 0)
        funnel.append(
            {
                "stage": stage,
                "count": count,
                "pct_of_total": round(count / total * 100, 1) if total else 0,
            }
        )

    # 30-day daily volume
    cutoff = datetime.now(UTC) - timedelta(days=30)
    daily: dict[str, int] = {}
    for a in apps:
        if a.created_at and a.created_at >= cutoff:
            day = a.created_at.strftime("%Y-%m-%d")
            daily[day] = daily.get(day, 0) + 1

    # Response rate = (interview + offer) / applied
    applied_count = sum(status_counts.get(s, 0) for s in ["applied", "tailored"])
    positive_count = sum(status_counts.get(s, 0) for s in ["phone_screen", "interview", "offer"])
    response_rate = round(positive_count / applied_count * 100, 1) if applied_count else 0

    # Offer rate = offers / total non-discovered
    offer_count = status_counts.get("offer", 0)
    non_discovered = total - status_counts.get("discovered", 0)
    offer_rate = round(offer_count / non_discovered * 100, 1) if non_discovered else 0

    return {
        "total": total,
        "funnel": funnel,
        "response_rate_pct": response_rate,
        "offer_rate_pct": offer_rate,
        "daily_volume_30d": [{"date": d, "count": c} for d, c in sorted(daily.items())],
    }
