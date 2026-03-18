"""
Vault sub-module: resume and content generation endpoints.
"""

import contextlib
import hashlib
import json as _json
import sys
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.resume import Resume
from app.models.user import User
from app.models.work_history import WorkHistoryEntry
from app.services.ats_service import ATSResult
from app.services.resume_generator import PersonalProfile

from ._shared import _github_service


def _score_resume():
    """Late lookup so tests can patch app.routers.vault.score_resume."""
    return sys.modules["app.routers.vault"].score_resume


def _build_tfidf_vector():
    """Late lookup so tests can patch app.routers.vault.build_tfidf_vector."""
    return sys.modules["app.routers.vault"].build_tfidf_vector


def _get_rag_context_for_query():
    """Late lookup so tests can patch app.routers.vault.get_rag_context_for_query."""
    return sys.modules["app.routers.vault"].get_rag_context_for_query


def _generate_full_latex_resume():
    """Late lookup so tests can patch app.routers.vault.generate_full_latex_resume."""
    return sys.modules["app.routers.vault"].generate_full_latex_resume


def _generate_cover_letter():
    """Late lookup so tests can patch app.routers.vault.generate_cover_letter."""
    return sys.modules["app.routers.vault"].generate_cover_letter


def _generate_professional_summary():
    """Late lookup so tests can patch app.routers.vault.generate_professional_summary."""
    return sys.modules["app.routers.vault"].generate_professional_summary


def _generate_role_bullets():
    """Late lookup so tests can patch app.routers.vault.generate_role_bullets."""
    return sys.modules["app.routers.vault"].generate_role_bullets


router = APIRouter()


# ── Generate full LaTeX resume ─────────────────────────────────────────────


