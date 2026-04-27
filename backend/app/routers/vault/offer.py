"""Vault sub-module: offer evaluation endpoint."""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User

router = APIRouter()


class OfferEvaluateRequest(BaseModel):
    jd_text: str = ""
    company_name: str
    role_title: str
    resume_id: uuid.UUID | None = None
    portal_scan_id: uuid.UUID | None = None


class DimensionOut(BaseModel):
    score: float | None
    weight: float
    label: str


class OfferEvaluateResponse(BaseModel):
    evaluation_id: uuid.UUID
    cached: bool
    grade: str
    overall_score: float
    recommendation: str
    degraded_dimensions: list[str]
    dimensions: dict[str, DimensionOut]

    model_config = {"from_attributes": True}


@router.post("/offer/evaluate", response_model=OfferEvaluateResponse)
async def evaluate_offer(
    body: OfferEvaluateRequest,
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.offer_scoring_service import evaluate_offer as _evaluate

    jd_text = body.jd_text

    # Resolve jd_text from portal scan if portal_scan_id provided and jd_text empty
    if body.portal_scan_id and not jd_text:
        try:
            from sqlalchemy import select

            from app.models.portal_scan import PortalScanCache

            scan_res = await db.execute(
                select(PortalScanCache).where(
                    PortalScanCache.id == body.portal_scan_id,
                    PortalScanCache.user_id == user.id,
                )
            )
            scan = scan_res.scalar_one_or_none()
            if scan:
                scan_result = scan.scan_result or {}
                requirements = scan_result.get("requirements", [])
                responsibilities = scan_result.get("responsibilities", [])
                jd_text = "\n".join(requirements + responsibilities)
        except Exception:
            pass

    # Get user's Anthropic key for LLM-based sponsorship scoring
    api_key = ""
    try:
        from sqlalchemy import select

        from app.models.user_provider_config import UserProviderConfig
        from app.utils.encryption import decrypt_value

        key_res = await db.execute(
            select(UserProviderConfig).where(
                UserProviderConfig.user_id == user.id,
                UserProviderConfig.provider_name == "anthropic",
                UserProviderConfig.is_enabled.is_(True),
            )
        )
        cfg = key_res.scalar_one_or_none()
        if cfg and cfg.encrypted_api_key:
            api_key = decrypt_value(cfg.encrypted_api_key)
    except Exception:
        pass

    evaluation, cached = await _evaluate(
        db=db,
        user_id=user.id,
        jd_text=jd_text,
        company_name=body.company_name,
        role_title=body.role_title,
        resume_id=body.resume_id,
        api_key=api_key,
        refresh=refresh,
    )

    degraded = [k for k, v in evaluation.dimension_scores.items() if v.get("score") is None]

    return OfferEvaluateResponse(
        evaluation_id=evaluation.id,
        cached=cached,
        grade=evaluation.overall_grade,
        overall_score=evaluation.overall_score,
        recommendation=evaluation.recommendation,
        degraded_dimensions=degraded,
        dimensions={k: DimensionOut(**v) for k, v in evaluation.dimension_scores.items()},
    )
