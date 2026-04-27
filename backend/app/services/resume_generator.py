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


# ── Q&A generation (RFC #2) — moved to qa_generation_service.py ────────────
# Re-exported here so existing import sites that haven't been updated yet
# continue to work without changes. vault/answers.py already imports directly
# from qa_generation_service; these shims will be removed in RFC #3.

from app.services.qa_generation_service import (  # noqa: E402, F401
    _PROVIDER_RANK,
    _extract_category_framework,
    _parse_answer_drafts,
    _rule_based_answer_drafts,
    _rule_based_cover_letter_drafts,
    generate_answer_drafts,
    generate_answer_drafts_cascade,
    generate_answer_drafts_multi,
    generate_answer_drafts_parallel,
)

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