@router.post("/generate")
async def generate_resume(
    company_name: str = Form(...),
    role_title: str = Form(...),
    jd_text: str = Form(...),
    job_id: str | None = Form(None),
    # Personal profile (injected by extension from private vault)
    name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    linkedin_url: str = Form(...),
    linkedin_label: str = Form(...),
    portfolio_url: str = Form(""),
    portfolio_label: str = Form(""),
    work_history_text: str = Form(...),
    education_text: str = Form(""),
    # LLM config
    llm_provider: str = Form("anthropic"),
    llm_api_key: str | None = Form(None),
    ollama_model: str = Form("llama3.1:8b"),
    # Base resume for ATS pre-scoring
    base_resume_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Generate a complete LaTeX resume tailored to the JD.

    Returns: latex_content, markdown_preview, version_tag, recruiter_filename,
             ats_score_estimate, skills_gap, changes_summary, llm_provider_used
    """

    # Pre-score with base resume if available
    ats_result: ATSResult | None = None
    if base_resume_id:
        res = await db.execute(
            select(Resume.raw_text).where(
                Resume.id == uuid.UUID(base_resume_id),
                Resume.user_id == user.id,
            )
        )
        raw = res.scalar_one_or_none()
        if raw:
            ats_result = _score_resume()(jd_text, raw)

    # Retrieve RAG context from uploaded documents
    rag_query = f"{role_title} {company_name} {jd_text[:500]}"
    rag_ctx = await _get_rag_context_for_query()(
        db=db,
        user_id=user.id,
        query=rag_query,
        doc_types=["resume", "work_history"],
        top_k=6,
        max_context_tokens=1500,
        label="CANDIDATE BACKGROUND (from uploaded resume/work history)",
    )

    profile = PersonalProfile(
        name=name,
        phone=phone,
        email=email,
        linkedin_url=linkedin_url,
        linkedin_label=linkedin_label,
        portfolio_url=portfolio_url,
        portfolio_label=portfolio_label,
        work_history_text=work_history_text,
        education_text=education_text,
    )

    generated = await _generate_full_latex_resume()(
        profile=profile,
        jd_text=jd_text,
        company_name=company_name,
        role_title=role_title,
        job_id=job_id,
        ats_result=ats_result,
        provider=llm_provider,
        api_key=llm_api_key or user.encrypted_llm_api_key or "",
        ollama_model=ollama_model,
        rag_context=rag_ctx,
    )

    # Store generated resume in vault
    tfidf = _build_tfidf_vector()(work_history_text)
    new_resume = Resume(
        user_id=user.id,
        filename=f"{generated.version_tag}.tex",
        file_type="tex",
        raw_text=work_history_text[:50000],
        latex_content=generated.latex_content,
        markdown_content=generated.markdown_preview,
        tfidf_vector=tfidf,
        version_tag=generated.version_tag,
        recruiter_filename=generated.recruiter_filename,
        is_generated=True,
        target_company=company_name,
        target_role=role_title,
        target_jd_hash=hashlib.sha256(jd_text.encode()).hexdigest(),
        ats_score=generated.ats_score_estimate,
    )
    db.add(new_resume)
    await db.commit()
    await db.refresh(new_resume)

    logger.info(f"Generated resume {generated.version_tag} for {company_name} / {role_title}")

    # Auto-commit to GitHub vault if token is configured
    github_path: str | None = None
    github_url: str | None = None
    if user.encrypted_github_token and user.github_username:
        try:
            gh_result = await _github_service.commit_named_resume(
                encrypted_token=user.encrypted_github_token,
                repo_full_name=f"{user.github_username}/{user.resume_repo_name or 'resume-vault'}",
                version_tag=generated.version_tag,
                tex_content=generated.latex_content,
                pdf_content=None,
                metadata={
                    "company": company_name,
                    "role": role_title,
                    "job_id": job_id,
                    "ats_score": generated.ats_score_estimate,
                    "skills_gap": generated.skills_gap,
                },
                job_id=job_id,
            )
            github_path = gh_result.get("versions_path")
            if github_path:
                new_resume.github_path = github_path
                new_resume.github_commit_sha = gh_result.get("versions_sha")
                await db.commit()
                github_url = (
                    f"https://github.com/{user.github_username}/"
                    f"{user.resume_repo_name or 'resume-vault'}/blob/main/{github_path}"
                )
                logger.info(f"Committed resume to GitHub: {github_path}")
        except Exception as e:
            logger.warning(f"GitHub commit failed for {generated.version_tag}: {e}")
    else:
        logger.debug(f"User {user.id} has no GitHub token; skipping vault commit")

    return {
        "resume_id": str(new_resume.id),
        "version_tag": generated.version_tag,
        "recruiter_filename": generated.recruiter_filename,
        "latex_content": generated.latex_content,
        "markdown_preview": generated.markdown_preview,
        "ats_score_estimate": generated.ats_score_estimate,
        "skills_gap": generated.skills_gap,
        "changes_summary": generated.changes_summary,
        "llm_provider_used": generated.llm_provider_used,
        "warnings": generated.generation_warnings,
        "github_path": github_path,
        "github_url": github_url,
    }


# ── Generate tailored resume (simplified — no personal profile needed) ─────


@router.post("/generate/tailored")
async def generate_tailored_resume(
    base_resume_id: str = Form(...),
    jd_text: str = Form(...),
    company_name: str = Form(...),
    role_title: str = Form(""),
    providers_json: str = Form(""),  # JSON: [{"name":"groq","api_key":"...","model":"..."}]
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Generate a tailored resume from a stored base resume.

    Simpler than /generate — caller does not need to provide personal profile fields.
    Uses the stored resume text + user's DB work history as the grounding context.

    Returns: markdown_preview, ats_score_before/after, skills_gap, changes_summary.
    Contact info (name/phone/email) appears as placeholders — user fills those in manually.
    """
    # Load the base resume
    res = await db.execute(
        select(Resume).where(
            Resume.id == uuid.UUID(base_resume_id),
            Resume.user_id == user.id,
        )
    )
    base_resume = res.scalar_one_or_none()
    if not base_resume:
        raise HTTPException(status_code=404, detail="Base resume not found in vault")

    # Auto-load structured work history from DB for richer grounding
    wh_stmt = (
        select(WorkHistoryEntry)
        .where(WorkHistoryEntry.user_id == user.id)
        .order_by(WorkHistoryEntry.sort_order, WorkHistoryEntry.created_at.desc())
    )
    wh_result = await db.execute(wh_stmt)
    wh_entries = list(wh_result.scalars().all())
    work_history_text = (
        "\n\n".join(e.to_text_block() for e in wh_entries)
        if wh_entries
        else (base_resume.raw_text or "")
    )

    # ATS score baseline (before tailoring)
    ats_before: ATSResult | None = None
    if base_resume.raw_text and jd_text:
        ats_before = _score_resume()(jd_text, base_resume.raw_text)

    # Build PersonalProfile with placeholder contact info — user will supply real values
    # when they download/compile the .tex output.  The important grounding is work_history_text.
    profile = PersonalProfile(
        name="[Your Name]",
        phone="[Phone]",
        email="[Email]",
        linkedin_url="[LinkedIn URL]",
        linkedin_label="LinkedIn",
        portfolio_url="",
        portfolio_label="",
        work_history_text=work_history_text,
        education_text="",
    )

    # Resolve provider — use first entry in providers_json, fallback to user's stored key
    providers_list: list[dict] = []
    if providers_json.strip():
        try:
            providers_list = _json.loads(providers_json)
        except Exception:
            logger.warning("generate/tailored: invalid providers_json — using fallback")

    provider = "anthropic"
    api_key = user.encrypted_llm_api_key or ""
    if providers_list:
        provider = providers_list[0].get("name", "anthropic")
        api_key = providers_list[0].get("api_key", "") or api_key

    generated = await _generate_full_latex_resume()(
        profile=profile,
        jd_text=jd_text,
        company_name=company_name,
        role_title=role_title,
        job_id=None,
        ats_result=ats_before,
        provider=provider,
        api_key=api_key,
        ollama_model="llama3.1:8b",
    )

    # Persist the generated resume in the vault
    tfidf = _build_tfidf_vector()(work_history_text)
    new_resume = Resume(
        user_id=user.id,
        filename=f"{generated.version_tag}.tex",
        file_type="tex",
        raw_text=work_history_text[:50000],
        latex_content=generated.latex_content,
        markdown_content=generated.markdown_preview,
        tfidf_vector=tfidf,
        version_tag=generated.version_tag,
        recruiter_filename=generated.recruiter_filename,
        is_generated=True,
        target_company=company_name,
        target_role=role_title,
        target_jd_hash=hashlib.sha256(jd_text.encode()).hexdigest(),
        ats_score=generated.ats_score_estimate,
    )
    db.add(new_resume)
    await db.commit()
    await db.refresh(new_resume)

    logger.info(
        f"Tailored resume {generated.version_tag} for {company_name} / {role_title} "
        f"(base={base_resume_id})"
    )

    return {
        "resume_id": str(new_resume.id),
        "version_tag": generated.version_tag,
        "markdown_preview": generated.markdown_preview,
        "ats_score_estimate": generated.ats_score_estimate,
        "ats_score_before": ats_before.overall_score if ats_before else None,
        "skills_gap": generated.skills_gap,
        "changes_summary": generated.changes_summary,
        "llm_provider_used": generated.llm_provider_used,
        "warnings": generated.generation_warnings,
    }


# ── Professional summary endpoint ──────────────────────────────────────────


@router.post("/generate/summary")
async def generate_summary_endpoint(
    company_name: str = Form(...),
    role_title: str = Form(""),
    jd_text: str = Form(""),
    word_limit: int = Form(80),
    candidate_name: str = Form(""),
    providers_json: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    Generate a 2-4 sentence professional summary tailored to a role.
    Returns {summary, provider_used, word_count}.
    """
    providers_list: list[dict] = []
    with contextlib.suppress(Exception):
        if providers_json.strip():
            providers_list = _json.loads(providers_json)

    from app.models.work_history import WorkHistoryEntry as WHModel

    wh_rows = (
        (
            await db.execute(
                select(WHModel).where(WHModel.user_id == user.id).order_by(WHModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    work_history_text = "\n\n".join(
        f"{r.role_title} at {r.company_name} ({r.start_date} – {r.end_date or 'present'})\n"
        + "\n".join(f"• {b}" for b in (r.bullets or []))
        for r in wh_rows
    )

    summary, provider_used = await _generate_professional_summary()(
        company_name=company_name,
        role_title=role_title,
        jd_text=jd_text,
        work_history_text=work_history_text,
        providers=providers_list,
        candidate_name=candidate_name,
        word_limit=min(max(40, word_limit), 200),
    )

    return {
        "summary": summary,
        "provider_used": provider_used,
        "word_count": len(summary.split()),
    }


# ── Tailored bullets endpoint ────────────────────────────────────────────────


@router.post("/generate/bullets")
async def generate_bullets_endpoint(
    company_name: str = Form(...),
    role_title: str = Form(""),
    jd_text: str = Form(""),
    num_bullets: int = Form(5),
    target_company_for_context: str = Form(""),
    providers_json: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    Generate ATS-optimized bullet points for a specific role, grounded in work history.
    Returns {bullets, provider_used, count}.
    """
    providers_list: list[dict] = []
    with contextlib.suppress(Exception):
        if providers_json.strip():
            providers_list = _json.loads(providers_json)

    from app.models.work_history import WorkHistoryEntry as WHModel

    wh_rows = (
        (
            await db.execute(
                select(WHModel).where(WHModel.user_id == user.id).order_by(WHModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    work_history_text = "\n\n".join(
        f"{r.role_title} at {r.company_name} ({r.start_date} – {r.end_date or 'present'})\n"
        + "\n".join(f"• {b}" for b in (r.bullets or []))
        for r in wh_rows
    )

    bullets, provider_used = await _generate_role_bullets()(
        company_name=company_name,
        role_title=role_title,
        jd_text=jd_text,
        work_history_text=work_history_text,
        providers=providers_list,
        num_bullets=min(max(1, num_bullets), 10),
        target_company_for_context=target_company_for_context,
    )

    return {
        "bullets": bullets,
        "provider_used": provider_used,
        "count": len(bullets),
    }


# ── Dedicated cover letter endpoint ─────────────────────────────────────────


@router.post("/generate/cover-letter")
async def generate_cover_letter_endpoint(
    company_name: str = Form(...),
    role_title: str = Form(""),
    jd_text: str = Form(""),
    tone: str = Form("professional"),  # professional|enthusiastic|concise|conversational
    word_limit: int = Form(400),
    candidate_name: str = Form(""),
    providers_json: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    Generate cover letter drafts — one per enabled LLM provider, run in parallel.
    Accepts tone and word_limit controls. Returns up to N drafts (one per provider).
    """
    providers_list: list[dict] = []
    with contextlib.suppress(Exception):
        if providers_json.strip():
            providers_list = _json.loads(providers_json)

    # Load candidate work history
    from app.models.work_history import WorkHistoryEntry as WHModel  # local import avoids circular

    wh_rows = (
        (
            await db.execute(
                select(WHModel).where(WHModel.user_id == user.id).order_by(WHModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    work_history_text = "\n\n".join(
        f"{r.role_title} at {r.company_name} ({r.start_date} – {r.end_date or 'present'})\n"
        + "\n".join(f"• {b}" for b in (r.bullets or []))
        for r in wh_rows
    )

    # Retrieve past accepted cover letters for style memory
    from app.models.resume import ApplicationAnswer

    stmt = (
        select(ApplicationAnswer)
        .where(
            ApplicationAnswer.user_id == user.id,
            ApplicationAnswer.question_category == "cover_letter",
            ApplicationAnswer.reward_score >= 0.7,
        )
        .order_by(ApplicationAnswer.reward_score.desc())
        .limit(2)
    )
    past = (await db.execute(stmt)).scalars().all()
    past_accepted = [p.answer_text for p in past]

    # candidate_name already received from form

    # Retrieve RAG context from uploaded documents
    rag_query = f"{role_title} {company_name} {jd_text[:500]}"
    rag_ctx = await _get_rag_context_for_query()(
        db=db,
        user_id=user.id,
        query=rag_query,
        doc_types=["resume", "work_history"],
        top_k=6,
        max_context_tokens=1500,
        label="CANDIDATE BACKGROUND (from uploaded resume/work history)",
    )

    drafts, draft_providers = await _generate_cover_letter()(
        company_name=company_name,
        role_title=role_title,
        jd_text=jd_text,
        work_history_text=work_history_text,
        providers=providers_list,
        candidate_name=candidate_name,
        tone=tone,
        word_limit=min(max(150, word_limit), 800),
        past_accepted=past_accepted or None,
        rag_context=rag_ctx,
    )

    return {
        "drafts": drafts,
        "draft_providers": draft_providers,
        "tone": tone,
        "word_limit": word_limit,
    }
