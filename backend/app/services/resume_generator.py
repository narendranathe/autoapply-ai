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
    elif provider == "kimi" and api_key:
        cascade.append(("kimi", lambda: _call_kimi(system_prompt, user_prompt, api_key)))
    elif provider == "ollama":
        cascade.append(("ollama", lambda: _call_ollama(system_prompt, user_prompt, ollama_model)))

    # Always add Ollama as last resort before fallback
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
    """Parse 3 DRAFT_N: sections from LLM response."""
    drafts: list[str] = []
    for i in range(1, 4):
        pattern = rf"DRAFT_{i}:\s*(.*?)(?=DRAFT_{i+1}:|$)"
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            text = match.group(1).strip()
            if len(text) > 20:
                drafts.append(text)
    # Pad to 3 if LLM returned fewer
    while len(drafts) < 3 and drafts:
        drafts.append(drafts[0])
    return drafts[:3]


def _rule_based_answer_drafts(category: str, company: str, work_history: str) -> list[str]:
    """Minimal fallback when no LLM is available."""
    base = (
        f"Based on my experience in data engineering, I have developed strong skills "
        f"that align well with {company}'s needs. {work_history[:100]}... "
        f"I look forward to contributing to {company}'s mission."
    )
    return [base, base, base]


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
