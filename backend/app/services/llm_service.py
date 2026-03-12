"""
BYOK LLM Service — Bring Your Own Key.

Users provide their own OpenAI/Anthropic API keys.
We provide the intelligence: prompt templates + validation.

ARCHITECTURE:
1. User's API key is decrypted from database
2. We construct the prompt using our templates (our IP)
3. The Chrome extension calls the LLM directly with the user's key
4. OR the backend proxies the call (for logging/validation)

FALLBACK:
If the LLM is unavailable (circuit breaker open, invalid key, rate limited),
we fall back to keyword-based matching — free, offline, deterministic.

COST MODEL:
- User pays for LLM calls directly (their key, their bill)
- We pay $0 for LLM compute
- We add value through prompt engineering + validation
"""

import re
from abc import ABC, abstractmethod
from enum import Enum

import httpx
from loguru import logger

from app.middleware.circuit_breaker import CircuitOpenError, llm_circuit
from app.services.resume_parser import ResumeAST
from app.utils.encryption import decrypt_value


class RewriteStrategy(str, Enum):
    """
    How aggressively to rewrite the resume.

    Determined by similarity score to previous applications:
    - SLIGHT_TWEAK: >85% similar to a previous application
    - MODERATE: 60-85% similar
    - GROUND_UP: <60% similar (new domain/role)
    """

    SLIGHT_TWEAK = "slight_tweak"
    MODERATE = "moderate"
    GROUND_UP = "ground_up"


# ══════════════════════════════════════════════════════════════
# PROMPT TEMPLATES
# These are your intellectual property. They encode the
# anti-hallucination rules directly into the LLM instructions.
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a resume optimization expert. You help job seekers
rephrase their existing resume bullet points to better match specific job descriptions.

ABSOLUTE RULES — VIOLATION OF ANY RULE MAKES YOUR OUTPUT INVALID:
1. Return EXACTLY the same number of bullet points as the input
2. NEVER add skills, technologies, or tools not in the original
3. NEVER change dates, company names, school names, or job titles
4. NEVER add metrics, percentages, or numbers not in the original
5. NEVER invent achievements, awards, or responsibilities
6. Each output bullet must be clearly derived from its corresponding input bullet
7. Return ONLY the rephrased bullets, one per line, no numbering or labels
8. Preserve the order — bullet 1 maps to bullet 1, bullet 2 to bullet 2, etc.

You CAN:
- Reorder words within a bullet for emphasis
- Replace generic verbs with action verbs from the job description
- Use terminology and keywords from the job description
- Adjust tone to match the company's voice
- Combine or split clauses within a SINGLE bullet (but output count stays same)
"""

REWRITE_PROMPT_TEMPLATE = """REWRITE STRATEGY: {strategy_description}

JOB DESCRIPTION:
{job_description}

ORIGINAL RESUME BULLETS (rephrase each one, maintaining order):
{resume_context}

Return EXACTLY {bullet_count} rephrased bullets, one per line.
Do NOT include numbers, dashes, bullet characters, or labels.
Each line should be the raw rephrased text only."""

STRATEGY_DESCRIPTIONS = {
    RewriteStrategy.SLIGHT_TWEAK: (
        "SLIGHT TWEAK — Make minimal changes. Change 1-3 keywords per bullet "
        "to use terminology from the job description. Preserve sentence structure."
    ),
    RewriteStrategy.MODERATE: (
        "MODERATE REWRITE — Restructure sentences to lead with JD-relevant "
        "action verbs. Reframe responsibilities using JD terminology. "
        "Keep all facts identical."
    ),
    RewriteStrategy.GROUND_UP: (
        "COMPREHENSIVE REPHRASE — Significantly restructure each bullet to "
        "maximize alignment with the job description. Change sentence structure, "
        "emphasis, and framing. But keep ALL facts, dates, and metrics identical."
    ),
}


# ══════════════════════════════════════════════════════════════
# LLM PROVIDERS
# ══════════════════════════════════════════════════════════════


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str) -> str:
        """Send a completion request and return the text response."""
        pass

    @abstractmethod
    def validate_key_format(self, api_key: str) -> bool:
        """Check if the API key has the right format (not if it's valid)."""
        pass


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    @llm_circuit
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-5-20250929",
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "temperature": 0.3,  # Low temp for consistency
                },
            )

            if response.status_code == 401:
                raise InvalidAPIKeyError("Anthropic API key is invalid or expired")
            if response.status_code == 429:
                raise RateLimitError("Anthropic rate limit exceeded")

            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    def validate_key_format(self, api_key: str) -> bool:
        return api_key.startswith("sk-ant-") and len(api_key) > 20


