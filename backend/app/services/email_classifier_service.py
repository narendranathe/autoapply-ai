"""
Email Classifier Service — T2 Issue #2.

Classifies an email body into one of the 8 application statuses:
  discovered | draft | tailored | applied | rejected | phone_screen | interview | offer

Strategy:
  1. Strip HTML from email body
  2. Try LLM (provider from llm_service.PROVIDERS) — expects JSON response
  3. Fall back to keyword matching if LLM fails or returns invalid JSON

LLM prompt returns JSON: {"status": "...", "confidence": 0.0-1.0, "reasoning": "..."}
"""

from __future__ import annotations

import json
import re

from loguru import logger

from app.schemas.application import ParseEmailResponse
from app.services.llm_service import PROVIDERS, InvalidAPIKeyError, RateLimitError

# ── Valid statuses ────────────────────────────────────────────────────────────

_VALID_STATUSES = frozenset(
    {
        "discovered",
        "draft",
        "tailored",
        "applied",
        "rejected",
        "phone_screen",
        "interview",
        "offer",
    }
)

# ── LLM prompt ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert at reading job application emails and determining the current
hiring stage. Classify the email into exactly one of these statuses:
  offer | interview | phone_screen | rejected | applied | discovered

Return ONLY a JSON object with these keys:
  status     — one of the statuses above (string)
  confidence — your confidence level from 0.0 to 1.0 (float)
  reasoning  — one sentence explanation (string)

Example:
{"status": "rejected", "confidence": 0.95, "reasoning": "Email says 'we will not be moving forward'."}
"""

_USER_PROMPT_TEMPLATE = """\
Classify the following email{company_clause}. Return JSON only.

EMAIL:
{email_text}
"""


# ── HTML stripping ────────────────────────────────────────────────────────────


def strip_html_tags(html: str) -> str:
    """
    Remove all HTML tags from a string and collapse whitespace.

    Args:
        html: Raw HTML string (may also be plain text — safe to pass through).

    Returns:
        Plain text with tags removed and whitespace collapsed.
    """
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse multiple whitespace (spaces, tabs, newlines) into a single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ── Keyword fallback ──────────────────────────────────────────────────────────


def _keyword_fallback(text: str) -> tuple[str, float]:
    """
    Classify email status using keyword pattern matching.

    Evaluated in priority order: offer > interview > phone_screen > rejected > applied.

    Args:
        text: Plain-text email body (HTML already stripped).

    Returns:
        (status, confidence) tuple.
    """
    lower = text.lower()

    # Offer — highest priority, most specific signal
    offer_patterns = [
        r"congratulations.*offer",
        r"pleased to offer",
        r"\bjob offer\b",
        r"\boffer letter\b",
        r"\bformal offer\b",
        r"we.{0,20}like to offer you",
    ]
    for pattern in offer_patterns:
        if re.search(pattern, lower):
            return "offer", 0.95

    # Interview invite
    interview_patterns = [
        r"schedule.*interview",
        r"invite you to interview",
        r"\bnext round\b",
        r"\bfinal round\b",
        r"\btechnical interview\b",
        r"\bonsite interview\b",
        r"\bvirtual interview\b",
        r"we.{0,30}like to (schedule|set up|arrange)",
    ]
    for pattern in interview_patterns:
        if re.search(pattern, lower):
            return "interview", 0.90

    # Phone screen / recruiter call
    phone_patterns = [
        r"\bphone screen\b",
        r"\bphone call\b",
        r"\brecruiter call\b",
        r"(15|30).{0,10}minute.{0,10}call",
        r"\bintroductory call\b",
        r"\bscreening call\b",
    ]
    for pattern in phone_patterns:
        if re.search(pattern, lower):
            return "phone_screen", 0.85

    # Rejection
    rejection_patterns = [
        r"not moving forward",
        r"not selected",
        r"\bunfortunately\b",
        r"other candidates",
        r"position has been filled",
        r"decided to (move|proceed) with (other|another)",
        r"will not be (moving|proceeding)",
        r"we regret to inform",
    ]
    for pattern in rejection_patterns:
        if re.search(pattern, lower):
            return "rejected", 0.90

    # Application received
    applied_patterns = [
        r"received your application",
        r"application received",
        r"thank you for applying",
        r"we have received",
        r"successfully submitted",
        r"application has been submitted",
    ]
    for pattern in applied_patterns:
        if re.search(pattern, lower):
            return "applied", 0.70

    # Default — no clear signal
    return "applied", 0.40


# ── Main classifier ───────────────────────────────────────────────────────────


async def classify_email_status(
    email_body: str,
    company_name: str | None,
    provider: str,
    api_key: str,
    model: str | None = None,
) -> ParseEmailResponse:
    """
    Classify an email body into an application status.

    Workflow:
      1. Strip HTML from email_body
      2. Try LLM provider (returns JSON with status/confidence/reasoning)
      3. Parse and validate LLM JSON
      4. Fall back to _keyword_fallback on any error

    Args:
        email_body:   Raw email text (HTML or plain text).
        company_name: Optional company name for context in the prompt.
        provider:     LLM provider name (e.g. "anthropic", "openai", "groq").
        api_key:      Plaintext API key for the provider.
        model:        Optional model override (not used currently, reserved).

    Returns:
        ParseEmailResponse with suggested_status, confidence, and reasoning.
    """
    # Step 1: strip HTML
    clean_text = strip_html_tags(email_body)

    # Truncate to prevent excessive token usage (50K chars → ~12K tokens)
    truncated = clean_text[:8000]

    # Step 2: build LLM prompt
    company_clause = f" from {company_name}" if company_name else ""
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        company_clause=company_clause,
        email_text=truncated,
    )

    # Step 3: try LLM
    llm_provider = PROVIDERS.get(provider, PROVIDERS.get("fallback"))
    if llm_provider is None:
        logger.warning(f"Unknown LLM provider '{provider}' — using keyword fallback")
        status, confidence = _keyword_fallback(clean_text)
        return ParseEmailResponse(
            suggested_status=status,
            confidence=confidence,
            reasoning="LLM provider unavailable; classified by keyword patterns.",
        )

    try:
        raw = await llm_provider.complete(_SYSTEM_PROMPT, user_prompt, api_key)

        # Step 4: parse JSON — LLM might wrap in markdown fences
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON object found in LLM response: {raw[:200]}")

        data = json.loads(json_match.group())

        status = str(data.get("status", "")).lower().strip()
        if status not in _VALID_STATUSES:
            raise ValueError(f"LLM returned unknown status: {status!r}")

        raw_confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, raw_confidence))  # clamp to [0, 1]

        reasoning = str(data.get("reasoning", "")).strip() or "Classified by LLM."

        logger.info(f"Email classified as '{status}' (confidence={confidence:.2f}) via {provider}")

        return ParseEmailResponse(
            suggested_status=status,
            confidence=confidence,
            reasoning=reasoning,
        )

    except (InvalidAPIKeyError, RateLimitError) as e:
        logger.warning(f"LLM provider error ({provider}): {e} — using keyword fallback")
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse LLM response: {e} — using keyword fallback")
    except Exception as e:
        logger.error(f"Unexpected LLM error ({provider}): {e} — using keyword fallback")

    # Step 5: keyword fallback
    status, confidence = _keyword_fallback(clean_text)
    return ParseEmailResponse(
        suggested_status=status,
        confidence=confidence,
        reasoning="LLM unavailable or returned invalid response; classified by keyword patterns.",
    )
