"""
Semantic Retrieval Agent — finds the right resume for any company/JD.

Three retrieval modes:
  1. retrieve_by_company  — exact + fuzzy company name match on resume_usages
  2. retrieve_by_jd       — TF-IDF / dense cosine similarity across all user resumes
  3. get_positioning_advice — combines both + ATS scoring + suggestions

Tier selection mirrors the embedding service:
  Free:  TF-IDF (always available)
  Paid:  dense vectors (if stored on the Resume row)
  Local: Ollama (if dense vectors were generated via Ollama)
"""

import hashlib
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resume import ApplicationAnswer, Resume, ResumeUsage
from app.services.ats_service import ATSResult, score_resume
from app.services.embedding_service import (
    build_tfidf_vector,
    cosine_similarity_tfidf,
)

# ── Data transfer objects ──────────────────────────────────────────────────


@dataclass
class ResumeWithScore:
    resume_id: uuid.UUID
    version_tag: str | None
    filename: str
    file_type: str
    target_company: str | None
    target_role: str | None
    ats_score: float | None
    similarity_score: float  # 0.0–1.0 — how close to the query
    last_used: str | None  # ISO date string of most recent usage
    usage_outcomes: list[str] = field(default_factory=list)
    github_path: str | None = None
    latex_content: str | None = None


@dataclass
class PositioningAdvice:
    best_resume: ResumeWithScore | None
    company_history: list[ResumeWithScore]  # all resumes used for this company
    ats_result: ATSResult | None
    positioning_summary: str  # human-readable paragraph
    reuse_recommendation: str  # "reuse" | "tweak" | "generate_new"


# ── Fuzzy company name matching ────────────────────────────────────────────