class OpenAIProvider(LLMProvider):
    """OpenAI GPT API provider."""

    @llm_circuit
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
            )

            if response.status_code == 401:
                raise InvalidAPIKeyError("OpenAI API key is invalid or expired")
            if response.status_code == 429:
                raise RateLimitError("OpenAI rate limit exceeded")

            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def validate_key_format(self, api_key: str) -> bool:
        return api_key.startswith("sk-") and len(api_key) > 20


class KimiProvider(LLMProvider):
    """
    Kimi (Moonshot AI) provider.
    Best for very long-context JDs (32K token window).
    Model: moonshot-v1-32k
    """

    @llm_circuit
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str) -> str:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "moonshot-v1-32k",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
            )

            if response.status_code == 401:
                raise InvalidAPIKeyError("Kimi API key is invalid or expired")
            if response.status_code == 429:
                raise RateLimitError("Kimi rate limit exceeded")

            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def validate_key_format(self, api_key: str) -> bool:
        return len(api_key) > 10  # Kimi keys don't have a fixed prefix


class PerplexityProvider(LLMProvider):
    """
    Perplexity AI — free tier with internet-search-augmented models.
    Default model: sonar (fast, free, web-grounded).
    Get API key at: https://www.perplexity.ai/settings/api
    """

    def __init__(self, model: str = "sonar"):
        self.model = model

    @llm_circuit
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
            )
            if response.status_code == 401:
                raise InvalidAPIKeyError("Perplexity API key is invalid or expired")
            if response.status_code == 429:
                raise RateLimitError("Perplexity rate limit exceeded")
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    def validate_key_format(self, api_key: str) -> bool:
        return api_key.startswith("pplx-") and len(api_key) > 20


class GroqProvider(LLMProvider):
    """
    Groq Cloud — free tier, OpenAI-compatible.
    Best free option for production: fast inference, no cost.
    Default model: llama-3.3-70b-versatile (free tier).
    Get API key at: https://console.groq.com
    """

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        self.model = model

    @llm_circuit
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
            )
            if response.status_code == 401:
                raise InvalidAPIKeyError("Groq API key is invalid or expired")
            if response.status_code == 429:
                raise RateLimitError("Groq rate limit exceeded")
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    def validate_key_format(self, api_key: str) -> bool:
        return api_key.startswith("gsk_") and len(api_key) > 20


class GeminiProvider(LLMProvider):
    """
    Google Gemini — free tier via AI Studio, no credit card required.
    Get API key at: https://aistudio.google.com
    Default model: gemini-1.5-flash (1 500 req/day free).
    Uses the OpenAI-compatible endpoint so no extra SDK needed.
    """

    def __init__(self, model: str = "gemini-1.5-flash"):
        self.model = model

    @llm_circuit
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                },
            )
            if response.status_code == 400:
                raise InvalidAPIKeyError("Gemini API key is invalid")
            if response.status_code == 429:
                raise RateLimitError("Gemini rate limit exceeded")
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    def validate_key_format(self, api_key: str) -> bool:
        return api_key.startswith("AIza") and len(api_key) > 20


