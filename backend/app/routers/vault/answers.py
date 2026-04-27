"""
Vault sub-module: answer generation, saving, feedback, search, and retrieval.
"""

import contextlib
import hashlib
import json as _json
import sys
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.resume import ApplicationAnswer
from app.models.user import User
from app.models.work_history import WorkHistoryEntry
from app.services.llm_gateway import (
    _call_anthropic,
    _call_gemini,
    _call_groq,
    _call_kimi,
    _call_openai,
)
from app.services.qa_generation_service import (
    _PROVIDER_RANK,
    generate_answer_drafts,
    generate_answer_drafts_cascade,
    generate_answer_drafts_parallel,
)
from app.services.rag_service import get_rag_context_for_query

from ._shared import _resolve_providers


def _agent():
    """Late lookup so tests can patch app.routers.vault._shared._retrieval_agent."""
    return sys.modules["app.routers.vault._shared"]._retrieval_agent


router = APIRouter()


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
    prev = await _agent().get_previous_answer(db, user.id, question_text, company_name)

    # 2. Pull top-3 high-reward answers for this category to ground the LLM
    best_past = await _agent().get_best_answers_for_question(
        db, user.id, question_text, question_category, top_k=3
    )
    # Only inject answers with a meaningful reward score (0.6+)
    past_texts = [ans.answer_text for _, ans in best_past if (ans.reward_score or 0) >= 0.6]

    # Cascade mode: try providers in priority order, use first that works for all 3 drafts
    # #25: prefer server-side config when client sends empty providers_json
    providers_list: list[dict] = await _resolve_providers(providers_json, db, user)

    # Resolve candidate name for cover letter greeting
    candidate_name = ""
    if question_category == "cover_letter":
        from app.models.work_history import WorkHistoryEntry as _WH  # noqa: F401

        # Try to get the name from the user record
        candidate_name = getattr(user, "display_name", "") or getattr(user, "email_hash", "")[:8]

    # Retrieve RAG context from uploaded documents (resume.md / work-history.md)
    rag_query = f"{question_category} {question_text} {company_name} {role_title}"
    answer_rag_ctx = await get_rag_context_for_query(
        db=db,
        user_id=user.id,
        query=rag_query,
        doc_types=["resume", "work_history"],
        top_k=5,
        max_context_tokens=1200,
        label="ADDITIONAL CANDIDATE CONTEXT (from uploaded documents)",
    )

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
                rag_context=answer_rag_ctx,
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
                rag_context=answer_rag_ctx,
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
            rag_context=answer_rag_ctx,
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


