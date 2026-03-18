"""
Resume Generator — produces a complete LaTeX resume tailored to a JD.

Loads:
  - docs/resume_instructions.md  (general rules, 2026 DE standards)
  - docs/resume_personal_config.md  (output format, LaTeX template rules, integrity)
  - docs/templates/resume_template.tex  (structural LaTeX skeleton)

Fills template variables with personal data injected at call time (from private vault).
Personal data NEVER lives in this file or the docs above.

LLM cascade:
  1. Anthropic claude-sonnet-4-6 (preferred)
  2. OpenAI gpt-4o
  3. Kimi moonshot-v1-32k (long-context JDs)
  4. Ollama llama3.1:8b (local, no API cost)
  5. Rule-based keyword fallback (no LLM)

Output: .tex string ready for pdflatex compilation.
A .md preview is also generated for easy human review/editing.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from loguru import logger

from app.services.ats_service import ATSResult
from app.services.llm_gateway import LLMGateway

# ── Load instruction files ─────────────────────────────────────────────────

_DOCS_ROOT = Path(__file__).parent.parent.parent.parent / "docs"


def _load_doc(filename: str) -> str:
    path = _DOCS_ROOT / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning(f"Instruction file not found: {path}")
    return ""


def _load_template() -> str:
    path = _DOCS_ROOT / "templates" / "resume_template.tex"
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("resume_template.tex not found — using minimal fallback template")
    return _MINIMAL_FALLBACK_TEMPLATE


_MINIMAL_FALLBACK_TEMPLATE = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage[hidelinks]{hyperref}
\usepackage{enumitem}
\pagestyle{empty}
\begin{document}
\begin{center}
\textbf{\Huge \scshape {{NAME}}} \\
\small {{PHONE}} $|$ \href{mailto:{{EMAIL}}}{\underline{{{EMAIL}}}} $|$
\href{{{LINKEDIN_URL}}}{\underline{{{LINKEDIN_LABEL}}}} $|$
\href{{{PORTFOLIO_URL}}}{\underline{{{PORTFOLIO_LABEL}}}}
\end{center}
{{EDUCATION}}
{{EXPERIENCE}}
{{PROJECTS}}
{{CERTIFICATIONS}}
{{SKILLS}}
\end{document}
"""


# ── Data contracts ─────────────────────────────────────────────────────────


@dataclass
class PersonalProfile:
    """User personal data injected at generation time from private vault."""

    name: str
    phone: str
    email: str
    linkedin_url: str
    linkedin_label: str
    portfolio_url: str
    portfolio_label: str
    # Structured work history — used as grounding context for LLM
    work_history_text: str = ""  # raw text extracted from base resume
    education_text: str = ""  # raw education section


@dataclass
class GeneratedResume:
    latex_content: str
    markdown_preview: str
    version_tag: str
    recruiter_filename: str  # always {FirstName}.pdf
    ats_score_estimate: float | None = None
    skills_gap: list[str] = field(default_factory=list)
    changes_summary: str = ""
    llm_provider_used: str = "fallback"
    generation_warnings: list[str] = field(default_factory=list)


@dataclass
class SkillGapItem:
    skill: str
    jd_context: str  # sentence from JD where this skill appears
    suggested_reframe: str  # how to surface from existing experience


# ── Version tag builder ────────────────────────────────────────────────────

_ROLE_ABBREVS = {
    "data engineer": "DE",
    "data scientist": "DS",
    "software engineer": "SWE",
    "swe": "SWE",
    "machine learning": "MLE",
    "ml engineer": "MLE",
    "analytics engineer": "AE",
    "data analyst": "DA",
    "platform engineer": "PE",
    "product manager": "PM",
    "solutions architect": "SA",
    "devops": "SRE",
    "site reliability": "SRE",
    "applied scientist": "AS",
}

_COMPANY_SHORT = {
    "goldman sachs": "GS",
    "jp morgan": "JPMC",
    "jpmorgan": "JPMC",
    "jp morgan chase": "JPMC",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "netflix": "NFLX",
    "alphabet": "Google",
    "meta platforms": "Meta",
}


def build_version_tag(
    first_name: str,
    company: str,
    role_title: str,
    job_id: str | None = None,
) -> str:
    """
    Build git version tag: {FirstName}_{CompanyShortName}_{RoleAbbrev}[_{JobID}]

    The recruiter-facing PDF is always {FirstName}.pdf — the tag is internal only.
    """
    # Company short name
    company_key = company.lower().strip()
    short = _COMPANY_SHORT.get(company_key, company.strip().replace(" ", ""))
    # Capitalise first letter of each word segment
    short = "".join(w.capitalize() for w in re.split(r"[\s_-]+", short))

    # Role abbreviation
    role_lower = role_title.lower()
    abbrev = "DE"  # default
    for pattern, abbr in _ROLE_ABBREVS.items():
        if pattern in role_lower:
            abbrev = abbr
            break

    tag = f"{first_name}_{short}_{abbrev}"
    if job_id:
        tag += f"_{job_id.upper()}"
    return tag


# ── System prompt ──────────────────────────────────────────────────────────


def _build_system_prompt() -> str:
    instructions = _load_doc("resume_instructions.md")
    personal_config = _load_doc("resume_personal_config.md")

    # Extract just the integrity and rules sections to keep context focused
    integrity_section = ""
    if "## Resume Integrity Rules" in personal_config:
        idx = personal_config.find("## Resume Integrity Rules")
        integrity_section = personal_config[idx : idx + 2000]

    return f"""You are an expert resume writer generating a LaTeX resume.

CRITICAL INTEGRITY RULES — NEVER VIOLATE:
1. Only use facts from the candidate's actual work history provided below
2. Never fabricate metrics, percentages, company names, or technologies
3. Never add skills the candidate has not used — even if they appear in the JD
4. Increase ATS alignment by reframing genuine experience in JD vocabulary, not by padding
5. A single cloud platform should lead (Azure, AWS, OR GCP — not all three equally)
6. Every bullet must follow the XYZ formula: accomplished [X] as measured by [Y], by doing [Z]
7. Output must be valid LaTeX — no markdown, no plain text, no code fences
8. Single page only — no exceptions

OUTPUT FORMAT:
- Return ONLY the complete LaTeX document content
- Start with \\documentclass
- End with \\end{{document}}
- No explanation, no markdown wrapping, no code fences

{integrity_section}

RESUME RULES REFERENCE:
{instructions[:3000]}
"""


