"""
LLMGateway — single source of truth for LLM provider dispatch.

Merged from llm_service.py (issue #146 / PRD #144).
All LLM logic now lives here: HTTP callers, provider classes, BYOK
tailoring pipeline, exceptions, and the gateway cascade class.

Supported providers
-------------------
anthropic  | Anthropic claude-sonnet-4-6
openai     | OpenAI gpt-4o
groq       | Groq llama-3.3-70b-versatile (free tier)
kimi       | Moonshot moonshot-v1-32k   (long-context)
gemini     | Google Gemini 1.5 Flash    (free tier)
perplexity | Perplexity sonar           (web-grounded)
ollama     | Local Ollama               (no key needed)
fallback   | Always-available keyword fallback
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import Enum

import httpx
from loguru import logger

from app.config import settings
from app.middleware.circuit_breaker import CircuitOpenError, llm_circuit
from app.services.resume_parser import ResumeAST
from app.utils.encryption import decrypt_value

# ── Low-level HTTP callers (mirrors resume_generator private functions) ──────


async def _call_anthropic(
    system: str, user: str, api_key: str, model: str = "claude-sonnet-4-6"
) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
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


# ── Gateway class ────────────────────────────────────────────────────────────

# Minimum response length to be considered a real answer (not an empty/noise reply)
_MIN_RESPONSE_LEN = 200


class LLMGateway:
    """
    Single dispatch point for all LLM calls in the application.

    Usage::

        gw = LLMGateway()
        text, provider_used = await gw.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            provider="anthropic",
            api_key=decrypted_key,
        )

    The method tries the requested provider first, then falls back to Ollama
    (local, no API cost), then returns ("", "fallback") if everything fails.

    Returns
    -------
    tuple[str, str]
        (content, provider_name_used)
        provider_name_used is one of the provider keys or "fallback".
    """

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        provider: str,
        api_key: str = "",
        ollama_model: str = "llama3.1:8b",
    ) -> tuple[str, str]:
        """
        Dispatch a completion request through the provider cascade.

        Parameters
        ----------
        system_prompt:
            The system/instruction prompt sent to the LLM.
        user_prompt:
            The user-facing prompt (question or task).
        provider:
            Requested provider name: "anthropic" | "openai" | "groq" |
            "kimi" | "gemini" | "perplexity" | "ollama".
        api_key:
            Decrypted API key for the provider.  Empty string means the
            provider will be skipped and the cascade starts at Ollama.
        ollama_model:
            Ollama model tag (default "llama3.1:8b").

        Returns
        -------
        tuple[str, str]
            ``(content, provider_name_used)``
        """
        cascade: list[tuple[str, object]] = []

        # Build ordered cascade — primary provider first (only if key is present)
        if provider == "anthropic" and api_key:
            cascade.append(
                ("anthropic", lambda: _call_anthropic(system_prompt, user_prompt, api_key))
            )
        elif provider == "openai" and api_key:
            cascade.append(("openai", lambda: _call_openai(system_prompt, user_prompt, api_key)))
        elif provider == "groq" and api_key:
            cascade.append(("groq", lambda: _call_groq(system_prompt, user_prompt, api_key)))
        elif provider == "kimi" and api_key:
            cascade.append(("kimi", lambda: _call_kimi(system_prompt, user_prompt, api_key)))
        elif provider == "gemini" and api_key:
            cascade.append(("gemini", lambda: _call_gemini(system_prompt, user_prompt, api_key)))
        elif provider == "perplexity" and api_key:
            cascade.append(
                ("perplexity", lambda: _call_perplexity(system_prompt, user_prompt, api_key))
            )
        elif provider == "ollama":
            # Ollama needs no key; add it as primary and skip the second append below
            cascade.append(
                ("ollama", lambda: _call_ollama(system_prompt, user_prompt, ollama_model))
            )

        # Always append Ollama as local fallback unless it is already primary
        if provider != "ollama":
            cascade.append(
                ("ollama", lambda: _call_ollama(system_prompt, user_prompt, ollama_model))
            )

        # Try each provider in order
        for name, call in cascade:
            try:
                result = await call()  # type: ignore[operator]
                if result and len(result) > _MIN_RESPONSE_LEN:
                    return result, name
                logger.warning(
                    f"LLMGateway: provider '{name}' returned a short response "
                    f"({len(result)} chars) — skipping"
                )
            except Exception as exc:
                logger.warning(f"LLMGateway: provider '{name}' failed: {exc}")

        return "", "fallback"


# ── LLMProvider Protocol ──────────────────────────────────────────────────────


class LLMProvider(ABC):
    """Abstract base class for all BYOK LLM providers."""

    @abstractmethod
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str) -> str:
        """Send a completion request and return the text response."""
        pass

    @abstractmethod
    def validate_key_format(self, api_key: str) -> bool:
        """Check if the API key has the right format (not if it's valid)."""
        pass


# ── Provider Classes ──────────────────────────────────────────────────────────


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
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                    "temperature": 0.3,
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
    Default model: llama-3.3-70b-versatile (free tier).
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
    Google Gemini — free tier via AI Studio.
    Default model: gemini-1.5-flash (1500 req/day free).
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
    Recommended model: llama3.1:8b.
    """

    def __init__(self, model: str = "llama3.1:8b"):
        self.model = model

    @llm_circuit
    async def complete(self, system_prompt: str, user_prompt: str, api_key: str = "") -> str:
        async with httpx.AsyncClient(timeout=180.0) as client:
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
                    f"Ollama model '{self.model}' not found. Run: ollama pull {self.model}"
                )

            response.raise_for_status()
            return response.json()["response"]

    def validate_key_format(self, api_key: str) -> bool:
        return True  # Ollama doesn't need a key


class KeywordFallback(LLMProvider):
    """
    Free, offline fallback when LLM is unavailable.
    Returns a marker string that tells tailor_resume() to use original bullets.
    """

    async def complete(self, system_prompt: str, user_prompt: str, api_key: str = "") -> str:
        logger.info("Using keyword fallback — LLM unavailable")
        return "__FALLBACK_MODE__"

    def validate_key_format(self, api_key: str) -> bool:
        return True

    def score_bullets_by_relevance(
        self, bullets: list[str], job_description: str
    ) -> list[tuple[str, float]]:
        """Score each bullet by keyword overlap with JD."""
        jd_words = set(job_description.lower().split())
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


# ── Exceptions ────────────────────────────────────────────────────────────────


class InvalidAPIKeyError(Exception):
    """Raised when user's API key is invalid."""

    pass


class RateLimitError(Exception):
    """Raised when LLM provider rate limits us."""

    pass


class LLMUnavailableError(Exception):
    """Raised when LLM is down and we're using fallback."""

    pass


# ── Constants & Provider Registry ────────────────────────────────────────────

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


# ── Resume Tailoring Entry Point ──────────────────────────────────────────────


async def tailor_resume(
    resume_ast: ResumeAST,
    job_description: str,
    strategy: RewriteStrategy,
    provider_name: str,
    encrypted_api_key: str,
) -> tuple[list[str], bool, str]:
    """
    Main entry point for BYOK resume tailoring.

    Args:
        resume_ast: Parsed original resume
        job_description: The job description to tailor for
        strategy: How aggressively to rewrite
        provider_name: "anthropic" | "openai" | "fallback" | etc.
        encrypted_api_key: Fernet-encrypted API key from database

    Returns:
        tuple of:
        - list[str]: Rewritten bullet texts (same count as original)
        - bool: True if fallback was used (LLM unavailable)
        - str: Summary of changes made
    """
    provider = get_provider(provider_name)

    # Decrypt API key
    api_key = ""
    if encrypted_api_key and provider_name != "fallback":
        try:
            api_key = decrypt_value(encrypted_api_key)
        except Exception as e:
            logger.error(f"Failed to decrypt API key: {e}")
            provider = PROVIDERS["fallback"]

    # Validate key format
    if api_key and not provider.validate_key_format(api_key):
        logger.warning(f"Invalid API key format for {provider_name}")
        provider = PROVIDERS["fallback"]

    # Build the prompt
    user_prompt = REWRITE_PROMPT_TEMPLATE.format(
        strategy_description=STRATEGY_DESCRIPTIONS[strategy],
        job_description=job_description[:4000],
        resume_context=resume_ast.to_prompt_context(),
        bullet_count=resume_ast.bullet_count,
    )

    # Call the LLM
    try:
        raw_response = await provider.complete(SYSTEM_PROMPT, user_prompt, api_key)

        if raw_response == "__FALLBACK_MODE__":
            return (
                [b.text for b in resume_ast.bullets],
                True,
                "LLM unavailable. Showing original bullets with keyword relevance scores.",
            )

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

    Cleans up formatting artifacts (numbers, dashes, BULLET_N labels).
    Trims to expected_count if too many; warns if too few.
    """
    lines = raw_response.strip().split("\n")

    bullets: list[str] = []
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue

        cleaned = re.sub(r"^(\d+[.)]\s*|[-•●]\s*|BULLET_\d+:\s*)", "", cleaned)
        cleaned = cleaned.strip()

        if cleaned and len(cleaned) > 5:
            bullets.append(cleaned)

    if len(bullets) > expected_count:
        logger.warning(f"LLM returned {len(bullets)} bullets, expected {expected_count}. Trimming.")
        bullets = bullets[:expected_count]

    if len(bullets) < expected_count:
        logger.warning(f"LLM returned {len(bullets)} bullets, expected {expected_count}.")

    return bullets