@router.post("/answers/bulk-save", status_code=status.HTTP_201_CREATED)
async def bulk_save_answers(
    payload: dict,  # { company_name, role_title, answers: [{question_text, category, answer_text}] }
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Save multiple answers in a single request.
    Used by interview prep "Save all to bank" and batch workflows.

    Body JSON: {
        "company_name": str,
        "role_title": str,          # optional
        "answers": [
            {
                "question_text": str,
                "question_category": str,   # default "custom"
                "answer_text": str,
                "was_default": bool,        # default False
            },
            ...
        ]
    }
    Returns: { "saved": int, "answer_ids": [str, ...] }
    """
    company_name = str(payload.get("company_name", ""))
    role_title = str(payload.get("role_title", ""))
    answers_in = payload.get("answers", [])

    if not company_name:
        raise HTTPException(status_code=422, detail="company_name is required")
    if not isinstance(answers_in, list) or len(answers_in) == 0:
        raise HTTPException(status_code=422, detail="answers must be a non-empty list")
    if len(answers_in) > 50:
        raise HTTPException(status_code=422, detail="Cannot bulk-save more than 50 answers at once")

    saved_ids: list[str] = []
    for item in answers_in:
        question_text = str(item.get("question_text", "")).strip()
        answer_text = str(item.get("answer_text", "")).strip()
        if not question_text or not answer_text:
            continue  # skip blank entries silently

        q_hash = hashlib.sha256(" ".join(question_text.lower().split()).encode()).hexdigest()
        ans = ApplicationAnswer(
            user_id=user.id,
            question_hash=q_hash,
            question_text=question_text,
            question_category=str(item.get("question_category", "custom")),
            answer_text=answer_text,
            word_count=len(answer_text.split()),
            was_default=bool(item.get("was_default", False)),
            company_name=company_name,
            role_title=role_title,
        )
        db.add(ans)
        await db.flush()  # get ID before commit
        saved_ids.append(str(ans.id))

    await db.commit()
    return {"saved": len(saved_ids), "answer_ids": saved_ids}


@router.delete("/answers/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_answer(
    answer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a saved answer from the user's bank."""
    stmt = select(ApplicationAnswer).where(
        ApplicationAnswer.id == uuid.UUID(answer_id),
        ApplicationAnswer.user_id == user.id,
    )
    result = await db.execute(stmt)
    ans = result.scalar_one_or_none()
    if ans is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    await db.delete(ans)
    await db.commit()


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


# ── Edit saved answer text ─────────────────────────────────────────────────


@router.patch("/answers/{answer_id}")
async def edit_answer_text(
    answer_id: str,
    answer_text: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Update the stored text of a saved answer.
    Resets reward_score to 0.5 (neutral) since we can't assess quality of manual edits.
    """
    stmt = select(ApplicationAnswer).where(
        ApplicationAnswer.id == uuid.UUID(answer_id),
        ApplicationAnswer.user_id == user.id,
    )
    result = await db.execute(stmt)
    ans = result.scalar_one_or_none()
    if ans is None:
        raise HTTPException(status_code=404, detail="Answer not found")

    ans.answer_text = answer_text.strip()
    ans.word_count = len(ans.answer_text.split())
    ans.feedback = "edited"
    ans.reward_score = 0.5  # neutral — user manually provided this answer

    await db.commit()
    return {
        "answer_id": answer_id,
        "word_count": ans.word_count,
        "feedback": ans.feedback,
        "reward_score": ans.reward_score,
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
    best = await _agent().get_best_answers_for_question(
        db, user.id, question_text, question_category, top_k=top_k
    )
    return {
        "answers": [
            {
                "answer_id": str(ans.id),
                "question_text": ans.question_text,
                "answer_text": ans.answer_text,
                "company_name": ans.company_name,
                "question_category": ans.question_category,
                "reward_score": ans.reward_score,
                "similarity_score": round(score, 4),
                "feedback": ans.feedback,
                "word_count": ans.word_count,
                "created_at": ans.created_at.isoformat(),
            }
            for score, ans in best
        ],
        "total": len(best),
    }


@router.get("/answers/search")
async def search_answers(
    q: str,
    category: str | None = None,
    company: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Full-text search over a user's saved answer bank.
    Matches against question_text and answer_text (case-insensitive ILIKE).

    Query params:
      q        — required search term
      category — optional filter by question_category
      company  — optional filter by company_name
      limit    — max results (default 20, max 50)
    """
    if not q or not q.strip():
        raise HTTPException(status_code=422, detail="q (search term) is required")

    limit = min(max(1, limit), 50)
    term = f"%{q.strip()}%"

    stmt = (
        select(ApplicationAnswer)
        .where(
            ApplicationAnswer.user_id == user.id,
            (
                ApplicationAnswer.question_text.ilike(term)
                | ApplicationAnswer.answer_text.ilike(term)
            ),
        )
        .order_by(
            ApplicationAnswer.reward_score.desc().nulls_last(), ApplicationAnswer.created_at.desc()
        )
        .limit(limit)
    )

    if category:
        stmt = stmt.where(ApplicationAnswer.question_category == category)
    if company:
        stmt = stmt.where(ApplicationAnswer.company_name.ilike(f"%{company}%"))

    result = await db.execute(stmt)
    answers = result.scalars().all()

    return {
        "q": q,
        "answers": [
            {
                "answer_id": str(a.id),
                "question_text": a.question_text[:300],
                "answer_text": a.answer_text,
                "company_name": a.company_name,
                "question_category": a.question_category,
                "reward_score": a.reward_score,
                "feedback": a.feedback,
                "word_count": a.word_count,
                "created_at": a.created_at.isoformat(),
            }
            for a in answers
        ],
        "total": len(answers),
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
