"""
Vault Router — Resume vault CRUD, semantic retrieval, ATS scoring, and resume generation.

Endpoints:
  POST   /api/v1/vault/upload                   Upload resume file → parse → embed → store
  GET    /api/v1/vault/resumes                  List all user resumes (paginated)
  DELETE /api/v1/vault/resumes/{id}             Delete a resume
  POST   /api/v1/vault/retrieve                 Semantic retrieval by company + optional JD
  POST   /api/v1/vault/ats-score                Score a stored resume against a JD
  POST   /api/v1/vault/generate                 Generate full LaTeX resume
  POST   /api/v1/vault/generate/summary         Generate professional summary only
  POST   /api/v1/vault/generate/bullets         Generate tailored bullets only
  POST   /api/v1/vault/generate/answers         Generate open-ended Q&A drafts
  GET    /api/v1/vault/history/{company}        All resumes ever used for a company
  GET    /api/v1/vault/answers/{company}        Previously saved answers for a company
  POST   /api/v1/vault/answers/save             Save accepted answer to DB
  PATCH  /api/v1/vault/answers/{id}/feedback    Record outcome (RL reward signal)
  GET    /api/v1/vault/answers/similar          Best past answers for a question (bandit policy)
  GET    /api/v1/vault/github/versions          List versions/ directory on GitHub
"""

import contextlib
import hashlib
import json as _json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.resume import ApplicationAnswer, Resume
from app.models.user import User
from app.models.work_history import WorkHistoryEntry
from app.services.ats_service import ATSResult, score_resume
from app.services.embedding_service import build_tfidf_vector
from app.services.github_service import GitHubService
from app.services.resume_generator import (
    _PROVIDER_RANK,
    PersonalProfile,
    _call_anthropic,
    _call_gemini,
    _call_groq,
    _call_kimi,
    _call_openai,
    generate_answer_drafts,
    generate_answer_drafts_cascade,
    generate_answer_drafts_parallel,
    generate_cover_letter,
    generate_full_latex_resume,
)
from app.services.resume_parser import ResumeParser
from app.services.retrieval_agent import ResumeWithScore, RetrievalAgent

router = APIRouter()
_retrieval_agent = RetrievalAgent()
_resume_parser = ResumeParser()
_github_service = GitHubService()