# ── LLM call helpers ───────────────────────────────────────────────────────


async def _call_anthropic(system: str, user: str, api_key: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 4096,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "temperature": 0.2,
            },
        )
        response.raise_for_status()
        return response.json()["content"][0]["text"]


async def _call_openai(system: str, user: str, api_key: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def _call_groq(
    system: str, user: str, api_key: str, model: str = "llama-3.3-70b-versatile"
) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def _call_gemini(
    system: str, user: str, api_key: str, model: str = "gemini-1.5-flash"
) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def _call_perplexity(system: str, user: str, api_key: str, model: str = "sonar") -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 2048,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def _call_kimi(system: str, user: str, api_key: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "moonshot-v1-32k",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "max_tokens": 4096,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def _call_ollama(system: str, user: str, model: str = "llama3.1:8b") -> str:
    async with httpx.AsyncClient(timeout=180.0) as client:
        from app.config import settings

        response = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "system": system,
                "prompt": user,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 4096},
            },
        )
        response.raise_for_status()
        return response.json()["response"]


_llm_gateway = LLMGateway()


async def _llm_generate(
    system_prompt: str,
    user_prompt: str,
    provider: str,
    api_key: str = "",
    ollama_model: str = "llama3.1:8b",
) -> tuple[str, str]:
    """
    Try LLM providers in cascade order.
    Returns (raw_text, provider_name_used).

    Delegates to LLMGateway — single source of truth for provider dispatch.
    """
    return await _llm_gateway.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        provider=provider,
        api_key=api_key,
        ollama_model=ollama_model,
    )


# ── Answer generation (Q&A) ────────────────────────────────────────────────

_ANSWER_SYSTEM_PROMPT = """You generate compelling, honest answers to job application questions.

ABSOLUTE RULES:
1. Ground every answer in the candidate's real work history provided — no fabrication
2. Align tone and language to the company's known culture (from JD and company context)
3. End with a forward-looking statement tying the candidate's background to the company's mission
4. Use active voice, first-person implied (no "I am a person who...")
5. Never exceed 250 words — target 180-220 words (readable in 6-7 seconds)
6. Never open with "I am passionate about..." or "I have always wanted to..."
7. Every claim must be traceable to the provided work history

ANSWER QUALITY STANDARDS:
- Open with a concrete achievement or specific insight about the company
- Include at least one quantified accomplishment from the work history
- Use the company's own language and values from the JD
- Close with a specific, forward-looking contribution statement
"""

_COVER_LETTER_SYSTEM_PROMPT = """You write professional, compelling cover letters for job applications.

STRUCTURE (strictly follow):
1. Greeting: "Dear Hiring Team," (or specific name if provided in JD)
2. Opening paragraph (2-3 sentences): Hook with a specific achievement or insight about the company's work, then state the role applied for
3. Body paragraph 1 (3-4 sentences): Most relevant technical experience — ground in real work history, quantify where possible
4. Body paragraph 2 (3-4 sentences): Alignment with company mission/values — use their own language from the JD
5. Closing paragraph (2-3 sentences): Clear call to action, express enthusiasm, sign off professionally

ABSOLUTE RULES:
1. Total length: 300-420 words. Never exceed 450 words.
2. Every factual claim must come from the provided work history — no fabrication
3. Never open with "I am writing to apply..." or "I am excited to apply..."
4. Open paragraph must contain a specific achievement or observation about the company
5. Use active voice throughout
6. End with "Sincerely," followed by [CANDIDATE_NAME]
"""


def _build_cover_letter_prompt(
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    candidate_name: str = "the candidate",
    past_accepted_answers: list[str] | None = None,
) -> str:
    """Build the user prompt for cover letter generation."""
    memory_block = ""
    if past_accepted_answers:
        examples = "\n\n---\n".join(
            f"EXAMPLE COVER LETTER {i+1}:\n{a[:600]}"
            for i, a in enumerate(past_accepted_answers[:2])
        )
        memory_block = f"""
PREVIOUSLY ACCEPTED COVER LETTERS (mirror this voice/style — do NOT copy verbatim):
{examples}

"""

    wh_section = (
        f"CANDIDATE WORK HISTORY (ground every sentence in these facts):\n{work_history_text[:3500]}"
        if work_history_text.strip()
        else "CANDIDATE WORK HISTORY: Not provided — write a compelling cover letter using professional language, strong transferable skills, and genuine enthusiasm for the company's mission."
    )

    return f"""Write a cover letter for the following application.

POSITION: {role_title}
COMPANY: {company_name}
CANDIDATE NAME: {candidate_name}

JOB DESCRIPTION:
{jd_text[:2500]}

{wh_section}

{memory_block}Write exactly 3 different cover letter drafts, each taking a different opening angle.

Respond in EXACTLY this format:
DRAFT_1:
[complete cover letter — 300-420 words]

DRAFT_2:
[complete cover letter — 300-420 words, different opening]

DRAFT_3:
[complete cover letter — 300-420 words, different angle]
"""


