"""
TDD tests for T2: Email Status Parsing — Issue #1
Covers schema fixes (phone_screen validator) + new ParseEmail schemas.
"""

import pytest
from pydantic import ValidationError

from app.schemas.application import (
    ApplicationStatusUpdate,
    ParseEmailRequest,
    ParseEmailResponse,
)

# ── Validator fix: phone_screen ──────────────────────────────────────────────


def test_status_update_accepts_phone_screen():
    """AC: phone_screen is now a valid status (was previously blocked by regex)."""
    update = ApplicationStatusUpdate(status="phone_screen")
    assert update.status == "phone_screen"


def test_status_update_accepts_discovered():
    """AC: discovered is valid in schema (already was, just confirming)."""
    update = ApplicationStatusUpdate(status="discovered")
    assert update.status == "discovered"


def test_status_update_rejects_unknown():
    """AC: unknown status still rejected."""
    with pytest.raises(ValidationError):
        ApplicationStatusUpdate(status="ghosted")


def test_status_update_accepts_all_valid():
    """AC: all 8 valid statuses pass."""
    for status in (
        "discovered",
        "draft",
        "tailored",
        "applied",
        "rejected",
        "phone_screen",
        "interview",
        "offer",
    ):
        obj = ApplicationStatusUpdate(status=status)
        assert obj.status == status


# ── New schema: ParseEmailRequest ────────────────────────────────────────────


def test_parse_email_request_valid():
    """AC: ParseEmailRequest accepts email_body."""
    req = ParseEmailRequest(email_body="Thanks for applying. Unfortunately...")
    assert len(req.email_body) > 0


def test_parse_email_request_optional_company_name():
    """AC: company_name is optional."""
    req = ParseEmailRequest(email_body="We'd like to schedule an interview.")
    assert req.company_name is None


def test_parse_email_request_with_company_name():
    """AC: company_name can be provided."""
    req = ParseEmailRequest(
        email_body="We'd like to schedule an interview.",
        company_name="Acme Corp",
    )
    assert req.company_name == "Acme Corp"


def test_parse_email_request_rejects_empty_body():
    """AC: empty email_body raises ValidationError (min_length=1)."""
    with pytest.raises(ValidationError):
        ParseEmailRequest(email_body="")


# ── New schema: ParseEmailResponse ───────────────────────────────────────────


def test_parse_email_response_valid():
    """AC: ParseEmailResponse accepts all required fields."""
    resp = ParseEmailResponse(
        suggested_status="rejected",
        confidence=0.95,
        reasoning="Email contains 'unfortunately' and 'not moving forward'.",
    )
    assert resp.suggested_status == "rejected"
    assert resp.confidence == 0.95
    assert resp.company_match is None


def test_parse_email_response_company_match_optional():
    """AC: company_match defaults to None."""
    resp = ParseEmailResponse(
        suggested_status="interview",
        confidence=0.88,
        reasoning="Interview invite detected.",
    )
    assert resp.company_match is None