# ── Upload ─────────────────────────────────────────────────────────────────


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    version_tag: str | None = Form(None),
    target_company: str | None = Form(None),
    target_role: str | None = Form(None),
    is_base_template: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Upload a resume file (PDF, DOCX, or .tex) to the vault.

    Parses content, builds TF-IDF vector, stores in DB.
    Personal data stored here is for retrieval/ATS only — canonical source
    is the user's private GitHub vault.
    """

    file_bytes = await file.read()
    filename = file.filename or "resume"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"

    if ext not in {"pdf", "docx", "tex", "txt"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {ext}. Supported: pdf, docx, tex, txt",
        )

    # Parse content
    raw_text = ""
    latex_content = None
    parse_result = None

    try:
        if ext == "pdf":
            parse_result = _resume_parser.parse_pdf(file_bytes)
        elif ext == "docx":
            parse_result = _resume_parser.parse_docx(file_bytes)
        elif ext == "tex":
            raw_text = file_bytes.decode("utf-8", errors="replace")
            latex_content = raw_text
        else:
            raw_text = file_bytes.decode("utf-8", errors="replace")

        if parse_result:
            raw_text = " ".join(b.text for b in parse_result.bullets)
    except Exception as e:
        logger.warning(f"Parse error for {filename}: {e}")
        raw_text = file_bytes.decode("utf-8", errors="replace")

    # Build TF-IDF vector
    tfidf_vec = build_tfidf_vector(raw_text) if raw_text else {}

    # Extract structured data from parse result
    skills = list(parse_result.skills) if parse_result else []
    companies = list(parse_result.companies) if parse_result else []
    bullet_count = len(parse_result.bullets) if parse_result else 0

    # Compute ATS score if we have a target company/role context
    ats_score_val = None

    # Build resume row
    resume = Resume(
        user_id=user.id,
        filename=filename,
        file_type=ext,
        raw_text=raw_text[:50000],  # cap at 50K chars
        latex_content=latex_content,
        bullet_count=bullet_count,
        skills_detected=skills,
        companies_found=companies,
        tfidf_vector=tfidf_vec,
        version_tag=version_tag,
        recruiter_filename=f"{user.email_hash[:8]}.pdf",  # placeholder; overridden on generate
        is_base_template=is_base_template,
        is_generated=False,
        target_company=target_company,
        target_role=target_role,
        ats_score=ats_score_val,
    )

    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    logger.info(f"Uploaded resume {filename} for user {user.id} (id={resume.id})")

    return {
        "resume_id": str(resume.id),
        "filename": filename,
        "file_type": ext,
        "bullet_count": bullet_count,
        "skills_detected": skills[:10],
        "version_tag": version_tag,
        "parse_warnings": parse_result.parse_warnings if parse_result else [],
    }


# ── List ───────────────────────────────────────────────────────────────────


@router.get("/resumes")
async def list_resumes(
    page: int = 1,
    per_page: int = 20,
    company: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all resumes in the user's vault, newest first."""

    stmt = select(Resume).where(Resume.user_id == user.id)
    if company:
        stmt = stmt.where(Resume.target_company.ilike(f"%{company}%"))
    stmt = stmt.order_by(Resume.created_at.desc()).offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(stmt)
    resumes = result.scalars().all()

    return {
        "items": [
            {
                "resume_id": str(r.id),
                "filename": r.filename,
                "version_tag": r.version_tag,
                "target_company": r.target_company,
                "target_role": r.target_role,
                "ats_score": r.ats_score,
                "bullet_count": r.bullet_count,
                "is_base_template": r.is_base_template,
                "is_generated": r.is_generated,
                "github_path": r.github_path,
                "created_at": r.created_at.isoformat(),
            }
            for r in resumes
        ],
        "page": page,
        "per_page": per_page,
    }


# ── Delete ─────────────────────────────────────────────────────────────────


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    await db.delete(resume)
    await db.commit()


# ── Retrieve ───────────────────────────────────────────────────────────────


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
        advice = await _retrieval_agent.get_positioning_advice(db, user.id, jd_text, company_name)
        return {
            "company_history": [_resume_to_dict(r) for r in advice.company_history],
            "jd_matches": [],  # embedded in advice.best_resume
            "best_match": _resume_to_dict(advice.best_resume) if advice.best_resume else None,
            "positioning_summary": advice.positioning_summary,
            "reuse_recommendation": advice.reuse_recommendation,
            "ats_result": _ats_to_dict(advice.ats_result) if advice.ats_result else None,
        }
    else:
        history = await _retrieval_agent.retrieve_by_company(db, user.id, company_name)
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