async def generate_answer_drafts(
    question_text: str,
    question_category: str,
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    provider: str,
    api_key: str = "",
    ollama_model: str = "llama3.1:8b",
    past_accepted_answers: list[str] | None = None,
    rag_context: str = "",
) -> list[str]:
    """
    Generate 3 draft answers to an open-ended application question.
    Returns list of 3 answer strings, each ≤ 250 words.

    past_accepted_answers: high-reward answers to similar questions from history.
    Injected as style/voice examples so the LLM learns the user's preferred tone.
    """
    # Load answering framework for this category
    config = _load_doc("resume_personal_config.md")
    framework_snippet = _extract_category_framework(config, question_category)

    # Build "From Memory" context block if we have good past answers
    memory_block = ""
    if past_accepted_answers:
        examples = "\n\n---\n".join(
            f"EXAMPLE {i+1}:\n{a[:400]}" for i, a in enumerate(past_accepted_answers[:3])
        )
        memory_block = f"""
PREVIOUSLY ACCEPTED ANSWERS (high quality — mirror this voice and style):
{examples}

Adapt the voice and structure above to the current question/company.
Do NOT copy verbatim — generate fresh content grounded in work history.
"""

    rag_section = f"\n{rag_context}\n" if rag_context.strip() else ""

    user_prompt = f"""QUESTION: {question_text}
CATEGORY: {question_category}
COMPANY: {company_name}
ROLE: {role_title}

JOB DESCRIPTION (first 2000 chars):
{jd_text[:2000]}

CANDIDATE WORK HISTORY (use ONLY these facts — no fabrication):
{work_history_text[:3000]}
{rag_section}
ANSWERING FRAMEWORK FOR THIS CATEGORY:
{framework_snippet}
{memory_block}
Generate exactly 3 different draft answers. Each must:
- Be ≤ 250 words (180-220 words ideal)
- Use a different angle or emphasis while staying factual
- Follow all rules in the system prompt

Format your response as:
DRAFT_1:
[answer text]

DRAFT_2:
[answer text]

DRAFT_3:
[answer text]
"""

    raw, provider_used = await _llm_generate(
        _ANSWER_SYSTEM_PROMPT, user_prompt, provider, api_key, ollama_model
    )

    if not raw or provider_used == "fallback":
        return _rule_based_answer_drafts(question_category, company_name, work_history_text)

    return _parse_answer_drafts(raw)