class OllamaProvider(LLMProvider):
    """
    Ollama local LLM provider — no API key required.
    Recommended model: llama3.1:8b (strong at structured LaTeX generation).
    Requires Ollama running at http://localhost:11434.
    """

    def __init__(self, model: str = "llama3.1:8b"):
        self.model = model

    @llm_circuit
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str = "") -> str:
        async with httpx.AsyncClient(timeout=180.0) as client:
            from app.config import settings

            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": self.model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 4096},
                },
            )

            if response.status_code == 404:
                raise InvalidAPIKeyError(
                    f"Ollama model '{self.model}' not found. " f"Run: ollama pull {self.model}"
                )

            response.raise_for_status()
            return response.json()["response"]

    def validate_key_format(self, api_key: str) -> bool:
        return True  # Ollama doesn't need a key


class KeywordFallback(LLMProvider):
    """
    Free, offline fallback when LLM is unavailable.

    Instead of rewriting bullets, it:
    1. Extracts keywords from the job description
    2. Scores each resume bullet by keyword overlap
    3. Returns original bullets sorted by relevance

    Not as powerful as LLM rewriting, but:
    - Always available (no API key needed)
    - Free (no cost)
    - Deterministic (same input = same output)
    - Zero hallucination risk
    """

    async def complete(self, system_prompt: str, user_prompt: str, api_key: str = "") -> str:
        logger.info("Using keyword fallback — LLM unavailable")
        # Return a marker that tells the caller we used fallback
        return "__FALLBACK_MODE__"

    def validate_key_format(self, api_key: str) -> bool:
        return True  # Fallback doesn't need a key

    def score_bullets_by_relevance(
        self, bullets: list[str], job_description: str
    ) -> list[tuple[str, float]]:
        """
        Score each bullet by keyword overlap with JD.

        Returns list of (bullet_text, relevance_score) tuples.
        """
        # Extract JD keywords (words that appear frequently)
        jd_words = set(job_description.lower().split())
        # Remove common stop words
        stop_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "shall",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "and",
            "or",
            "but",
            "not",
            "no",
            "this",
            "that",
            "these",
            "those",
            "we",
            "you",
            "they",
            "our",
            "your",
            "their",
        }
        jd_keywords = jd_words - stop_words

        scored: list[tuple[str, float]] = []
        for bullet in bullets:
            bullet_words = set(bullet.lower().split())
            overlap = bullet_words & jd_keywords
            score = len(overlap) / max(len(jd_keywords), 1)
            scored.append((bullet, score))

        return scored


# ══════════════════════════════════════════════════════════════
# CUSTOM EXCEPTIONS
# ══════════════════════════════════════════════════════════════


class InvalidAPIKeyError(Exception):
    """Raised when user's API key is invalid."""

    pass


class RateLimitError(Exception):
    """Raised when LLM provider rate limits us."""

    pass


class LLMUnavailableError(Exception):
    """Raised when LLM is down and we're using fallback."""

    pass


# ══════════════════════════════════════════════════════════════
# PROVIDER REGISTRY
# ══════════════════════════════════════════════════════════════

PROVIDERS: dict[str, LLMProvider] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(model="gemini-1.5-flash"),
    "groq": GroqProvider(model="llama-3.3-70b-versatile"),
    "perplexity": PerplexityProvider(model="sonar"),
    "kimi": KimiProvider(),
    "ollama": OllamaProvider(model="llama3.1:8b"),
    "fallback": KeywordFallback(),
}


def get_provider(name: str) -> LLMProvider:
    """Get an LLM provider by name. Falls back to keyword matching."""
    return PROVIDERS.get(name, PROVIDERS["fallback"])


# ══════════════════════════════════════════════════════════════
# MAIN TAILORING FUNCTION
# ══════════════════════════════════════════════════════════════


