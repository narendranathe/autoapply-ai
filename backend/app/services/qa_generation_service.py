"""
Q&A Generation Service — generates draft answers to open-ended job application questions.

Extracted from resume_generator.py (RFC #2) so that Q&A generation and resume tailoring
can evolve, be tested, and be scaled independently.  vault/answers.py no longer needs to
import from a module named "resume generator".

Responsible for:
  generate_answer_drafts          — single-provider, LLMGateway cascade (3 drafts)
  generate_answer_drafts_cascade  — try providers in priority order; first winner → 3 drafts
  generate_answer_drafts_parallel — all providers concurrently; each contributes 1 draft
  generate_answer_drafts_multi    — legacy parallel variant (1 draft per provider)
  _rule_based_answer_drafts       — LLM-free fallback for standard Q&A
  _rule_based_cover_letter_drafts — LLM-free fallback for cover letters
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from loguru import logger

from app.services.llm_gateway import (
    LLMGateway,
    _call_anthropic,
    _call_gemini,
    _call_groq,
    _call_kimi,
    _call_ollama,
    _call_openai,
    _call_perplexity,
)

# ── Document loader ────────────────────────────────────────────────────────

_DOCS_ROOT = Path(__file__).parent.parent.parent.parent / "docs"


def _load_doc(filename: str) -> str:
    path = _DOCS_ROOT / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning(f"Instruction file not found: {path}")
    return ""


# ── LLM gateway (for generate_answer_drafts single-provider path) ──────────

_qa_llm_gateway = LLMGateway()


async def _llm_generate(
    system_prompt: str,
    user_prompt: str,
    provider: str,
    api_key: str = "",
    ollama_model: str = "llama3.1:8b",
) -> tuple[str, str]:
    """Delegate to LLMGateway — single source of truth for provider dispatch."""
    return await _qa_llm_gateway.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        provider=provider,
        api_key=api_key,
        ollama_model=ollama_model,
    )


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

# ── System prompts ─────────────────────────────────────────────────────────

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

# ── Prompt helpers ─────────────────────────────────────────────────────────


def _build_cover_letter_prompt(
    company_name: str,
    role_title: str,
    jd_text: str,
    work_history_text: str,
    candidate_name: str = "the candidate",
    past_accepted_answers: list[str] | None = None,
) -> str:
    """Build the user prompt for cover letter generation (used in cascade/parallel Q&A paths)."""
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


# ── Parsers and rule-based fallbacks ───────────────────────────────────────


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


# ── Q&A generation functions ───────────────────────────────────────────────


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
