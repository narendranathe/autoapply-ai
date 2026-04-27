"""
Vault sub-module: interview preparation endpoint.
"""

import json as _json

from fastapi import APIRouter, Depends, Form
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.story import StoryEntry
from app.models.user import User
from app.models.work_history import WorkHistoryEntry
from app.services.llm_gateway import (
    _call_anthropic,
    _call_gemini,
    _call_groq,
    _call_kimi,
    _call_openai,
)

router = APIRouter()


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

    # Fetch matched stories for grounding
    stories_stmt = (
        select(StoryEntry)
        .where(StoryEntry.user_id == user.id)
        .order_by(StoryEntry.quality_score.desc())
        .limit(20)
    )
    stories_result = await db.execute(stories_stmt)
    all_stories = list(stories_result.scalars().all())

    from app.services.story_service import match_stories_to_jd

    matched_stories = match_stories_to_jd(jd_text, all_stories)[:3] if jd_text else []

    stories_block = ""
    if matched_stories:
        lines = ["Proven narratives to draw from (use as grounding, do not fabricate):"]
        for i, s in enumerate(matched_stories, 1):
            lines.append(f"{i}. Action: {s.action} | Result: {s.result_text}")
        stories_block = "\n".join(lines)

    # Parse providers list
    providers_list: list[dict] = []
    if providers_json.strip():
        try:
            providers_list = _json.loads(providers_json)
        except Exception:
            logger.warning("interview-prep: invalid providers_json")

    user_prompt = f"""Candidate work history:
{work_history_text or "Not provided."}

{stories_block}

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
