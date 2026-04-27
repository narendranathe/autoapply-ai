"""
Offer scoring service — 8-dimension A-F grader.

Vendored SIGNAL_TAXONOMY from story_service (single source in this repo).
"""

from __future__ import annotations

import hashlib
import re
import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.offer_evaluation import OfferEvaluation
from app.services.story_service import SIGNAL_TAXONOMY

# ---------------------------------------------------------------------------
# Dream company list — used for compensation fallback and brand prestige
# ---------------------------------------------------------------------------
_DREAM_COMPANIES = {
    "anthropic",
    "openai",
    "databricks",
    "snowflake",
    "goldman sachs",
    "google",
    "microsoft",
    "nvidia",
    "apple",
    "amazon",
    "meta",
    "netflix",
    "stripe",
    "citadel",
    "aqr",
    "two sigma",
    "hrt",
    "bloomberg",
    "jp morgan",
    "fidelity",
    "uber",
    "salesforce",
    "spotify",
    "doordash",
    "disney",
    "walmart",
}

# ---------------------------------------------------------------------------
# Dimension scoring functions
# ---------------------------------------------------------------------------


def _score_compensation(jd_text: str, company_name: str) -> float:
    salary_matches = re.findall(
        r"\$\s?(\d{2,3}(?:,\d{3})?)\s?[kK–\-]\s?\$?\s?(\d{2,3}(?:,\d{3})?)\s?[kK]?",
        jd_text,
    )
    if salary_matches:
        try:
            low_str, high_str = salary_matches[0]
            low = int(low_str.replace(",", ""))
            high = int(high_str.replace(",", ""))
            if low < 1000:
                low *= 1000
            if high < 1000:
                high *= 1000
            mid = (low + high) / 2
            target_low, target_high = 150_000, 220_000
            if mid >= target_low:
                return min(100.0, 70.0 + (mid - target_low) / (target_high - target_low) * 30)
            return max(0.0, 70.0 * mid / target_low)
        except Exception:
            pass
    if company_name.lower() in _DREAM_COMPANIES:
        return 70.0
    return 50.0


def _score_sponsorship_regex(jd_text: str, company_name: str) -> float:
    text = jd_text.lower()
    if any(
        phrase in text
        for phrase in [
            "must be authorized to work without sponsorship",
            "no sponsorship",
            "will not sponsor",
            "not able to sponsor",
        ]
    ):
        return 10.0
    if any(
        phrase in text
        for phrase in [
            "h1b",
            "h-1b",
            "visa sponsorship",
            "will sponsor",
            "sponsorship available",
            "work authorization provided",
        ]
    ):
        return 85.0
    if company_name.lower() in _DREAM_COMPANIES:
        return 50.0
    return 35.0


async def _score_sponsorship_llm(jd_text: str, company_name: str, api_key: str) -> float:
    from app.services.llm_gateway import _call_anthropic

    system = (
        "You are an H1B visa sponsorship classifier. "
        "Reply with ONE word: SPONSORS, SILENT, or NO_SPONSOR. "
        "SPONSORS = JD explicitly mentions H1B/visa sponsorship positively. "
        "SILENT = JD says nothing about sponsorship. "
        "NO_SPONSOR = JD explicitly says no sponsorship."
    )
    user = f"Company: {company_name}\n\nJob description:\n{jd_text[:2000]}"
    try:
        result = await _call_anthropic(system, user, api_key, model="claude-haiku-4-5-20251001")
        result = result.strip().upper()
        if "SPONSORS" in result:
            return 85.0
        if "NO_SPONSOR" in result:
            return 10.0
        return _score_sponsorship_regex(jd_text, company_name)
    except Exception as exc:
        logger.warning(f"[offer_scoring] LLM sponsorship failed: {exc} — using regex fallback")
        return _score_sponsorship_regex(jd_text, company_name)


def _score_tech_stack(jd_text: str) -> float:
    text = jd_text.lower()
    tech_categories = {k: v for k, v in SIGNAL_TAXONOMY.items() if k != "leadership_ownership"}
    matched = sum(1 for kws in tech_categories.values() for kw in kws if kw in text)
    total = sum(len(v) for v in tech_categories.values())
    return min(100.0, (matched / max(total, 1)) * 400)


def _score_growth_trajectory(jd_text: str) -> float:
    text = jd_text.lower()
    signals = ["senior", "staff", "lead", "principal", "architect", "director"]
    found = sum(1 for s in signals if s in text)
    return min(100.0, found * 25.0)


def _score_remote_flexibility(jd_text: str) -> float:
    text = jd_text.lower()
    if "fully remote" in text or "100% remote" in text:
        return 100.0
    if "remote" in text and "hybrid" not in text:
        return 85.0
    if "hybrid" in text:
        return 60.0
    if "on-site" in text or "onsite" in text or "in-office" in text:
        return 20.0
    return 50.0


def _score_brand_prestige(company_name: str) -> float:
    return 90.0 if company_name.lower() in _DREAM_COMPANIES else 50.0


def _score_interview_difficulty(jd_text: str) -> float:
    text = jd_text.lower()
    signals = ["leetcode", "system design", "take-home", "coding challenge", "onsite loop"]
    found = sum(1 for s in signals if s in text)
    return max(0.0, 80.0 - found * 20.0)


