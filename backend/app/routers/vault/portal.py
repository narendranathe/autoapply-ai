"""Vault sub-module: ATS portal scanner endpoint."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.portal_scan import PortalScanCache
from app.models.user import User

router = APIRouter()


class PortalScanRequest(BaseModel):
    url: str


class PortalScanResponse(BaseModel):
    scan_id: uuid.UUID | None
    cached: bool
    manual_entry: bool
    board_type: str | None
    title: str
    company: str
    location: str
    remote_policy: str
    compensation_min: int | None
    compensation_max: int | None
    requirements: list[str]
    responsibilities: list[str]
    apply_url: str
    job_id: str
    schema_version: int


@router.post("/portal/scan", response_model=PortalScanResponse)
async def scan_portal(
    body: PortalScanRequest,
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.portal_scanner_service import detect_board, scan_url

    # Cache lookup
    detected = detect_board(body.url)
    if detected and not refresh:
        board_type, company_slug, job_id = detected
        result = await db.execute(
            select(PortalScanCache).where(
                PortalScanCache.user_id == user.id,
                PortalScanCache.board_type == board_type,
                PortalScanCache.job_id == job_id,
            )
        )
        cached_row = result.scalar_one_or_none()
        if cached_row:
            cached_row.last_accessed_at = datetime.now(tz=UTC)
            await db.commit()
            sr = cached_row.scan_result
            return PortalScanResponse(
                scan_id=cached_row.id,
                cached=True,
                manual_entry=False,
                board_type=cached_row.board_type,
                title=sr.get("title", ""),
                company=cached_row.company_name,
                location=sr.get("location", ""),
                remote_policy=sr.get("remote_policy", ""),
                compensation_min=cached_row.compensation_min,
                compensation_max=cached_row.compensation_max,
                requirements=sr.get("requirements", []),
                responsibilities=sr.get("responsibilities", []),
                apply_url=cached_row.job_url,
                job_id=cached_row.job_id,
                schema_version=cached_row.schema_version,
            )

    scan = await scan_url(body.url)

    if scan.manual_entry:
        return PortalScanResponse(
            scan_id=None,
            cached=False,
            manual_entry=True,
            board_type=None,
            title="",
            company="",
            location="",
            remote_policy="",
            compensation_min=None,
            compensation_max=None,
            requirements=[],
            responsibilities=[],
            apply_url=body.url,
            job_id="",
            schema_version=1,
        )

    scan_result_json = {
        "title": scan.title,
        "location": scan.location,
        "remote_policy": scan.remote_policy,
        "requirements": scan.requirements,
        "responsibilities": scan.responsibilities,
        "schema_version": 1,
    }

    existing_result = await db.execute(
        select(PortalScanCache).where(
            PortalScanCache.user_id == user.id,
            PortalScanCache.board_type == scan.board_type,
            PortalScanCache.job_id == scan.job_id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.scan_result = scan_result_json
        existing.compensation_min = scan.compensation_min
        existing.compensation_max = scan.compensation_max
        existing.is_stale = False
        existing.last_accessed_at = datetime.now(tz=UTC)
        await db.commit()
        await db.refresh(existing)
        row = existing
    else:
        row = PortalScanCache(
            user_id=user.id,
            company_name=scan.company_name,
            job_id=scan.job_id,
            board_type=scan.board_type,
            job_url=scan.apply_url,
            compensation_min=scan.compensation_min,
            compensation_max=scan.compensation_max,
            scan_result=scan_result_json,
            schema_version=1,
            last_accessed_at=datetime.now(tz=UTC),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

    return PortalScanResponse(
        scan_id=row.id,
        cached=False,
        manual_entry=False,
        board_type=scan.board_type,
        title=scan.title,
        company=scan.company_name,
        location=scan.location,
        remote_policy=scan.remote_policy,
        compensation_min=scan.compensation_min,
        compensation_max=scan.compensation_max,
        requirements=scan.requirements,
        responsibilities=scan.responsibilities,
        apply_url=scan.apply_url,
        job_id=scan.job_id,
        schema_version=1,
    )
