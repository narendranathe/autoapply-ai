"""
Vault sub-module: company history and analytics.
"""

import sys

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.resume import ApplicationAnswer, Resume
from app.models.user import User

from ._shared import _resume_to_dict


def _agent():
    """Late lookup so tests can patch app.routers.vault._retrieval_agent."""
    return sys.modules["app.routers.vault"]._retrieval_agent


router = APIRouter()


# ── History ────────────────────────────────────────────────────────────────


@router.get("/history/{company_name}")
async def company_history(
    company_name: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """All resumes and answers ever used for a company — recruiter callback reference."""

    resumes = await _agent().retrieve_by_company(db, user.id, company_name)

    # Fetch saved answers for this company
    ans_stmt = (
        select(ApplicationAnswer)
        .where(
            ApplicationAnswer.user_id == user.id,
            ApplicationAnswer.company_name.ilike(f"%{company_name}%"),
        )
        .order_by(ApplicationAnswer.created_at.desc())
    )
    ans_result = await db.execute(ans_stmt)
    answers = ans_result.scalars().all()

    return {
        "company": company_name,
        "resumes": [_resume_to_dict(r) for r in resumes],
        "answers": [
            {
                "question_category": a.question_category,
                "question_text": a.question_text[:200],
                "answer_text": a.answer_text,
                "word_count": a.word_count,
                "saved_at": a.created_at.isoformat(),
                "role_title": a.role_title,
                "job_id": a.job_id,
            }
            for a in answers
        ],
    }


# ── Vault analytics ──────────────────────────────────────────────────────────


@router.get("/analytics")
async def get_vault_analytics(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Return per-user vault analytics:
    - Total answers saved and feedback distribution
    - Average reward score and per-category breakdown
    - Total resumes and unique companies served
    - Top companies by answer count
    """
    # ── Answers aggregate ──────────────────────────────────────────────────
    answers_stmt = select(ApplicationAnswer).where(ApplicationAnswer.user_id == user.id)
    all_answers = (await db.execute(answers_stmt)).scalars().all()

    total_answers = len(all_answers)
    feedback_dist: dict[str, int] = {}
    category_stats: dict[str, dict[str, float | int]] = {}
    reward_scores: list[float] = []
    companies: dict[str, int] = {}

    for a in all_answers:
        fb = a.feedback or "pending"
        feedback_dist[fb] = feedback_dist.get(fb, 0) + 1

        cat = a.question_category or "custom"
        if cat not in category_stats:
            category_stats[cat] = {"count": 0, "reward_sum": 0.0, "used_as_is": 0}
        category_stats[cat]["count"] = int(category_stats[cat]["count"]) + 1
        if a.reward_score is not None:
            category_stats[cat]["reward_sum"] = (
                float(category_stats[cat]["reward_sum"]) + a.reward_score
            )
            reward_scores.append(a.reward_score)
        if a.feedback == "used_as_is":
            category_stats[cat]["used_as_is"] = int(category_stats[cat]["used_as_is"]) + 1

        cname = a.company_name or "unknown"
        companies[cname] = companies.get(cname, 0) + 1

    avg_reward = sum(reward_scores) / len(reward_scores) if reward_scores else None

    # Build per-category avg reward
    category_breakdown = {
        cat: {
            "count": int(s["count"]),
            "avg_reward": (
                round(float(s["reward_sum"]) / int(s["count"]), 3) if int(s["count"]) else None
            ),
            "acceptance_rate": (
                round(int(s["used_as_is"]) / int(s["count"]), 3) if int(s["count"]) else None
            ),
        }
        for cat, s in category_stats.items()
    }

    top_companies = sorted(companies.items(), key=lambda x: x[1], reverse=True)[:10]

    # ── Resumes aggregate ─────────────────────────────────────────────────
    resumes_stmt = select(func.count(Resume.id)).where(Resume.user_id == user.id)
    total_resumes = (await db.execute(resumes_stmt)).scalar_one() or 0

    unique_companies_stmt = select(func.count(func.distinct(Resume.target_company))).where(
        Resume.user_id == user.id,
        Resume.target_company.isnot(None),
    )
    unique_companies = (await db.execute(unique_companies_stmt)).scalar_one() or 0

    return {
        "answers": {
            "total": total_answers,
            "avg_reward_score": round(avg_reward, 3) if avg_reward is not None else None,
            "feedback_distribution": feedback_dist,
            "by_category": category_breakdown,
        },
        "resumes": {
            "total": total_resumes,
            "unique_companies": unique_companies,
        },
        "top_companies_by_answers": [{"company": c, "answer_count": n} for c, n in top_companies],
    }