# ---------------------------------------------------------------------------
# Weights and grade thresholds
# ---------------------------------------------------------------------------
_WEIGHTS: dict[str, float] = {
    "role_match": 0.25,
    "compensation_fit": 0.18,
    "sponsorship_likelihood": 0.15,
    "tech_stack_fit": 0.15,
    "growth_trajectory": 0.10,
    "remote_flexibility": 0.08,
    "brand_prestige": 0.05,
    "interview_difficulty": 0.04,
}


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Main evaluation entry point
# ---------------------------------------------------------------------------
async def evaluate_offer(
    db: AsyncSession,
    user_id: uuid.UUID,
    jd_text: str,
    company_name: str,
    role_title: str,
    resume_id: uuid.UUID | None,
    api_key: str = "",
    refresh: bool = False,
) -> tuple[OfferEvaluation, bool]:
    """
    Score a job offer across 8 dimensions.
    Returns (evaluation, was_cached).
    """
    jd_hash = hashlib.sha256(jd_text.encode()).hexdigest()

    if not refresh:
        result = await db.execute(
            select(OfferEvaluation).where(
                OfferEvaluation.user_id == user_id,
                OfferEvaluation.jd_text_hash == jd_hash,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing, True

    # Resolve resume for role_match dimension
    effective_resume_id = resume_id
    if not effective_resume_id:
        from app.models.resume import Resume

        res = await db.execute(
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(Resume.created_at.desc())
            .limit(1)
        )
        default_resume = res.scalar_one_or_none()
        if default_resume:
            effective_resume_id = default_resume.id

    # role_match via standalone HTTP — degrade gracefully if unavailable
    role_match_score: float | None = None
    degraded: list[str] = []

    if effective_resume_id:
        import os

        import httpx

        from app.models.resume import Resume

        res = await db.execute(select(Resume).where(Resume.id == effective_resume_id))
        resume = res.scalar_one_or_none()
        resume_text = getattr(resume, "raw_text", None) or getattr(resume, "content", None) or ""

        if resume_text:
            standalone_url = os.getenv("STANDALONE_URL", "http://localhost:7000")
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        f"{standalone_url}/api/v1/resume/score",
                        json={"jd_text": jd_text, "resume_text": resume_text},
                    )
                    resp.raise_for_status()
                    role_match_score = resp.json().get("ats_score")
            except Exception as exc:
                logger.warning(f"[offer_eval] standalone unavailable: {exc}")
                degraded.append("role_match")

    # Score all formula dimensions
    sponsorship_score = (
        await _score_sponsorship_llm(jd_text, company_name, api_key)
        if api_key
        else _score_sponsorship_regex(jd_text, company_name)
    )

    dimensions: dict[str, dict] = {}
    active_weights = dict(_WEIGHTS)

    if role_match_score is not None:
        dimensions["role_match"] = {
            "score": round(role_match_score, 1),
            "weight": _WEIGHTS["role_match"],
            "label": "Strong" if role_match_score >= 70 else "Moderate",
        }
    else:
        active_weights.pop("role_match", None)
        dimensions["role_match"] = {
            "score": None,
            "weight": _WEIGHTS["role_match"],
            "label": "Unavailable",
        }

    dimensions.update(
        {
            "compensation_fit": {
                "score": round(_score_compensation(jd_text, company_name), 1),
                "weight": _WEIGHTS["compensation_fit"],
                "label": "",
            },
            "sponsorship_likelihood": {
                "score": round(sponsorship_score, 1),
                "weight": _WEIGHTS["sponsorship_likelihood"],
                "label": "Uncertain" if sponsorship_score < 70 else "Likely",
            },
            "tech_stack_fit": {
                "score": round(_score_tech_stack(jd_text), 1),
                "weight": _WEIGHTS["tech_stack_fit"],
                "label": "",
            },
            "growth_trajectory": {
                "score": round(_score_growth_trajectory(jd_text), 1),
                "weight": _WEIGHTS["growth_trajectory"],
                "label": "",
            },
            "remote_flexibility": {
                "score": round(_score_remote_flexibility(jd_text), 1),
                "weight": _WEIGHTS["remote_flexibility"],
                "label": "",
            },
            "brand_prestige": {
                "score": round(_score_brand_prestige(company_name), 1),
                "weight": _WEIGHTS["brand_prestige"],
                "label": "",
            },
            "interview_difficulty": {
                "score": round(_score_interview_difficulty(jd_text), 1),
                "weight": _WEIGHTS["interview_difficulty"],
                "label": "",
            },
        }
    )

    # Weighted average over available dimensions
    total_weight = sum(
        w for k, w in active_weights.items() if dimensions.get(k, {}).get("score") is not None
    )
    overall = 0.0
    if total_weight > 0:
        overall = (
            sum(
                dimensions[k]["score"] * w
                for k, w in active_weights.items()
                if dimensions.get(k, {}).get("score") is not None
            )
            / total_weight
        )

    grade = _grade(overall)

    sponsorship_note = ""
    if sponsorship_score < 50:
        sponsorship_note = " Low H1B signal — verify sponsorship before applying."
    recommendation = (
        f"Grade {grade} ({overall:.0f}/100). "
        f"Role: {role_title} at {company_name}.{sponsorship_note}"
    )

    # Upsert
    result = await db.execute(
        select(OfferEvaluation).where(
            OfferEvaluation.user_id == user_id,
            OfferEvaluation.jd_text_hash == jd_hash,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.dimension_scores = dimensions
        existing.overall_grade = grade
        existing.overall_score = round(overall, 1)
        existing.recommendation = recommendation
        existing.resume_id = effective_resume_id
        await db.commit()
        await db.refresh(existing)
        return existing, False

    evaluation = OfferEvaluation(
        user_id=user_id,
        resume_id=effective_resume_id,
        jd_text_hash=jd_hash,
        company_name=company_name,
        role_title=role_title,
        dimension_scores=dimensions,
        overall_grade=grade,
        overall_score=round(overall, 1),
        recommendation=recommendation,
    )
    db.add(evaluation)
    await db.commit()
    await db.refresh(evaluation)
    return evaluation, False
