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
    """
    cascade = []

    if provider == "anthropic" and api_key:
        cascade.append(("anthropic", lambda: _call_anthropic(system_prompt, user_prompt, api_key)))
    elif provider == "openai" and api_key:
        cascade.append(("openai", lambda: _call_openai(system_prompt, user_prompt, api_key)))
    elif provider == "groq" and api_key:
        cascade.append(("groq", lambda: _call_groq(system_prompt, user_prompt, api_key)))
    elif provider == "kimi" and api_key:
        cascade.append(("kimi", lambda: _call_kimi(system_prompt, user_prompt, api_key)))
    elif provider == "ollama":
        cascade.append(("ollama", lambda: _call_ollama(system_prompt, user_prompt, ollama_model)))

    # Always try Ollama as local fallback before giving up (only if not already first)
    if provider != "ollama":
        cascade.append(("ollama", lambda: _call_ollama(system_prompt, user_prompt, ollama_model)))

    for name, call in cascade:
        try:
            result = await call()
            if result and len(result) > 200:
                return result, name
        except Exception as e:
            logger.warning(f"LLM provider {name} failed: {e}")

    return "", "fallback"


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

    user_prompt = f"""QUESTION: {question_text}
CATEGORY: {question_category}
COMPANY: {company_name}
ROLE: {role_title}

JOB DESCRIPTION (first 2000 chars):
{jd_text[:2000]}

CANDIDATE WORK HISTORY (use ONLY these facts — no fabrication):
{work_history_text[:3000]}

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

        user_prompt = f"""QUESTION: {question_text}
CATEGORY: {question_category}
COMPANY: {company_name}
ROLE: {role_title}

JOB DESCRIPTION (first 2000 chars):
{jd_text[:2000]}

{wh_section}

ANSWERING FRAMEWORK FOR THIS CATEGORY:
{framework_snippet}
{memory_block}
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