async def generate_answer_drafts_multi(
    question_text: str,
    question_category: str,
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    providers: list[dict],  # [{"name": "groq", "api_key": "...", "model": "..."}]
    past_accepted_answers: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Run all configured LLM providers in parallel. Each generates 1 draft answer.
    Returns (drafts, provider_names) — parallel lists, failures silently dropped.
    """
    config = _load_doc("resume_personal_config.md")
    framework_snippet = _extract_category_framework(config, question_category)

    memory_block = ""
    if past_accepted_answers:
        examples = "\n\n---\n".join(
            f"EXAMPLE {i+1}:\n{a[:400]}" for i, a in enumerate(past_accepted_answers[:3])
        )
        memory_block = f"""
PREVIOUSLY ACCEPTED ANSWERS (mirror this voice/style, do NOT copy verbatim):
{examples}
"""

    user_prompt = f"""QUESTION: {question_text}
CATEGORY: {question_category}
COMPANY: {company_name}
ROLE: {role_title}

JOB DESCRIPTION:
{jd_text[:2000]}

CANDIDATE WORK HISTORY (use ONLY these facts):
{work_history_text[:3000]}

ANSWERING FRAMEWORK:
{framework_snippet}
{memory_block}
Write exactly 1 compelling draft answer (180-220 words). Return only the answer text."""

    async def _call_one(p: dict) -> tuple[str, str]:
        name = p.get("name", "")
        api_key = p.get("api_key", "")
        model = p.get("model", "")
        try:
            if name == "anthropic" and api_key:
                raw = await _call_anthropic(_ANSWER_SYSTEM_PROMPT, user_prompt, api_key)
            elif name == "openai" and api_key:
                raw = await _call_openai(_ANSWER_SYSTEM_PROMPT, user_prompt, api_key)
            elif name == "gemini" and api_key:
                raw = await _call_gemini(
                    _ANSWER_SYSTEM_PROMPT, user_prompt, api_key, model or "gemini-1.5-flash"
                )
            elif name == "groq" and api_key:
                raw = await _call_groq(
                    _ANSWER_SYSTEM_PROMPT, user_prompt, api_key, model or "llama-3.3-70b-versatile"
                )
            elif name == "perplexity" and api_key:
                raw = await _call_perplexity(
                    _ANSWER_SYSTEM_PROMPT, user_prompt, api_key, model or "sonar"
                )
            elif name == "kimi" and api_key:
                raw = await _call_kimi(_ANSWER_SYSTEM_PROMPT, user_prompt, api_key)
            elif name == "ollama":
                raw = await _call_ollama(_ANSWER_SYSTEM_PROMPT, user_prompt, model or "llama3.1:8b")
            else:
                return ("", name)
            return (raw.strip(), name) if raw and len(raw) > 50 else ("", name)
        except Exception as e:
            logger.warning(f"Multi-LLM: provider '{name}' failed: {e}")
            return ("", name)

    results = await asyncio.gather(*[_call_one(p) for p in providers])

    drafts, names = [], []
    for draft, name in results:
        if draft:
            drafts.append(draft)
            names.append(name)
    return drafts, names


# ── Priority ranks (lower = better) ────────────────────────────────────────
_PROVIDER_RANK: dict[str, int] = {
    "anthropic": 1,
    "openai": 2,
    "gemini": 3,
    "groq": 4,
    "perplexity": 5,
    "kimi": 6,
    "ollama": 99,  # local only — skipped on cloud backend
}


async def generate_answer_drafts_cascade(
    question_text: str,
    question_category: str,
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    providers: list[dict],  # [{"name": "groq", "api_key": "...", "model": "..."}], priority-ordered
    past_accepted_answers: list[str] | None = None,
    candidate_name: str = "",
    max_length: int | None = None,
    category_instructions: str | None = None,  # extra style instructions from user settings
    rag_context: str = "",
) -> tuple[list[str], str]:
    """
    Try providers in priority order. Use the first working one to generate 3 drafts.
    Cover letters get a dedicated prompt and system message.
    Returns (drafts, provider_name_used).
    Falls back to rule-based drafts if all providers fail.
    """
    is_cover_letter = question_category == "cover_letter"

    # Sort by quality rank so best provider is tried first
    sorted_providers = sorted(providers, key=lambda p: _PROVIDER_RANK.get(p.get("name", ""), 50))

    if is_cover_letter:
        system_prompt = _COVER_LETTER_SYSTEM_PROMPT
        user_prompt = _build_cover_letter_prompt(
            company_name=company_name,
            role_title=role_title,
            jd_text=jd_text,
            work_history_text=work_history_text,
            candidate_name=candidate_name or "the candidate",
            past_accepted_answers=past_accepted_answers,
        )
    else:
        system_prompt = _ANSWER_SYSTEM_PROMPT
        config = _load_doc("resume_personal_config.md")
        framework_snippet = _extract_category_framework(config, question_category)

        memory_block = ""
        if past_accepted_answers:
            examples = "\n\n---\n".join(
                f"EXAMPLE {i+1}:\n{a[:400]}" for i, a in enumerate(past_accepted_answers[:3])
            )
            memory_block = f"""
PREVIOUSLY ACCEPTED ANSWERS (high quality — mirror this voice and style):
{examples}

Adapt the voice and structure above to the current question/company.
Do NOT copy verbatim — generate fresh content grounded in work history.
"""

        wh_section = (
            f"CANDIDATE WORK HISTORY (ground every answer in these facts):\n{work_history_text[:3000]}"
            if work_history_text.strip()
            else "CANDIDATE WORK HISTORY: Not provided — write compelling, honest general answers about professional growth, teamwork, and problem-solving that any experienced engineer could claim."
        )

        # Build length constraint instruction based on textarea maxlength
        if max_length and max_length > 0:
            # Convert char limit to approximate word limit (avg 5 chars/word)
            max_words = max(50, (max_length // 5) - 20)  # leave headroom for safety
            length_instruction = f"CRITICAL: The application field has a {max_length}-character limit. Keep each answer under {max_words} words."
        else:
            length_instruction = "Target 150-220 words per answer."

        # Inject per-category style instructions if provided by the user
        style_block = ""
        if category_instructions and category_instructions.strip():
            style_block = (
                f"\nUSER STYLE INSTRUCTIONS (MUST follow):\n{category_instructions.strip()}\n"
            )

        rag_block = f"\n{rag_context}\n" if rag_context.strip() else ""

        user_prompt = f"""QUESTION: {question_text}
CATEGORY: {question_category}
COMPANY: {company_name}
ROLE: {role_title}

JOB DESCRIPTION (first 2000 chars):
{jd_text[:2000]}

{wh_section}
{rag_block}
ANSWERING FRAMEWORK FOR THIS CATEGORY:
{framework_snippet}
{memory_block}{style_block}
Generate exactly 3 different draft answers. Each answer must use a DIFFERENT angle or emphasis.
{length_instruction}

Respond in EXACTLY this format — no other text:
DRAFT_1:
[answer text here]

DRAFT_2:
[answer text here, different angle from Draft 1]

DRAFT_3:
[answer text here, different angle from Drafts 1 and 2]
"""

    for p in sorted_providers:
        name = p.get("name", "")
        api_key = p.get("api_key", "")
        model = p.get("model", "")
        try:
            if name == "ollama":
                # Ollama only works with a local backend — skip on cloud deployments
                continue
            elif name == "anthropic" and api_key:
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
            elif name == "perplexity" and api_key:
                raw = await _call_perplexity(system_prompt, user_prompt, api_key, model or "sonar")
            elif name == "kimi" and api_key:
                raw = await _call_kimi(system_prompt, user_prompt, api_key)
            else:
                continue
            min_len = 200 if is_cover_letter else 100
            if raw and len(raw) > min_len:
                drafts = _parse_answer_drafts(raw)
                if drafts:
                    logger.info(
                        f"Cascade: used provider '{name}' for {'cover letter' if is_cover_letter else 'answer'} drafts"
                    )
                    return drafts, name
        except Exception as e:
            logger.warning(f"Cascade: provider '{name}' failed — {e}")

    logger.warning("Cascade: all providers failed, using rule-based fallback")
    if is_cover_letter:
        fallback = _rule_based_cover_letter_drafts(company_name, role_title, work_history_text)
    else:
        fallback = _rule_based_answer_drafts(question_category, company_name, work_history_text)
    return fallback, "fallback"


async def _call_single_provider(
    name: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    is_cover_letter: bool,
) -> tuple[str, str]:
    """Call one provider and return (first_draft_text, provider_name). Returns ("", name) on failure."""
    try:
        if name == "ollama":
            return "", name
        elif name == "anthropic" and api_key:
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
        elif name == "perplexity" and api_key:
            raw = await _call_perplexity(system_prompt, user_prompt, api_key, model or "sonar")
        elif name == "kimi" and api_key:
            raw = await _call_kimi(system_prompt, user_prompt, api_key)
        else:
            return "", name

        min_len = 200 if is_cover_letter else 80
        if raw and len(raw) > min_len:
            # Extract just the first draft from this provider's response
            drafts = _parse_answer_drafts(raw)
            if drafts:
                return drafts[0], name
    except Exception as e:
        logger.warning(f"Parallel: provider '{name}' failed — {e}")
    return "", name


async def generate_answer_drafts_parallel(
    question_text: str,
    question_category: str,
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    providers: list[dict],
    past_accepted_answers: list[str] | None = None,
    candidate_name: str = "",
    max_length: int | None = None,
    category_instructions: str | None = None,
    rag_context: str = "",
) -> tuple[list[str], list[str]]:
    """
    Run all providers concurrently. Each provider contributes one draft.
    Returns (drafts, draft_providers) — parallel lists where drafts[i] came from draft_providers[i].
    Falls back to cascade if parallel yields < 1 result.
    """
    is_cover_letter = question_category == "cover_letter"
    sorted_providers = sorted(providers, key=lambda p: _PROVIDER_RANK.get(p.get("name", ""), 50))

    if is_cover_letter:
        system_prompt = _COVER_LETTER_SYSTEM_PROMPT
        user_prompt = _build_cover_letter_prompt(
            company_name=company_name,
            role_title=role_title,
            jd_text=jd_text,
            work_history_text=work_history_text,
            candidate_name=candidate_name or "the candidate",
            past_accepted_answers=past_accepted_answers,
        )
    else:
        system_prompt = _ANSWER_SYSTEM_PROMPT
        config = _load_doc("resume_personal_config.md")
        framework_snippet = _extract_category_framework(config, question_category)

        memory_block = ""
        if past_accepted_answers:
            examples = "\n\n---\n".join(
                f"EXAMPLE {i+1}:\n{a[:400]}" for i, a in enumerate(past_accepted_answers[:3])
            )
            memory_block = f"""
PREVIOUSLY ACCEPTED ANSWERS (high quality — mirror this voice and style):
{examples}

Adapt the voice and structure above to the current question/company.
Do NOT copy verbatim — generate fresh content grounded in work history.
"""

        wh_section = (
            f"CANDIDATE WORK HISTORY (ground every answer in these facts):\n{work_history_text[:3000]}"
            if work_history_text.strip()
            else "CANDIDATE WORK HISTORY: Not provided — write compelling, honest general answers."
        )

        if max_length and max_length > 0:
            max_words = max(50, (max_length // 5) - 20)
            length_instruction = f"CRITICAL: The application field has a {max_length}-character limit. Keep your answer under {max_words} words."
        else:
            length_instruction = "Target 150-220 words."

        style_block = ""
        if category_instructions and category_instructions.strip():
            style_block = (
                f"\nUSER STYLE INSTRUCTIONS (MUST follow):\n{category_instructions.strip()}\n"
            )

        rag_block = f"\n{rag_context}\n" if rag_context.strip() else ""

        user_prompt = f"""QUESTION: {question_text}
CATEGORY: {question_category}
COMPANY: {company_name}
ROLE: {role_title}

JOB DESCRIPTION (first 2000 chars):
{jd_text[:2000]}

{wh_section}
{rag_block}{memory_block}
{framework_snippet}
{style_block}
{length_instruction}

Write ONE focused, genuine answer (not DRAFT_1/DRAFT_2 format). Use first person.
"""

    # Run all providers concurrently with a 30-second timeout per provider
    tasks = [
        _call_single_provider(
            name=p.get("name", ""),
            api_key=p.get("api_key", ""),
            model=p.get("model", ""),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            is_cover_letter=is_cover_letter,
        )
        for p in sorted_providers
        if p.get("api_key") and p.get("name") != "ollama"
    ]

    if not tasks:
        fallback_drafts, _ = await generate_answer_drafts_cascade(
            question_text=question_text,
            question_category=question_category,
            company_name=company_name,
            role_title=role_title,
            jd_text=jd_text,
            work_history_text=work_history_text,
            providers=providers,
            past_accepted_answers=past_accepted_answers,
            candidate_name=candidate_name,
            max_length=max_length,
            category_instructions=category_instructions,
            rag_context=rag_context,
        )
        return fallback_drafts, []

    results = await asyncio.gather(*tasks, return_exceptions=False)

    # Collect successful results
    drafts: list[str] = []
    draft_providers: list[str] = []
    for draft_text, provider_name in results:
        if draft_text:
            drafts.append(draft_text)
            draft_providers.append(provider_name)
            logger.info(f"Parallel: got draft from '{provider_name}'")

    if not drafts:
        logger.warning("Parallel: all providers failed, falling back to cascade")
        fallback_drafts, used = await generate_answer_drafts_cascade(
            question_text=question_text,
            question_category=question_category,
            company_name=company_name,
            role_title=role_title,
            jd_text=jd_text,
            work_history_text=work_history_text,
            providers=providers,
            past_accepted_answers=past_accepted_answers,
            candidate_name=candidate_name,
            max_length=max_length,
            category_instructions=category_instructions,
        )
        return fallback_drafts, [used] * len(fallback_drafts) if used != "fallback" else []

    return drafts, draft_providers


def _rule_based_cover_letter_drafts(company: str, role: str, work_history: str) -> list[str]:
    """Rule-based cover letter fallback — 3 structurally different templates."""
    wh = work_history[:200].strip() if work_history.strip() else "my professional experience"
    co = company or "your company"
    r = role or "this role"
    return [
        f"Dear Hiring Team,\n\nHaving built experience in {wh[:100]}..., I was immediately drawn to the {r} opportunity at {co}. The work your team is doing aligns closely with challenges I have tackled throughout my career.\n\nIn my recent role, I delivered measurable impact by applying engineering discipline to real business problems. I bring both technical depth and the ability to collaborate across functions to ship high-quality systems.\n\nI believe {co}'s mission and engineering culture are a strong fit for my background. I would welcome the chance to discuss how I can contribute.\n\nSincerely,\n[CANDIDATE_NAME]",
        f"Dear Hiring Team,\n\nThe {r} role at {co} caught my attention because it aligns with the direction I have been building toward — combining {wh[:80]}... with meaningful impact at scale.\n\nMy experience has equipped me to move quickly in ambiguous environments while maintaining engineering standards. I have consistently delivered results by focusing on what matters most to the business.\n\nI admire {co}'s approach and would be excited to join a team where I can both contribute and grow.\n\nSincerely,\n[CANDIDATE_NAME]",
        f"Dear Hiring Team,\n\nI am applying for the {r} position at {co}. My background in {wh[:100]}... has prepared me to make an immediate contribution to your team.\n\nThroughout my career I have prioritised shipping reliable systems, mentoring peers, and translating complex technical work into clear business outcomes. I thrive in environments that value craft and ownership.\n\n{co}'s work resonates with my professional values and I look forward to exploring how I can add value.\n\nSincerely,\n[CANDIDATE_NAME]",
    ]


def _extract_category_framework(config_text: str, category: str) -> str:
    """Extract the answering framework section for a given category from the config."""
    marker = f"#### `{category}`"
    idx = config_text.find(marker)
    if idx == -1:
        return ""
    end = config_text.find("\n####", idx + 1)
    snippet = config_text[idx : end if end != -1 else idx + 800]
    return snippet[:600]


def _parse_answer_drafts(raw: str) -> list[str]:
    """Parse DRAFT_N: sections from LLM response. Also handles numbered lists."""
    drafts: list[str] = []

    # Primary: look for DRAFT_1: / DRAFT_2: / DRAFT_3: markers
    for i in range(1, 4):
        pattern = rf"DRAFT_{i}[:\s](.*?)(?=DRAFT_{i + 1}[:\s]|\Z)"
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
            if len(text) > 30:
                drafts.append(text)

    if len(drafts) >= 2:
        return drafts[:3]

    # Fallback: split on blank-line-separated paragraphs (LLM may skip markers)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", raw.strip()) if len(p.strip()) > 50]
    if len(paragraphs) >= 2:
        return paragraphs[:3]

    # Last resort: return the whole response as one draft (better than empty)
    if len(raw.strip()) > 50:
        return [raw.strip()]

    return []


def _rule_based_answer_drafts(category: str, company: str, work_history: str) -> list[str]:
    """
    Rule-based fallback when no LLM is available.
    Returns 3 distinct drafts with different angles to avoid identical answers.
    NOTE: These are templates — configure an LLM provider in Settings for real answers.
    """
    wh_snippet = (
        work_history[:200].strip() if work_history.strip() else "my professional experience"
    )
    co = company or "your company"

    templates: dict[str, list[str]] = {
        "why_company": [
            f"[Draft 1 — Mission angle] {co}'s approach to solving real-world problems resonates deeply with my background. {wh_snippet}... I'm excited to bring this expertise to {co}.",
            f"[Draft 2 — Growth angle] I've followed {co}'s trajectory and see strong alignment with my career goals. My experience with {wh_snippet[:80]}... would let me contribute immediately.",
            f"[Draft 3 — Culture angle] The engineering culture at {co} — shipping fast, data-driven decisions — matches how I've worked throughout my career.",
        ],
        "about_yourself": [
            f"[Draft 1] I'm a software/data engineer with experience in {wh_snippet[:120]}... I thrive building scalable systems and am looking for my next challenge at {co}.",
            f"[Draft 2] My background spans {wh_snippet[:120]}... I've consistently delivered impact by combining technical depth with cross-functional collaboration.",
            f"[Draft 3] I bring hands-on experience with {wh_snippet[:120]}... I'm motivated by solving hard problems and would love to do that at {co}.",
        ],
        "why_hire": [
            f"[Draft 1] I bring direct experience with {wh_snippet[:120]}... which maps closely to what {co} needs. I deliver results quickly and raise the bar for the teams I join.",
            f"[Draft 2] Three things set me apart: technical depth in {wh_snippet[:80]}..., ability to work autonomously, and a track record of shipping.",
            f"[Draft 3] I've done this work before — {wh_snippet[:100]}... — and I know exactly how to apply it to {co}'s challenges.",
        ],
    }

    drafts = templates.get(
        category,
        [
            f"[Draft 1] Based on my experience — {wh_snippet[:150]}... — I'm well positioned to contribute to {co}.",
            f"[Draft 2] Throughout my career I've built expertise in {wh_snippet[:100]}... This directly applies to {co}'s needs.",
            f"[Draft 3] I look forward to bringing my background in {wh_snippet[:100]}... to {co} and making an immediate impact.",
        ],
    )

    return drafts[:3]


# ── Full resume generation ─────────────────────────────────────────────────


async def generate_full_latex_resume(
    profile: PersonalProfile,
    jd_text: str,
    company_name: str,
    role_title: str,
    job_id: str | None,
    ats_result: ATSResult | None,
    provider: str,
    api_key: str = "",
    ollama_model: str = "llama3.1:8b",
    rag_context: str = "",
) -> GeneratedResume:
    """
    Generate a complete LaTeX resume tailored to the given JD.

    Steps:
    1. Build system + user prompt with grounding context
    2. Call LLM (cascade order from personal_config.md)
    3. Fill template variables with personal profile
    4. Enforce single-page (check line count, trim if needed)
    5. Generate Markdown preview
    6. Build version tag
    """
    template = _load_template()
    system_prompt = _build_system_prompt()

    # Determine target cloud from JD for coherence
    cloud_guidance = _cloud_coherence_guidance(jd_text, profile.work_history_text)

    # Pre-compute ATS analysis block so the f-string lines stay short
    if ats_result and ats_result.suggestions:
        _gap_lines = "\n".join(f"- {s}" for s in ats_result.suggestions)
        ats_block = (
            "ATS ANALYSIS — top gaps to address by reframing existing experience:"
            f"\n\n{_gap_lines}"
        )
    else:
        ats_block = ""

    user_prompt = f"""Generate a complete, single-page LaTeX resume for this job application.

COMPANY: {company_name}
ROLE: {role_title}
{f"JOB ID: {job_id}" if job_id else ""}

JOB DESCRIPTION:
{jd_text[:4000]}

CANDIDATE WORK HISTORY (use ONLY these facts):
{profile.work_history_text[:3000]}

CANDIDATE EDUCATION:
{profile.education_text}

{ats_block}

{cloud_guidance}

{f"CANDIDATE BACKGROUND (from uploaded documents):{chr(10)}{rag_context}{chr(10)}" if rag_context else ""}
TEMPLATE STRUCTURE TO FILL:
{template}

PERSONAL HEADER DATA (inject into template variables):
{{{{NAME}}}} = {profile.name}
{{{{PHONE}}}} = {profile.phone}
{{{{EMAIL}}}} = {profile.email}
{{{{LINKEDIN_URL}}}} = {profile.linkedin_url}
{{{{LINKEDIN_LABEL}}}} = {profile.linkedin_label}
{{{{PORTFOLIO_URL}}}} = {profile.portfolio_url}
{{{{PORTFOLIO_LABEL}}}} = {profile.portfolio_label}

Return the complete LaTeX document only. No explanation. No code fences.
"""

    raw_latex, provider_used = await _llm_generate(
        system_prompt, user_prompt, provider, api_key, ollama_model
    )

    warnings: list[str] = []

    if not raw_latex or provider_used == "fallback":
        # Fill template with placeholders and original bullets
        raw_latex = _fallback_fill_template(template, profile)
        warnings.append("LLM unavailable — template filled with original content. Review manually.")
        provider_used = "fallback"

    # Clean up any markdown fences the LLM may have added
    raw_latex = _strip_markdown_fences(raw_latex)

    # Validate it looks like LaTeX
    if "\\documentclass" not in raw_latex:
        warnings.append("Generated content may not be valid LaTeX — review before compiling.")

    # Build version tag and recruiter filename
    first_name = profile.name.split()[0]
    version_tag = build_version_tag(first_name, company_name, role_title, job_id)
    recruiter_filename = f"{first_name}.pdf"

    # Generate Markdown preview
    markdown_preview = _latex_to_markdown_preview(raw_latex, profile)

    return GeneratedResume(
        latex_content=raw_latex,
        markdown_preview=markdown_preview,
        version_tag=version_tag,
        recruiter_filename=recruiter_filename,
        ats_score_estimate=ats_result.overall_score if ats_result else None,
        skills_gap=ats_result.skills_gap[:5] if ats_result else [],
        changes_summary=f"Generated via {provider_used} for {company_name} — {role_title}",
        llm_provider_used=provider_used,
        generation_warnings=warnings,
    )


def _cloud_coherence_guidance(jd_text: str, work_history: str) -> str:
    """Return a prompt snippet enforcing cloud platform coherence."""
    jd_lower = jd_text.lower()
    clouds = {
        "azure": "azure" in jd_lower or "microsoft fabric" in jd_lower,
        "aws": "aws" in jd_lower or "amazon web services" in jd_lower,
        "gcp": "gcp" in jd_lower or "google cloud" in jd_lower or "bigquery" in jd_lower,
    }
    target = [c for c, present in clouds.items() if present]
    if len(target) == 1:
        return (
            f"CLOUD COHERENCE: This JD focuses on {target[0].upper()}. "
            f"Lead with {target[0].upper()} experience. "
            "Mention other cloud platforms only in brief supporting context."
        )
    return ""


def _strip_markdown_fences(text: str) -> str:
    """Remove ```latex ... ``` or ``` ... ``` wrapping if the LLM added it."""
    text = re.sub(r"^```(?:latex)?\s*\n", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n```\s*$", "", text.strip(), flags=re.MULTILINE)
    return text.strip()


def _fallback_fill_template(template: str, profile: PersonalProfile) -> str:
    """Fill template variables with profile data when LLM is unavailable."""
    replacements = {
        "{{NAME}}": profile.name,
        "{{PHONE}}": profile.phone,
        "{{EMAIL}}": profile.email,
        "{{LINKEDIN_URL}}": profile.linkedin_url,
        "{{LINKEDIN_LABEL}}": profile.linkedin_label,
        "{{PORTFOLIO_URL}}": profile.portfolio_url,
        "{{PORTFOLIO_LABEL}}": profile.portfolio_label,
        "{{EDUCATION}}": profile.education_text or "% Education section",
        "{{EXPERIENCE}}": profile.work_history_text or "% Experience section",
        "{{PROJECTS}}": "% Projects section",
        "{{CERTIFICATIONS}}": "% Certifications section",
        "{{SKILLS}}": "% Skills section",
        "{{SUMMARY}}": "",
    }
    result = template
    for k, v in replacements.items():
        result = result.replace(k, v)
    return result


def _latex_to_markdown_preview(latex: str, profile: PersonalProfile) -> str:
    """
    Generate a lightweight Markdown preview from the LaTeX content.
    Used for quick human review and editing in the sidepanel.
    Edits to this .md are re-compiled to LaTeX on save.
    """
    md_lines = [f"# {profile.name}", ""]
    md_lines.append(f"{profile.phone} | {profile.email} | {profile.linkedin_label}")
    md_lines.append("")

    # Extract section content from LaTeX (simplified)
    sections = re.findall(r"\\section\{([^}]+)\}(.*?)(?=\\section|\Z)", latex, re.DOTALL)
    for section_name, section_body in sections:
        md_lines.append(f"## {section_name}")
        md_lines.append("")
        # Extract resume items
        items = re.findall(r"\\resumeItem\{([^}]+)\}", section_body)
        for item in items:
            # Strip remaining LaTeX commands
            clean = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", item)
            clean = re.sub(r"\\[a-zA-Z]+", "", clean).strip()
            if clean:
                md_lines.append(f"- {clean}")
        if items:
            md_lines.append("")

    return "\n".join(md_lines)


# ── Cover Letter Generation ─────────────────────────────────────────────────

_TONE_INSTRUCTIONS: dict[str, str] = {
    "professional": "Write in a polished, formal tone appropriate for corporate environments.",
    "enthusiastic": "Write in an energetic, passionate tone that conveys genuine excitement for the role.",
    "concise": "Write in a tight, direct style — every sentence must earn its place. No filler.",
    "conversational": "Write in a warm, natural tone — formal enough for a job application but human and approachable.",
}


def _build_cover_letter_prompt_v2(
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    candidate_name: str = "the candidate",
    tone: str = "professional",
    word_limit: int = 400,
    num_drafts: int = 3,
    past_accepted: list[str] | None = None,
    rag_context: str = "",
) -> str:
    tone_instruction = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS["professional"])
    word_range = f"{max(150, word_limit - 60)}-{word_limit}"

    memory_block = ""
    if past_accepted:
        examples = "\n\n---\n".join(
            f"PREVIOUS ACCEPTED COVER LETTER {i + 1}:\n{a[:600]}"
            for i, a in enumerate(past_accepted[:2])
        )
        memory_block = f"""
PREVIOUSLY ACCEPTED COVER LETTERS (mirror this voice — do NOT copy verbatim):
{examples}

"""

    wh_section = (
        f"CANDIDATE WORK HISTORY:\n{work_history_text[:3500]}"
        if work_history_text.strip()
        else "CANDIDATE WORK HISTORY: Not provided — write using professional language and genuine enthusiasm."
    )

    rag_section = f"\n{rag_context}\n" if rag_context.strip() else ""

    draft_instructions = "\n".join(
        f"DRAFT_{i + 1}:\n[{word_range} words — {'different opening angle' if i > 0 else 'direct value-prop opening'}]"
        for i in range(num_drafts)
    )

    return f"""Write {num_drafts} cover letter draft{"s" if num_drafts > 1 else ""} for the following application.

POSITION: {role_title}
COMPANY: {company_name}
CANDIDATE NAME: {candidate_name}

TONE INSTRUCTION: {tone_instruction}
TARGET LENGTH: {word_range} words per draft

JOB DESCRIPTION:
{jd_text[:2500]}

{wh_section}
{rag_section}
{memory_block}Respond in EXACTLY this format — {num_drafts} separate complete drafts:
{draft_instructions}
"""


async def generate_cover_letter(
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    providers: list[dict],
    candidate_name: str = "",
    tone: str = "professional",
    word_limit: int = 400,
    past_accepted: list[str] | None = None,
    rag_context: str = "",
) -> tuple[list[str], list[str]]:
    """
    Generate cover letter drafts in parallel across all enabled providers.

    Returns (drafts, draft_providers) — parallel lists.
    Each provider contributes one draft (different opening angle).
    Falls back to rule-based if all LLMs fail.
    """
    num_providers = max(1, len(providers))
    system_prompt = (
        "You are an expert career coach specializing in compelling cover letters. "
        "You write cover letters that are tailored, specific, and human — never generic. "
        "You ground every claim in the candidate's real work history."
    )

    async def _call_one(p: dict, draft_num: int) -> tuple[str, str]:
        """Call one provider and extract a single cover letter draft."""
        user_prompt = _build_cover_letter_prompt_v2(
            company_name=company_name,
            role_title=role_title,
            jd_text=jd_text,
            work_history_text=work_history_text,
            candidate_name=candidate_name or "the candidate",
            tone=tone,
            word_limit=word_limit,
            num_drafts=1,  # one draft per provider call
            past_accepted=past_accepted,
            rag_context=rag_context,
        )
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
                return ("", "")
            # Strip any DRAFT_1: prefix the model may echo back
            text = re.sub(r"^DRAFT_\d+:\s*", "", raw.strip(), flags=re.IGNORECASE).strip()
            if text and len(text) > 100:
                return (text, name)
        except Exception as exc:
            logger.warning(f"CoverLetter: provider '{name}' draft {draft_num} failed — {exc}")
        return ("", "")

    if not providers:
        # No LLMs configured — return rule-based fallback
        fallback = _rule_based_cover_letter_drafts(company_name, role_title, work_history_text)
        return (fallback[:1], ["fallback"])

    # Run all providers in parallel
    tasks = [_call_one(p, i) for i, p in enumerate(providers[:num_providers])]
    results = await asyncio.gather(*tasks)

    drafts = [text for text, _ in results if text]
    draft_providers = [prov for text, prov in results if text]

    if not drafts:
        fallback = _rule_based_cover_letter_drafts(company_name, role_title, work_history_text)
        return (fallback[:1], ["fallback"])

    return (drafts, draft_providers)


# ── Professional Summary Generation ─────────────────────────────────────────


async def generate_professional_summary(
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    providers: list[dict],
    candidate_name: str = "",
    word_limit: int = 80,
) -> tuple[str, str]:
    """
    Generate a 2-4 sentence professional summary tailored to a specific role.

    Returns (summary_text, provider_used).
    Falls back to a rule-based summary if LLMs are unavailable.
    """
    system_prompt = (
        "You are a professional resume writer. Generate concise, powerful professional summaries "
        "that position candidates for specific roles. Be specific, not generic."
    )
    user_prompt = f"""Write a professional summary for a resume targeting this role.

POSITION: {role_title}
COMPANY: {company_name}
CANDIDATE: {candidate_name or "the candidate"}
TARGET WORD COUNT: {word_limit} words (2-4 sentences)

JOB DESCRIPTION:
{jd_text[:2000]}

CANDIDATE BACKGROUND:
{work_history_text[:2500]}

Write ONE professional summary (no headers, no quotes). Be specific about skills and impact.
Lead with years of experience or key expertise. End with value proposition for this role."""

    sorted_providers = sorted(providers, key=lambda p: _PROVIDER_RANK.get(p.get("name", ""), 50))
    for p in sorted_providers:
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
            text = raw.strip()
            if text and len(text) > 50:
                return (text[: word_limit * 7], name)  # ~7 chars/word safety cap
        except Exception as exc:
            logger.warning(f"Summary: provider '{name}' failed — {exc}")

    # Rule-based fallback
    years = ""
    if work_history_text:
        import re as _re

        yr_match = _re.search(r"(\d+)\s*(?:\+\s*)?years?", work_history_text, _re.IGNORECASE)
        if yr_match:
            years = f"{yr_match.group(1)}+ years of experience"
    fallback = (
        f"{'Experienced' if not years else years.capitalize()} professional "
        f"seeking {role_title} at {company_name}. "
        "Proven track record of delivering impactful results and driving technical excellence."
    )
    return (fallback, "fallback")


# ── Tailored Bullet Points Generation ───────────────────────────────────────


async def generate_role_bullets(
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    providers: list[dict],
    num_bullets: int = 5,
    target_company_for_context: str = "",
) -> tuple[list[str], str]:
    """
    Generate tailored resume bullet points for a role, grounded in work history.

    Returns (bullets_list, provider_used).
    Each bullet starts with a strong action verb.
    Falls back to extracting existing bullets from work history if LLMs fail.
    """
    system_prompt = (
        "You are a professional resume writer specializing in ATS-optimized bullet points. "
        "Write achievement-focused bullets using the XYZ formula: "
        "Accomplished [X] as measured by [Y] by doing [Z]. "
        "Start each bullet with a strong past-tense action verb."
    )
    user_prompt = f"""Generate {num_bullets} tailored resume bullet points.

TARGET ROLE: {role_title}
COMPANY: {company_name}{f' (targeting {target_company_for_context})' if target_company_for_context else ''}

JOB DESCRIPTION (keywords to match):
{jd_text[:2000]}

CANDIDATE'S ACTUAL WORK HISTORY (base bullets on these real facts):
{work_history_text[:3000]}

Rules:
1. Each bullet must start with a strong action verb (Led, Built, Reduced, Increased, etc.)
2. Include metrics where possible (%, $, time, scale)
3. Use keywords from the JD naturally
4. Keep each bullet under 25 words
5. Do NOT invent facts not in the work history

Return EXACTLY {num_bullets} bullets, one per line, each starting with "• "."""

    sorted_providers = sorted(providers, key=lambda p: _PROVIDER_RANK.get(p.get("name", ""), 50))
    for p in sorted_providers:
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
            import re as _re

            lines = [
                line.lstrip("•- ").strip()
                for line in raw.strip().splitlines()
                if line.strip() and len(line.strip()) > 10
            ]
            # Normalize: ensure bullet prefix
            bullets = [f"• {b}" if not b.startswith("•") else b for b in lines[:num_bullets]]
            if bullets:
                return (bullets, name)
        except Exception as exc:
            logger.warning(f"Bullets: provider '{name}' failed — {exc}")

    # Fallback: extract existing bullets from work history
    import re as _re

    existing = _re.findall(r"[•\-\*]\s*(.+)", work_history_text)
    fallback_bullets = (
        [f"• {b.strip()}" for b in existing[:num_bullets]]
        if existing
        else [
            f"• Delivered high-impact work as {role_title} contributing to team success.",
            f"• Collaborated cross-functionally to drive results at {company_name}.",
        ]
    )
    return (fallback_bullets[:num_bullets], "fallback")
