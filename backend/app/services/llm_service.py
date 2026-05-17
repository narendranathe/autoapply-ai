"""
Legacy import surface for LLM provider symbols.

This module exists for backward compatibility with code that imports from
``app.services.llm_service``. The authoritative implementations live in
``app.services.llm_gateway`` after the #146 consolidation.

When all import sites have migrated (issues #147, #148), this module will be
deleted by #149.
"""

from app.services.llm_gateway import (
    PROVIDERS,
    REWRITE_PROMPT_TEMPLATE,
    STRATEGY_DESCRIPTIONS,
    SYSTEM_PROMPT,
    AnthropicProvider,
    GeminiProvider,
    GroqProvider,
    InvalidAPIKeyError,
    KeywordFallback,
    KimiProvider,
    LLMProvider,
    LLMUnavailableError,
    OllamaProvider,
    OpenAIProvider,
    PerplexityProvider,
    RateLimitError,
    RewriteStrategy,
    _parse_llm_response,
    get_provider,
    tailor_resume,
)

__all__ = [
    "LLMProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "KimiProvider",
    "PerplexityProvider",
    "GroqProvider",
    "GeminiProvider",
    "OllamaProvider",
    "KeywordFallback",
    "InvalidAPIKeyError",
    "RateLimitError",
    "LLMUnavailableError",
    "RewriteStrategy",
    "SYSTEM_PROMPT",
    "REWRITE_PROMPT_TEMPLATE",
    "STRATEGY_DESCRIPTIONS",
    "PROVIDERS",
    "get_provider",
    "tailor_resume",
    "_parse_llm_response",
]