async def tailor_resume(
    resume_ast: ResumeAST,
    job_description: str,
    strategy: RewriteStrategy,
    provider_name: str,
    encrypted_api_key: str,
) -> tuple[list[str], bool, str]:
    """
    Main entry point for resume tailoring.

    Args:
        resume_ast: Parsed original resume
        job_description: The job description to tailor for
        strategy: How aggressively to rewrite
        provider_name: "anthropic" | "openai" | "fallback"
        encrypted_api_key: Fernet-encrypted API key from database

    Returns:
        tuple of:
        - list[str]: Rewritten bullet texts (same count as original)
        - bool: True if fallback was used (LLM unavailable)
        - str: Summary of changes made
    """
    provider = get_provider(provider_name)

    # ── Decrypt API key ───────────────────────────────────
    api_key = ""
    if encrypted_api_key and provider_name != "fallback":
        try:
            api_key = decrypt_value(encrypted_api_key)
        except Exception as e:
            logger.error(f"Failed to decrypt API key: {e}")
            provider = PROVIDERS["fallback"]

    # ── Validate key format ───────────────────────────────
    if api_key and not provider.validate_key_format(api_key):
        logger.warning(f"Invalid API key format for {provider_name}")
        provider = PROVIDERS["fallback"]

    # ── Build the prompt ──────────────────────────────────
    user_prompt = REWRITE_PROMPT_TEMPLATE.format(
        strategy_description=STRATEGY_DESCRIPTIONS[strategy],
        job_description=job_description[:4000],  # Truncate long JDs
        resume_context=resume_ast.to_prompt_context(),
        bullet_count=resume_ast.bullet_count,
    )

    # ── Call the LLM ──────────────────────────────────────
    try:
        raw_response = await provider.complete(SYSTEM_PROMPT, user_prompt, api_key)

        # Check for fallback marker
        if raw_response == "__FALLBACK_MODE__":
            return (
                [b.text for b in resume_ast.bullets],
                True,
                "LLM unavailable. Showing original bullets with keyword relevance scores.",
            )

        # Parse the response into individual bullets
        rewritten_bullets = _parse_llm_response(raw_response, resume_ast.bullet_count)

        summary = (
            f"Rewrote {len(rewritten_bullets)} bullets using {strategy.value} strategy "
            f"via {provider_name}."
        )

        return rewritten_bullets, False, summary

    except CircuitOpenError as e:
        logger.warning(f"Circuit open for {provider_name}: {e}")
        return (
            [b.text for b in resume_ast.bullets],
            True,
            "LLM service temporarily unavailable (circuit open). Showing original.",
        )

    except InvalidAPIKeyError:
        logger.warning(f"Invalid API key for {provider_name}")
        return (
            [b.text for b in resume_ast.bullets],
            True,
            f"API key for {provider_name} is invalid. Please update in settings.",
        )

    except RateLimitError:
        logger.warning(f"Rate limited by {provider_name}")
        return (
            [b.text for b in resume_ast.bullets],
            True,
            f"Rate limited by {provider_name}. Try again in a few minutes.",
        )

    except Exception as e:
        logger.error(f"LLM call failed: {e}", exc_info=True)
        return (
            [b.text for b in resume_ast.bullets],
            True,
            f"LLM error: {str(e)[:100]}. Showing original bullets.",
        )


def _parse_llm_response(raw_response: str, expected_count: int) -> list[str]:
    """
    Parse the LLM's raw text response into individual bullets.

    The LLM is instructed to return one bullet per line.
    We clean up any formatting it adds (numbers, dashes, etc.)
    """
    lines = raw_response.strip().split("\n")

    # Clean each line
    bullets: list[str] = []
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue

        # Remove common LLM formatting artifacts
        # "1. ", "- ", "• ", "BULLET_0: ", etc.
        cleaned = re.sub(r"^(\d+[.)]\s*|[-•●]\s*|BULLET_\d+:\s*)", "", cleaned)
        cleaned = cleaned.strip()

        if cleaned and len(cleaned) > 5:
            bullets.append(cleaned)

    # If we got more bullets than expected, try to trim
    if len(bullets) > expected_count:
        logger.warning(f"LLM returned {len(bullets)} bullets, expected {expected_count}. Trimming.")
        bullets = bullets[:expected_count]

    # If we got fewer, log warning (validator will catch this)
    if len(bullets) < expected_count:
        logger.warning(f"LLM returned {len(bullets)} bullets, expected {expected_count}.")

    return bullets