# ── Generate ───────────────────────────────────────────────────────────────


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
            ats_result = score_resume(jd_text, raw)

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

    generated = await generate_full_latex_resume(
        profile=profile,
        jd_text=jd_text,
        company_name=company_name,
        role_title=role_title,
        job_id=job_id,
        ats_result=ats_result,
        provider=llm_provider,
        api_key=llm_api_key or user.encrypted_llm_api_key or "",
        ollama_model=ollama_model,
    )

    # Store generated resume in vault
    tfidf = build_tfidf_vector(work_history_text)
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
        ats_before = score_resume(jd_text, base_resume.raw_text)

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

    generated = await generate_full_latex_resume(
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
    tfidf = build_tfidf_vector(work_history_text)
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


# ── Generate answers ───────────────────────────────────────────────────────


@router.post("/generate/answers")
async def generate_answers(
    question_text: str = Form(...),
    question_category: str = Form("custom"),
    company_name: str = Form(...),
    role_title: str = Form(""),
    jd_text: str = Form(""),
    work_history_text: str = Form(""),  # optional — auto-filled from DB if empty
    llm_provider: str = Form("anthropic"),
    llm_api_key: str | None = Form(None),
    ollama_model: str = Form("llama3.1:8b"),
    providers_json: str = Form(""),  # JSON: [{"name":"groq","api_key":"...","model":"..."}]
    max_length: int = Form(0),  # textarea maxlength — 0 means no limit
    category_instructions: str = Form(""),  # per-category style instructions from user settings
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Generate 3 draft answers to an open-ended application question.
    Each draft is ≤ 250 words, grounded in the user's real work history.
    High-reward past answers are injected as style examples (RL grounding).
    If work_history_text is empty, pulls structured history from the DB automatically.
    category_instructions: extra style instructions per category from the user's settings page.
    """
    # 0. Auto-fetch work history from DB if not provided by the client
    if not work_history_text.strip():
        wh_stmt = (
            select(WorkHistoryEntry)
            .where(WorkHistoryEntry.user_id == user.id)
            .order_by(WorkHistoryEntry.sort_order, WorkHistoryEntry.created_at.desc())
        )
        wh_result = await db.execute(wh_stmt)
        wh_entries = list(wh_result.scalars().all())
        work_history_text = "\n\n".join(e.to_text_block() for e in wh_entries)

    # 1. Check for an exact previous answer at this company
    prev = await _retrieval_agent.get_previous_answer(db, user.id, question_text, company_name)

    # 2. Pull top-3 high-reward answers for this category to ground the LLM
    best_past = await _retrieval_agent.get_best_answers_for_question(
        db, user.id, question_text, question_category, top_k=3
    )
    # Only inject answers with a meaningful reward score (0.6+)
    past_texts = [a.answer_text for a in best_past if (a.reward_score or 0) >= 0.6]

    # Cascade mode: try providers in priority order, use first that works for all 3 drafts
    providers_list: list[dict] = []
    if providers_json.strip():
        try:
            providers_list = _json.loads(providers_json)
        except Exception:
            logger.warning("Invalid providers_json — falling back to single provider")

    # Resolve candidate name for cover letter greeting
    candidate_name = ""
    if question_category == "cover_letter":
        from app.models.work_history import WorkHistoryEntry as _WH  # noqa: F401

        # Try to get the name from the user record
        candidate_name = getattr(user, "display_name", "") or getattr(user, "email_hash", "")[:8]

    draft_providers: list[str] = []
    if providers_list:
        if len(providers_list) > 1:
            # Parallel mode: each provider generates one draft concurrently
            drafts, draft_providers = await generate_answer_drafts_parallel(
                question_text=question_text,
                question_category=question_category,
                company_name=company_name,
                role_title=role_title,
                jd_text=jd_text,
                work_history_text=work_history_text,
                providers=providers_list,
                past_accepted_answers=past_texts or None,
                candidate_name=candidate_name,
                max_length=max_length if max_length > 0 else None,
                category_instructions=category_instructions.strip() or None,
            )
        else:
            # Single provider: use cascade (generates 3 drafts from one provider)
            drafts, provider_used = await generate_answer_drafts_cascade(
                question_text=question_text,
                question_category=question_category,
                company_name=company_name,
                role_title=role_title,
                jd_text=jd_text,
                work_history_text=work_history_text,
                providers=providers_list,
                past_accepted_answers=past_texts or None,
                candidate_name=candidate_name,
                max_length=max_length if max_length > 0 else None,
                category_instructions=category_instructions.strip() or None,
            )
            if provider_used and provider_used != "fallback":
                draft_providers = [provider_used] * len(drafts)
    else:
        drafts = await generate_answer_drafts(
            question_text=question_text,
            question_category=question_category,
            company_name=company_name,
            role_title=role_title,
            jd_text=jd_text,
            work_history_text=work_history_text,
            provider=llm_provider,
            api_key=llm_api_key or user.encrypted_llm_api_key or "",
            ollama_model=ollama_model,
            past_accepted_answers=past_texts or None,
        )

    return {
        "drafts": drafts,
        "draft_providers": draft_providers,
        "previously_used": prev.answer_text if prev else None,
        "previously_used_at": prev.created_at.isoformat() if prev else None,
        "question_category": question_category,
    }


# ── Trim answer to character limit ─────────────────────────────────────────


@router.post("/generate/answers/trim")
async def trim_answer(
    answer_text: str = Form(...),
    max_chars: int = Form(...),
    providers_json: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    Shorten an existing answer draft to fit within max_chars.
    Uses the same LLM cascade as generate/answers but with a concise
    rewrite instruction. Falls back to hard-truncation if LLM unavailable.
    """
    if len(answer_text) <= max_chars:
        return {"trimmed": answer_text, "char_count": len(answer_text), "provider_used": "none"}

    providers_list: list[dict] = []
    if providers_json.strip():
        with contextlib.suppress(Exception):
            providers_list = _json.loads(providers_json)

    system_prompt = "You are a precise editor. Your only task is to shorten text to fit a strict character limit while preserving meaning, tone, and all key facts. Return ONLY the shortened text — no commentary."
    target_words = max(30, (max_chars // 5) - 10)
    user_prompt = f"""Shorten the following text to under {max_chars} characters (approximately {target_words} words).
Keep the most impactful content. Preserve first-person voice. Return only the shortened version.

TEXT TO SHORTEN:
{answer_text}"""

    trimmed = ""
    provider_used = "truncation"

    if providers_list:
        sorted_p = sorted(providers_list, key=lambda p: _PROVIDER_RANK.get(p.get("name", ""), 50))
        for p in sorted_p:
            name = p.get("name", "")
            api_key = p.get("api_key", "")
            model = p.get("model", "")
            try:
                if name == "anthropic" and api_key:
                    raw = await _call_anthropic(system_prompt, user_prompt, api_key)
                elif name == "openai" and api_key:
                    raw = await _call_openai(system_prompt, user_prompt, api_key)
                elif name == "gemini" and api_key:
                    raw = await _call_gemini(
                        system_prompt, user_prompt, api_key, model or "gemini-1.5-flash"
                    )
                elif name == "groq" and api_key:
                    raw = await _call_groq(
                        system_prompt, user_prompt, api_key, model or "llama-3.3-70b-versatile"
                    )
                elif name == "kimi" and api_key:
                    raw = await _call_kimi(system_prompt, user_prompt, api_key)
                else:
                    continue
                if raw and len(raw.strip()) > 20:
                    trimmed = raw.strip()[:max_chars]
                    provider_used = name
                    break
            except Exception as e:
                logger.warning(f"Trim: provider '{name}' failed — {e}")

    # Hard-truncation fallback — cut at last sentence boundary
    if not trimmed:
        candidate = answer_text[:max_chars]
        last_period = max(candidate.rfind(". "), candidate.rfind(".\n"))
        if last_period > max_chars * 0.6:
            trimmed = candidate[: last_period + 1]
        else:
            trimmed = candidate.rstrip() + "…"

    return {
        "trimmed": trimmed,
        "char_count": len(trimmed),
        "provider_used": provider_used,
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

    drafts, draft_providers = await generate_cover_letter(
        company_name=company_name,
        role_title=role_title,
        jd_text=jd_text,
        work_history_text=work_history_text,
        providers=providers_list,
        candidate_name=candidate_name,
        tone=tone,
        word_limit=min(max(150, word_limit), 800),
        past_accepted=past_accepted or None,
    )

    return {
        "drafts": drafts,
        "draft_providers": draft_providers,
        "tone": tone,
        "word_limit": word_limit,
    }


# ── Save answer ────────────────────────────────────────────────────────────


@router.post("/answers/save", status_code=status.HTTP_201_CREATED)
async def save_answer(
    question_text: str = Form(...),
    question_category: str = Form("custom"),
    answer_text: str = Form(...),
    company_name: str = Form(...),
    role_title: str = Form(""),
    job_id: str | None = Form(None),
    application_id: str | None = Form(None),
    was_default: bool = Form(False),
    llm_provider_used: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Save a user-accepted answer to the DB for future reuse and callback reference."""

    q_hash = hashlib.sha256(" ".join(question_text.lower().split()).encode()).hexdigest()

    word_count = len(answer_text.split())

    answer = ApplicationAnswer(
        user_id=user.id,
        application_id=uuid.UUID(application_id) if application_id else None,
        question_hash=q_hash,
        question_text=question_text,
        question_category=question_category,
        answer_text=answer_text,
        word_count=word_count,
        was_default=was_default,
        llm_provider_used=llm_provider_used or None,
        company_name=company_name,
        role_title=role_title,
        job_id=job_id,
    )
    db.add(answer)
    await db.commit()
    await db.refresh(answer)

    return {
        "answer_id": str(answer.id),
        "word_count": word_count,
        "question_hash": q_hash,
        "saved": True,
    }


# ── Saved cover letters ─────────────────────────────────────────────────────


@router.get("/cover-letters")
async def list_cover_letters(
    company: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    List saved cover letters (ApplicationAnswers with category = cover_letter).
    Optionally filter by company_name.
    """
    stmt = (
        select(ApplicationAnswer)
        .where(
            ApplicationAnswer.user_id == user.id,
            ApplicationAnswer.question_category == "cover_letter",
        )
        .order_by(ApplicationAnswer.created_at.desc())
        .limit(min(limit, 50))
    )
    if company:
        stmt = stmt.where(ApplicationAnswer.company_name.ilike(f"%{company}%"))

    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "company_name": r.company_name,
                "role_title": r.role_title,
                "answer_text": r.answer_text,
                "word_count": r.word_count,
                "reward_score": r.reward_score,
                "llm_provider_used": r.llm_provider_used,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── Answer feedback (RL reward signal) ────────────────────────────────────


def _levenshtein(a: str, b: str) -> int:
    """Simple O(mn) Levenshtein distance on character level."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Limit to first 1000 chars to stay fast
    a, b = a[:1000], b[:1000]
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(prev[j - 1] if ca == cb else 1 + min(prev[j], curr[j - 1], prev[j - 1]))
        prev = curr
    return prev[-1]


def _compute_reward(feedback: str, edit_distance: int = 0, answer_len: int = 1) -> float:
    """
    Reward function for the contextual bandit.
      used_as_is  → 1.0
      edited      → 0.8 penalised by normalised edit distance (min 0.4)
      regenerated → 0.2
      skipped     → 0.0
    """
    if feedback == "used_as_is":
        return 1.0
    if feedback == "edited":
        penalty = min(edit_distance / max(answer_len, 1), 0.4)
        return max(0.4, 0.8 - penalty)
    if feedback == "regenerated":
        return 0.2
    if feedback == "skipped":
        return 0.0
    return 0.5  # pending / unknown


@router.patch("/answers/{answer_id}/feedback")
async def record_answer_feedback(
    answer_id: str,
    feedback: str = Form(...),  # used_as_is | edited | regenerated | skipped
    edited_answer: str | None = Form(None),  # final text if user edited before using
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Record the outcome of a generated answer draft (RL reward signal).
    Called by the extension after the user decides what to do with a draft.
    """
    stmt = select(ApplicationAnswer).where(
        ApplicationAnswer.id == uuid.UUID(answer_id),
        ApplicationAnswer.user_id == user.id,
    )
    result = await db.execute(stmt)
    ans = result.scalar_one_or_none()
    if ans is None:
        raise HTTPException(status_code=404, detail="Answer not found")

    valid_feedback = {"used_as_is", "edited", "regenerated", "skipped"}
    if feedback not in valid_feedback:
        raise HTTPException(status_code=422, detail=f"feedback must be one of {valid_feedback}")

    edit_dist = 0
    if feedback == "edited" and edited_answer:
        # Update the stored answer to the final version the user used
        edit_dist = _levenshtein(ans.answer_text, edited_answer)
        ans.answer_text = edited_answer
        ans.word_count = len(edited_answer.split())

    ans.feedback = feedback
    ans.edit_distance = edit_dist
    ans.reward_score = _compute_reward(feedback, edit_dist, len(ans.answer_text))

    await db.commit()
    logger.info(
        f"Answer feedback: {feedback} reward={ans.reward_score:.2f} "
        f"edit_dist={edit_dist} answer_id={answer_id}"
    )

    return {
        "answer_id": answer_id,
        "feedback": feedback,
        "reward_score": ans.reward_score,
        "edit_distance": edit_dist,
    }


# ── Similar answers retrieval (bandit policy) ─────────────────────────────


@router.get("/answers/similar")
async def get_similar_answers(
    question_text: str,
    question_category: str = "custom",
    top_k: int = 3,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Return the top-k highest-reward past answers for this question category,
    ranked by reward_score * 0.7 + tfidf_similarity(question_text) * 0.3.

    Used by the extension to show "From Memory" answers before generating new ones.
    """
    best = await _retrieval_agent.get_best_answers_for_question(
        db, user.id, question_text, question_category, top_k=top_k
    )
    return {
        "answers": [
            {
                "answer_id": str(a.id),
                "question_text": a.question_text,
                "answer_text": a.answer_text,
                "company_name": a.company_name,
                "question_category": a.question_category,
                "reward_score": a.reward_score,
                "feedback": a.feedback,
                "word_count": a.word_count,
                "created_at": a.created_at.isoformat(),
            }
            for a in best
        ],
        "total": len(best),
    }


# ── History ────────────────────────────────────────────────────────────────


@router.get("/history/{company_name}")
async def company_history(
    company_name: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """All resumes and answers ever used for a company — recruiter callback reference."""

    resumes = await _retrieval_agent.retrieve_by_company(db, user.id, company_name)

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


@router.get("/answers/{company_name}")
async def get_answers(
    company_name: str,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retrieve previously saved Q&A answers for a company."""

    stmt = (
        select(ApplicationAnswer)
        .where(
            ApplicationAnswer.user_id == user.id,
            ApplicationAnswer.company_name.ilike(f"%{company_name}%"),
        )
        .order_by(ApplicationAnswer.created_at.desc())
    )
    if category:
        stmt = stmt.where(ApplicationAnswer.question_category == category)

    result = await db.execute(stmt)
    answers = result.scalars().all()

    return {
        "company": company_name,
        "answers": [
            {
                "answer_id": str(a.id),
                "question_category": a.question_category,
                "question_text": a.question_text,
                "answer_text": a.answer_text,
                "word_count": a.word_count,
                "saved_at": a.created_at.isoformat(),
            }
            for a in answers
        ],
    }


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


# ── Download ────────────────────────────────────────────────────────────────


@router.get("/download/{resume_id}")
async def download_resume_file(
    resume_id: uuid.UUID,
    fmt: str = "tex",  # "tex" | "markdown"
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Download a resume file from the vault.

    fmt=tex       → returns the LaTeX source (.tex)
    fmt=markdown  → returns the markdown preview (.md)
    """
    from fastapi.responses import Response

    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if fmt == "markdown":
        content = resume.markdown_content or ""
        media_type = "text/markdown"
        ext = "md"
    else:
        content = resume.latex_content or resume.raw_text or ""
        media_type = "application/x-tex"
        ext = "tex"

    if not content:
        raise HTTPException(status_code=404, detail=f"No {fmt} content available for this resume")

    filename = resume.recruiter_filename or f"{resume.version_tag or resume.id}.{ext}"
    if not filename.endswith(f".{ext}"):
        filename = f"{filename.rsplit('.', 1)[0]}.{ext}"

    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Sync markdown (offline edit drain) ─────────────────────────────────────


@router.post("/sync-markdown")
async def sync_markdown(
    version_tag: str = Form(...),
    markdown_content: str = Form(...),
    timestamp: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Sync an offline markdown edit to the database.

    Called by the extension's background worker when connectivity is restored.
    Updates the resume's markdown_content in the vault so it reflects any
    offline edits the user made to their resume preview.
    """

    result = await db.execute(
        select(Resume)
        .where(
            Resume.user_id == user.id,
            Resume.version_tag == version_tag,
        )
        .order_by(Resume.created_at.desc())
        .limit(1)
    )
    resume = result.scalar_one_or_none()

    if not resume:
        raise HTTPException(
            status_code=404,
            detail=f"No resume found with version_tag={version_tag!r}",
        )

    resume.markdown_content = markdown_content
    await db.commit()

    logger.info(
        f"Synced offline markdown edit for {version_tag} " f"(ts={timestamp}, user={user.id})"
    )
    return {"synced": True, "version_tag": version_tag}


# ── GitHub versions directory ───────────────────────────────────────────────


@router.get("/github/versions")
async def list_github_versions(
    company: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    List all named resume versions from the GitHub resume-vault versions/ dir.

    Returns [{version_tag, path, sha, download_url}] for each .tex file.
    Requires user to have a GitHub token stored.
    """

    if not user.encrypted_github_token:
        raise HTTPException(
            status_code=400,
            detail="No GitHub token configured. Add your token via /api/v1/users/github-token.",
        )

    repo_full_name = f"{user.github_username}/{user.resume_repo_name}"
    try:
        versions = await _github_service.list_versions(
            encrypted_token=user.encrypted_github_token,
            repo_full_name=repo_full_name,
            company_filter=company,
        )
    except Exception as exc:
        logger.warning(f"GitHub list_versions failed: {exc}")
        raise HTTPException(status_code=502, detail=f"GitHub API error: {exc}") from exc

    return {"versions": versions, "total": len(versions)}


# ── Interview Prep (T3) ─────────────────────────────────────────────────────

_INTERVIEW_SYSTEM = """You are an expert interview coach helping a software engineer prepare for a job interview.
Generate exactly 10 likely interview questions for the given role and company, covering a mix of:
- Behavioral (2–3): leadership, conflict, challenge questions
- Motivation (1–2): why this company, why this role
- Technical/role-specific (2–3): based on the JD skills/requirements
- General (2–3): strengths, background, 5-year plan

For each question, provide:
1. The interview question text
2. A short category tag: behavioral | motivation | technical | general
3. A 2–4 sentence suggested answer tailored to the candidate's work history and the JD

Format your response as a JSON array with no extra text:
[
  {
    "question": "...",
    "category": "behavioral|motivation|technical|general",
    "suggested_answer": "..."
  },
  ...
]
Only return the JSON array. No markdown fences, no extra commentary."""


@router.post("/interview-prep")
async def generate_interview_prep(
    company_name: str = Form(...),
    role_title: str = Form(""),
    jd_text: str = Form(""),
    providers_json: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    T3: Generate 10 likely interview questions + suggested answers for a role.
    Grounds answers in the user's work history and the provided JD.
    Returns { questions: [{question, category, suggested_answer}] }
    """
    # Load work history
    wh_stmt = (
        select(WorkHistoryEntry)
        .where(WorkHistoryEntry.user_id == user.id)
        .order_by(WorkHistoryEntry.sort_order, WorkHistoryEntry.created_at.desc())
    )
    wh_result = await db.execute(wh_stmt)
    wh_entries = list(wh_result.scalars().all())
    work_history_text = "\n\n".join(e.to_text_block() for e in wh_entries)

    # Parse providers list
    providers_list: list[dict] = []
    if providers_json.strip():
        try:
            providers_list = _json.loads(providers_json)
        except Exception:
            logger.warning("interview-prep: invalid providers_json")

    user_prompt = f"""Candidate work history:
{work_history_text or "Not provided."}

Target company: {company_name}
Target role: {role_title or "Software Engineer"}

Job description excerpt:
{jd_text[:3000] if jd_text else "Not provided."}

Generate 10 interview questions + suggested answers as described."""

    questions: list[dict] = []

    if providers_list:
        for prov in providers_list:
            name = prov.get("name", "")
            api_key = prov.get("api_key", "")
            model = prov.get("model", "")
            try:
                if name == "anthropic":
                    raw = await _call_anthropic(_INTERVIEW_SYSTEM, user_prompt, api_key)
                elif name == "openai":
                    raw = await _call_openai(_INTERVIEW_SYSTEM, user_prompt, api_key)
                elif name == "groq":
                    raw = await _call_groq(
                        _INTERVIEW_SYSTEM, user_prompt, api_key, model or "llama-3.3-70b-versatile"
                    )
                elif name == "gemini":
                    raw = await _call_gemini(
                        _INTERVIEW_SYSTEM, user_prompt, api_key, model or "gemini-1.5-flash"
                    )
                elif name == "kimi":
                    raw = await _call_kimi(_INTERVIEW_SYSTEM, user_prompt, api_key)
                else:
                    continue
                parsed = _json.loads(raw.strip())
                if isinstance(parsed, list) and len(parsed) > 0:
                    questions = parsed[:10]
                    break
            except Exception as exc:
                logger.debug(f"interview-prep provider {name} failed: {exc}")
                continue

    # Rule-based fallback when no provider worked or none configured
    if not questions:
        questions = _rule_based_interview_questions(company_name, role_title, jd_text)

    return {"questions": questions, "total": len(questions)}


def _rule_based_interview_questions(company: str, role: str, jd_text: str) -> list[dict]:
    """Keyword-extracted question bank fallback — no LLM required."""
    base_questions = [
        {
            "question": f"Tell me about yourself and why you're interested in this {role} role at {company}.",
            "category": "general",
            "suggested_answer": "I have X years of experience in software engineering, focusing on [key skills from JD]. I'm drawn to this role because of [company mission/product].",
        },
        {
            "question": "Describe a challenging technical problem you solved recently.",
            "category": "behavioral",
            "suggested_answer": "In my last role, I faced [challenge]. I approached it by [steps]. The result was [outcome].",
        },
        {
            "question": f"Why do you want to work at {company} specifically?",
            "category": "motivation",
            "suggested_answer": f"I've followed {company}'s work in [area] and am excited by [specific product/mission]. My background in [skills] aligns well with your needs.",
        },
        {
            "question": "Tell me about a time you had to lead a project under tight deadlines.",
            "category": "behavioral",
            "suggested_answer": "I led a team of X engineers to deliver [project] in Y weeks. I broke the work into milestones, held daily standups, and unblocked issues proactively.",
        },
        {
            "question": "What's your greatest professional strength?",
            "category": "general",
            "suggested_answer": "My strongest skill is [skill] — demonstrated by [specific example with metric].",
        },
        {
            "question": "Describe a time you had a conflict with a colleague. How did you resolve it?",
            "category": "behavioral",
            "suggested_answer": "I once disagreed with a teammate about [topic]. I scheduled a 1:1, listened to their perspective, and we found a compromise by [approach].",
        },
        {
            "question": "Where do you see yourself in 5 years?",
            "category": "general",
            "suggested_answer": "I'd like to grow into a [senior/lead/staff] engineer role, taking on larger system design responsibilities and mentoring junior engineers.",
        },
        {
            "question": "How do you stay current with new technologies in your field?",
            "category": "technical",
            "suggested_answer": "I follow [blogs/newsletters], contribute to open source, and build side projects to test new tools before adopting them at work.",
        },
        {
            "question": "Tell me about a time you had to learn a new technology quickly.",
            "category": "behavioral",
            "suggested_answer": "When my team adopted [technology], I spent a week reading docs and building a proof-of-concept. Within two weeks I was contributing production code.",
        },
        {
            "question": f"What excites you most about the work {company} is doing?",
            "category": "motivation",
            "suggested_answer": f"{company}'s approach to [product area] is compelling because [reason]. I believe I can contribute to this by leveraging my experience in [relevant skill].",
        },
    ]
    return base_questions
