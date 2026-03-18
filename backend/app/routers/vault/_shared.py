"""
Shared helpers and singletons used across vault sub-modules.
"""

import json as _json

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.ats_service import ATSResult
from app.services.github_service import GitHubService
from app.services.resume_parser import ResumeParser
from app.services.retrieval_agent import ResumeWithScore, RetrievalAgent

# ── Singletons ─────────────────────────────────────────────────────────────

_retrieval_agent = RetrievalAgent()
_resume_parser = ResumeParser()
_github_service = GitHubService()


# ── Provider resolution ────────────────────────────────────────────────────


async def _resolve_providers(
    providers_json: str,
    db: "AsyncSession",
    user: "User",
) -> list[dict]:
    """
    Resolve the provider list for a generation endpoint.

    Priority:
    1. providers_json from request body (client-configured, backward-compat)
    2. Server-side UserProviderConfig rows (if providers_json is empty)
    3. Empty list → keyword fallback handled downstream

    This implements issue #25: server-side provider authority.
    """
    from sqlalchemy import select

    from app.models.user_provider_config import UserProviderConfig
    from app.utils.encryption import decrypt_value

    if providers_json.strip():
        try:
            return _json.loads(providers_json)  # type: ignore[return-value]
        except Exception:
            logger.warning("Invalid providers_json — falling back to server-side config")

    # Read from server-side storage
    result = await db.execute(
        select(UserProviderConfig)
        .where(
            UserProviderConfig.user_id == user.id,
            UserProviderConfig.is_enabled.is_(True),
        )
        .order_by(UserProviderConfig.provider_name)
    )
    rows = result.scalars().all()
    providers = []
    for row in rows:
        try:
            api_key = decrypt_value(row.encrypted_api_key) if row.encrypted_api_key else ""
        except Exception:
            api_key = ""
        if api_key:
            providers.append(
                {"name": row.provider_name, "api_key": api_key, "model": row.model_override or ""}
            )
    return providers


# ── Serialisation helpers ──────────────────────────────────────────────────


def _resume_to_dict(r: ResumeWithScore | None) -> dict | None:
    if r is None:
        return None
    return {
        "resume_id": str(r.resume_id),
        "version_tag": r.version_tag,
        "filename": r.filename,
        "file_type": r.file_type,
        "target_company": r.target_company,
        "target_role": r.target_role,
        "ats_score": r.ats_score,
        "similarity_score": r.similarity_score,
        "last_used": r.last_used,
        "outcomes": r.usage_outcomes,
        "github_path": r.github_path,
    }


def _ats_to_dict(r: ATSResult) -> dict:
    return {
        "overall_score": r.overall_score,
        "keyword_coverage": round(r.keyword_coverage * 100, 1),
        "skills_present": r.skills_present,
        "skills_gap": r.skills_gap,
        "quantification_score": round(r.quantification_score * 100, 1),
        "experience_alignment": round(r.experience_alignment * 100, 1),
        "mq_coverage": round(r.mq_coverage * 100, 1),
        "suggestions": r.suggestions,
        "total_jd_keywords": r.total_jd_keywords,
        "matched_keywords": r.matched_keywords,
    }
