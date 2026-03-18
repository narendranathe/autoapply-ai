"""
Vault sub-module: semantic retrieval and ATS scoring.
"""

import asyncio
import sys
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.resume import Resume
from app.models.user import User
from app.schemas.vault_batch import (
    BatchRetrieveRequest,
    BatchRetrieveResponse,
    BatchRetrieveResult,
)
from app.services.ats_service import score_resume

from ._shared import _ats_to_dict, _resume_to_dict


def _agent():
    """Late lookup so tests can patch app.routers.vault._retrieval_agent."""
    return sys.modules["app.routers.vault"]._retrieval_agent


router = APIRouter()


async def _single_retrieve(
    db: AsyncSession,
    user: "User",
    company: str,
    role: str,
    jd_snippet: str,
) -> BatchRetrieveResult:
    """
    Core retrieve logic for a single job card.
    Called by both the single /retrieve endpoint helper and batch_retrieve.
    Uses get_positioning_advice when jd_snippet is non-empty, otherwise falls back
    to retrieve_by_company (history-only).
    """
    if jd_snippet:
        advice = await _agent().get_positioning_advice(db, user.id, jd_snippet, company)
        ats_score = advice.ats_result.overall_score if advice.ats_result else None
        history_count = len(advice.company_history)
        best_resume_id = str(advice.best_resume.resume_id) if advice.best_resume else None
    else:
        history = await _agent().retrieve_by_company(db, user.id, company)
        ats_score = history[0].ats_score if history else None
        history_count = len(history)
        best_resume_id = str(history[0].resume_id) if history else None

    return BatchRetrieveResult(
        company=company,
        role=role,
        ats_score=ats_score,
        history_count=history_count,
        best_resume_id=best_resume_id,
    )


@router.post("/retrieve/batch")
async def batch_retrieve(
    request: BatchRetrieveRequest,
    db: AsyncSession = Depends(get_db),
    user: "User" = Depends(get_current_user),
) -> BatchRetrieveResponse:
    """
    Batch semantic retrieval — Issue #16.

    Accepts up to 50 job cards and returns one BatchRetrieveResult per card.
    All retrievals run in parallel via asyncio.gather(), reducing N serial
    network calls (Job Scout's O(N) pattern) to a single round-trip.

    Results are returned in the same order as the input jobs list.
    """
    if not request.jobs:
        return BatchRetrieveResponse(results=[])

    tasks = [
        _single_retrieve(db, user, job.company, job.role, job.jd_snippet) for job in request.jobs
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[BatchRetrieveResult] = []
    for i, item in enumerate(raw_results):
        if isinstance(item, BaseException):
            # Surface partial failures as a null result rather than aborting the whole batch
            logger.warning(f"batch_retrieve: job[{i}] ({request.jobs[i].company!r}) failed: {item}")
            results.append(
                BatchRetrieveResult(
                    company=request.jobs[i].company,
                    role=request.jobs[i].role,
                    ats_score=None,
                    history_count=0,
                    best_resume_id=None,
                )
            )
        else:
            results.append(item)

    return BatchRetrieveResponse(results=results)


@router.post("/retrieve")
async def retrieve_resumes(
    company_name: str = Form(...),
    jd_text: str | None = Form(None),
    top_k: int = Form(5),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Semantic retrieval: returns the most relevant resumes for a company + JD.

    - Company name alone → exact/fuzzy match on usage history
    - Company + JD text → TF-IDF similarity ranked results
    Returns positioning advice alongside the resume list.
    """

    if jd_text:
        advice = await _agent().get_positioning_advice(db, user.id, jd_text, company_name)
        return {
            "company_history": [_resume_to_dict(r) for r in advice.company_history],
            "jd_matches": [],  # embedded in advice.best_resume
            "best_match": _resume_to_dict(advice.best_resume) if advice.best_resume else None,
            "positioning_summary": advice.positioning_summary,
            "reuse_recommendation": advice.reuse_recommendation,
            "ats_result": _ats_to_dict(advice.ats_result) if advice.ats_result else None,
        }
    else:
        history = await _agent().retrieve_by_company(db, user.id, company_name)
        return {
            "company_history": [_resume_to_dict(r) for r in history],
            "best_match": _resume_to_dict(history[0]) if history else None,
            "positioning_summary": None,
            "reuse_recommendation": "generate_new" if not history else "tweak",
            "ats_result": None,
        }


# ── ATS Score ──────────────────────────────────────────────────────────────


@router.post("/ats-score")
async def ats_score(
    jd_text: str = Form(...),
    resume_id: str | None = Form(None),
    resume_text: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Score a resume against a job description.
    Provide either resume_id (to score a stored resume) or raw resume_text.
    """

    raw_text = resume_text
    if resume_id and not raw_text:
        result = await db.execute(
            select(Resume.raw_text).where(
                Resume.id == uuid.UUID(resume_id),
                Resume.user_id == user.id,
            )
        )
        raw_text = result.scalar_one_or_none()
        if not raw_text:
            raise HTTPException(status_code=404, detail="Resume not found or has no text content")

    if not raw_text:
        raise HTTPException(status_code=400, detail="Provide either resume_id or resume_text")

    ats = score_resume(jd_text, raw_text)
    return _ats_to_dict(ats)