def _levenshtein(s1: str, s2: str) -> int:
    """Simple Levenshtein distance for fuzzy company name matching."""
    m, n = len(s1), len(s2)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if s1[i - 1] == s2[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def _company_matches(stored: str, query: str, threshold: int = 3) -> bool:
    """
    True if stored company name is close enough to the query.
    Handles short names (GS ≈ Goldman Sachs) via token matching too.
    """
    s, q = stored.lower().strip(), query.lower().strip()
    if s == q:
        return True
    if s in q or q in s:
        return True
    # Abbreviation match: "Goldman Sachs" vs "GS"
    initials = "".join(w[0] for w in s.split() if w)
    if initials == q or q == initials:
        return True
    # Levenshtein for typos / short variations
    return _levenshtein(s, q) <= threshold


# ── Core retrieval methods ─────────────────────────────────────────────────


class RetrievalAgent:
    """
    Retrieves the most relevant resume(s) from the user's vault
    given a company name or job description text.
    """

    async def retrieve_by_company(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        company_name: str,
        limit: int = 10,
    ) -> list[ResumeWithScore]:
        """
        Find all resumes ever used for a company.
        Returns ranked by (recency DESC, ats_score DESC).
        """
        # Fetch all usages for this user
        stmt = (
            select(ResumeUsage)
            .where(ResumeUsage.user_id == user_id)
            .order_by(ResumeUsage.created_at.desc())
        )
        result = await db.execute(stmt)
        all_usages: list[ResumeUsage] = list(result.scalars().all())

        # Filter by fuzzy company name match
        matched_usages = [u for u in all_usages if _company_matches(u.company_name, company_name)]

        if not matched_usages:
            return []

        # Collect unique resume IDs, preserving order
        seen_ids: set[uuid.UUID] = set()
        ordered_resume_ids: list[uuid.UUID] = []
        usage_map: dict[uuid.UUID, list[ResumeUsage]] = {}
        for usage in matched_usages:
            if usage.resume_id not in seen_ids:
                seen_ids.add(usage.resume_id)
                ordered_resume_ids.append(usage.resume_id)
            usage_map.setdefault(usage.resume_id, []).append(usage)

        # Fetch resume rows
        resume_stmt = select(Resume).where(
            Resume.id.in_(ordered_resume_ids),
            Resume.user_id == user_id,
        )
        resume_result = await db.execute(resume_stmt)
        resumes: dict[uuid.UUID, Resume] = {r.id: r for r in resume_result.scalars().all()}

        scores: list[ResumeWithScore] = []
        for rid in ordered_resume_ids[:limit]:
            r = resumes.get(rid)
            if not r:
                continue
            usages_for_r = usage_map.get(rid, [])
            last_usage = usages_for_r[0] if usages_for_r else None
            outcomes = [u.outcome for u in usages_for_r if u.outcome != "unknown"]

            scores.append(
                ResumeWithScore(
                    resume_id=r.id,
                    version_tag=r.version_tag,
                    filename=r.filename,
                    file_type=r.file_type,
                    target_company=r.target_company,
                    target_role=r.target_role,
                    ats_score=r.ats_score,
                    similarity_score=1.0,  # exact/fuzzy company match = full relevance
                    last_used=last_usage.created_at.isoformat() if last_usage else None,
                    usage_outcomes=outcomes,
                    github_path=r.github_path,
                    latex_content=r.latex_content,
                )
            )

        return scores

    async def retrieve_by_jd(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        jd_text: str,
        top_k: int = 5,
    ) -> list[ResumeWithScore]:
        """
        Find the top-k most semantically similar resumes to the given JD text.

        Similarity is computed using:
        - Dense cosine similarity if embedding_vector is stored on the resume
        - TF-IDF cosine similarity as fallback
        """
        # Build query vector from JD text
        query_tfidf = build_tfidf_vector(jd_text)

        # Fetch all resumes for this user
        stmt = select(Resume).where(Resume.user_id == user_id)
        result = await db.execute(stmt)
        all_resumes: list[Resume] = list(result.scalars().all())

        if not all_resumes:
            return []

        scored: list[tuple[float, Resume]] = []
        for r in all_resumes:
            if not r.raw_text and not r.tfidf_vector:
                continue

            # Try dense first
            if r.embedding_vector:
                # We can't embed the JD without an async API call here;
                # use TF-IDF for now. Dense re-ranking is done in the router
                # when the user has an embedding-capable provider configured.
                sim = cosine_similarity_tfidf(query_tfidf, r.tfidf_vector or {})
            elif r.tfidf_vector:
                sim = cosine_similarity_tfidf(query_tfidf, r.tfidf_vector)
            else:
                # Build TF-IDF on the fly from raw_text
                resume_tfidf = build_tfidf_vector(r.raw_text or "")
                sim = cosine_similarity_tfidf(query_tfidf, resume_tfidf)

            scored.append((sim, r))

        # Sort descending by similarity
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        # Fetch most recent usage for each
        results: list[ResumeWithScore] = []
        for sim_score, r in top:
            usage_stmt = (
                select(ResumeUsage)
                .where(
                    ResumeUsage.resume_id == r.id,
                    ResumeUsage.user_id == user_id,
                )
                .order_by(ResumeUsage.created_at.desc())
                .limit(5)
            )
            usage_result = await db.execute(usage_stmt)
            usages = usage_result.scalars().all()
            outcomes = [u.outcome for u in usages if u.outcome != "unknown"]

            results.append(
                ResumeWithScore(
                    resume_id=r.id,
                    version_tag=r.version_tag,
                    filename=r.filename,
                    file_type=r.file_type,
                    target_company=r.target_company,
                    target_role=r.target_role,
                    ats_score=r.ats_score,
                    similarity_score=round(sim_score, 4),
                    last_used=usages[0].created_at.isoformat() if usages else None,
                    usage_outcomes=outcomes,
                    github_path=r.github_path,
                    latex_content=r.latex_content,
                )
            )

        return results

    async def get_positioning_advice(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        jd_text: str,
        company_name: str,
        role_title: str = "",
    ) -> PositioningAdvice:
        """
        Full positioning analysis:
        1. Company history (all past resumes for this company)
        2. JD similarity (top-3 semantic matches)
        3. ATS score on best matching resume
        4. Reuse recommendation
        5. Human-readable positioning summary
        """
        company_history = await self.retrieve_by_company(db, user_id, company_name)
        jd_matches = await self.retrieve_by_jd(db, user_id, jd_text, top_k=3)

        # Best candidate: company history first (exact match trumps JD similarity)
        best: ResumeWithScore | None = None
        if company_history:
            best = company_history[0]
        elif jd_matches:
            best = jd_matches[0]

        # ATS score against best resume
        ats_result: ATSResult | None = None
        if best:
            stmt = select(Resume.raw_text).where(Resume.id == best.resume_id)
            res = await db.execute(stmt)
            raw_text = res.scalar_one_or_none()
            if raw_text:
                ats_result = score_resume(jd_text, raw_text)

        # Reuse recommendation
        reuse_rec = _reuse_recommendation(best, ats_result)

        # Positioning summary
        summary = _build_positioning_summary(
            company_name, role_title, company_history, jd_matches, ats_result, reuse_rec
        )

        return PositioningAdvice(
            best_resume=best,
            company_history=company_history,
            ats_result=ats_result,
            positioning_summary=summary,
            reuse_recommendation=reuse_rec,
        )

    async def get_previous_answer(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        question_text: str,
        company_name: str,
    ) -> ApplicationAnswer | None:
        """
        Look up a previously accepted answer for the same question at the same company.
        Uses SHA-256 of the normalised question for deduplication.
        """
        q_hash = _hash_question(question_text)
        stmt = (
            select(ApplicationAnswer)
            .where(
                ApplicationAnswer.user_id == user_id,
                ApplicationAnswer.question_hash == q_hash,
                ApplicationAnswer.company_name.ilike(f"%{company_name}%"),
            )
            .order_by(ApplicationAnswer.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_best_answers_for_question(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        question_text: str,
        question_category: str,
        top_k: int = 5,
    ) -> list[tuple[float, ApplicationAnswer]]:
        """
        Find the best historical answers for this question category.

        Ranking = reward_score * 0.7  +  tfidf_similarity(question_text) * 0.3
        Falls back to recency when no feedback exists yet.
        Only returns answers with feedback != "skipped" and != "regenerated".
        """
        # Pull all category answers (limit 50 for TF-IDF scoring)
        stmt = (
            select(ApplicationAnswer)
            .where(
                ApplicationAnswer.user_id == user_id,
                ApplicationAnswer.question_category == question_category,
                ApplicationAnswer.feedback.notin_(["skipped", "regenerated"]),
            )
            .order_by(
                ApplicationAnswer.reward_score.desc().nulls_last(),
                ApplicationAnswer.created_at.desc(),
            )
            .limit(50)
        )
        result = await db.execute(stmt)
        candidates: list[ApplicationAnswer] = list(result.scalars().all())

        if not candidates:
            return []

        # Score each candidate: reward * 0.7 + tfidf_sim * 0.3
        q_vec = build_tfidf_vector(question_text)
        scored: list[tuple[float, ApplicationAnswer]] = []
        for ans in candidates:
            reward = ans.reward_score if ans.reward_score is not None else 0.5
            sim = cosine_similarity_tfidf(q_vec, build_tfidf_vector(ans.question_text))
            composite = reward * 0.7 + sim * 0.3
            scored.append((composite, ans))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]


# ── Helpers ────────────────────────────────────────────────────────────────


def _hash_question(text: str) -> str:
    """SHA-256 of normalised question text (lowercase, collapsed whitespace)."""
    normalised = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(normalised.encode()).hexdigest()


def _reuse_recommendation(best: ResumeWithScore | None, ats: ATSResult | None) -> str:
    """
    Decide whether to reuse, tweak, or generate a new resume.

    Mirrors the similarity thresholds in the existing tailoring pipeline:
      >85% similarity → reuse
      60-85%          → tweak
      <60%            → generate_new
    """
    if best is None:
        return "generate_new"
    if ats is None:
        return "tweak"

    score = ats.overall_score
    if score >= 85:
        return "reuse"
    elif score >= 60:
        return "tweak"
    return "generate_new"


def _build_positioning_summary(
    company_name: str,
    role_title: str,
    company_history: list[ResumeWithScore],
    jd_matches: list[ResumeWithScore],
    ats: ATSResult | None,
    recommendation: str,
) -> str:
    parts: list[str] = []

    if company_history:
        outcomes = [o for r in company_history for o in r.usage_outcomes]
        outcome_str = f"Previous outcomes: {', '.join(set(outcomes))}." if outcomes else ""
        parts.append(
            f"You have applied to {company_name} {len(company_history)} time(s) before. "
            + outcome_str
        )
    else:
        parts.append(f"This is your first application to {company_name}.")

    if ats:
        parts.append(
            f"Your best matching resume scores {ats.overall_score:.0f}/100 against this JD "
            f"(keyword coverage: {ats.keyword_coverage * 100:.0f}%, "
            f"quantification: {ats.quantification_score * 100:.0f}%)."
        )
        if ats.skills_gap:
            top_gaps = ats.skills_gap[:4]
            parts.append(f"Skills in JD not in your resume: {', '.join(top_gaps)}.")

    rec_text = {
        "reuse": "Recommendation: your existing resume is a strong match — reuse with minor edits.",
        "tweak": "Recommendation: tweak your resume to better align with this JD's vocabulary.",
        "generate_new": "Recommendation: generate a freshly tailored resume for this role.",
    }
    parts.append(rec_text.get(recommendation, ""))

    return " ".join(p for p in parts if p)
