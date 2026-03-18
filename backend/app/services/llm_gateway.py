"""
LLMGateway — single source of truth for LLM provider dispatch.

Extracted from resume_generator._llm_generate so every code path
(resume, Q&A, cover letter, summary, bullets) shares one dispatch table.

Phase 1: create the class with full test coverage.
Phase 2 (next): migrate resume_generator / llm_service to call LLMGateway.

Supported providers
-------------------
anthropic  | Anthropic claude-sonnet-4-6
openai     | OpenAI gpt-4o
groq       | Groq llama-3.3-70b-versatile (free tier)
kimi       | Moonshot moonshot-v1-32k   (long-context)
gemini     | Google Gemini 1.5 Flash    (free tier)
perplexity | Perplexity sonar           (web-grounded)
ollama     | Local Ollama               (no key needed)
fallback   | Always-available empty string return
"""

from __future__ import annotations

import httpx
from loguru import logger

from app.config import settings

# ── Low-level HTTP callers (mirrors resume_generator private functions) ──────


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
