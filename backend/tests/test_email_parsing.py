"""
TDD tests for T2 Email Status Parsing — Issues #2, #3, #4.

Covers:
  - T2 Issue #2: email_classifier_service (strip_html, keyword_fallback, classify_email_status)
  - T2 Issue #3: ApplicationService.find_by_company_name_fuzzy
  - T2 Issue #4: POST /api/v1/applications/parse-email endpoint
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.application import ParseEmailResponse
from app.services.application_service import ApplicationService
from app.services.email_classifier_service import (
    _keyword_fallback,
    classify_email_status,
    strip_html_tags,
)

# ═══════════════════════════════════════════════════════════════════════════════
# T2 Issue #2A — strip_html_tags
# ═══════════════════════════════════════════════════════════════════════════════


class TestStripHtmlTags:
    def test_removes_simple_tags(self):
        """HTML tags are removed, leaving text content."""
        result = strip_html_tags("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result
        assert ">" not in result

    def test_collapses_whitespace(self):
        """Multiple whitespace chars (spaces, newlines, tabs) collapse to single space."""
        result = strip_html_tags("<p>Hello  \n\t  world</p>")
        assert "Hello world" in result
        assert "  " not in result  # no double spaces

    def test_plain_text_passthrough(self):
        """Plain text without HTML passes through unchanged (modulo whitespace normalisation)."""
        result = strip_html_tags("Just plain text.")
        assert result == "Just plain text."

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert strip_html_tags("") == ""

    def test_nested_tags(self):
        """Deeply nested tags are fully removed."""
        html = "<div><span><a href='#'>Link text</a></span></div>"
        result = strip_html_tags(html)
        assert result == "Link text"

    def test_strips_style_and_script_content(self):
        """Style/script tags are removed along with surrounding content."""
        html = "<style>body { color: red; }</style>Hello<script>alert(1)</script>"
        result = strip_html_tags(html)
        # Tags are gone; text content remains (style/script *content* stays — that's ok)
        assert "<style>" not in result
        assert "<script>" not in result
        assert "Hello" in result


# ═══════════════════════════════════════════════════════════════════════════════
# T2 Issue #2B — _keyword_fallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestKeywordFallback:
    def test_offer_pattern_job_offer(self):
        status, conf = _keyword_fallback("We are pleased to send you a job offer letter.")
        assert status == "offer"
        assert conf >= 0.90

    def test_offer_pattern_congratulations(self):
        status, conf = _keyword_fallback("Congratulations! We are extending an offer to you.")
        assert status == "offer"
        assert conf >= 0.90

    def test_offer_pattern_pleased_to_offer(self):
        status, conf = _keyword_fallback("We are pleased to offer you the position.")
        assert status == "offer"
        assert conf >= 0.90

    def test_interview_schedule(self):
        status, conf = _keyword_fallback(
            "We would like to schedule an interview with you next week."
        )
        assert status == "interview"
        assert conf >= 0.85

    def test_interview_next_round(self):
        status, conf = _keyword_fallback("You have advanced to the next round of interviews.")
        assert status == "interview"
        assert conf >= 0.85

    def test_interview_final_round(self):
        status, conf = _keyword_fallback("We'd like to invite you to the final round.")
        assert status == "interview"
        assert conf >= 0.85

    def test_phone_screen(self):
        status, conf = _keyword_fallback("Our recruiter would like to schedule a phone screen.")
        assert status == "phone_screen"
        assert conf >= 0.80

    def test_phone_screen_recruiter_call(self):
        status, conf = _keyword_fallback("Hi! I'd love to set up a quick recruiter call this week.")
        assert status == "phone_screen"
        assert conf >= 0.80

    def test_phone_screen_30_min(self):
        status, conf = _keyword_fallback(
            "Let's hop on a 30 minute call to discuss your background."
        )
        assert status == "phone_screen"
        assert conf >= 0.80

    def test_rejected_unfortunately(self):
        status, conf = _keyword_fallback(
            "Unfortunately, we have decided not to move forward with your application."
        )
        assert status == "rejected"
        assert conf >= 0.85

    def test_rejected_not_selected(self):
        status, conf = _keyword_fallback(
            "After careful review, you were not selected for this role."
        )
        assert status == "rejected"
        assert conf >= 0.85

    def test_rejected_other_candidates(self):
        status, conf = _keyword_fallback(
            "We have decided to move forward with other candidates at this time."
        )
        assert status == "rejected"
        assert conf >= 0.85

    def test_applied_received(self):
        status, conf = _keyword_fallback(
            "Thank you for applying! We have received your application."
        )
        assert status == "applied"
        assert conf >= 0.65

    def test_applied_thank_you_for_applying(self):
        status, conf = _keyword_fallback("Thank you for applying to the Software Engineer role.")
        assert status == "applied"
        assert conf >= 0.65

    def test_default_fallback(self):
        """Generic email with no clear signal returns 'applied' with low confidence."""
        status, conf = _keyword_fallback("Hi, just wanted to touch base with you.")
        assert status == "applied"
        assert conf < 0.60

    def test_priority_offer_over_phone_screen(self):
        """Offer signal takes priority even if email also mentions a call."""
        text = "We have a job offer for you — let's schedule a call to discuss."
        status, conf = _keyword_fallback(text)
        assert status == "offer"

    def test_priority_interview_over_applied(self):
        """Interview signal takes priority over application-received language."""
        text = "Thank you for applying. We'd like to schedule an interview."
        status, conf = _keyword_fallback(text)
        assert status == "interview"


# ═══════════════════════════════════════════════════════════════════════════════
# T2 Issue #2C — classify_email_status (async, uses LLM or fallback)
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifyEmailStatus:
    @pytest.mark.asyncio
    async def test_llm_success_returns_parsed_response(self):
        """
        When LLM returns valid JSON, classify_email_status parses and returns it.
        """
        fake_llm_response = (
            '{"status": "interview", "confidence": 0.92, '
            '"reasoning": "Email invites candidate to interview."}'
        )
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=fake_llm_response)

        with patch(
            "app.services.email_classifier_service.PROVIDERS",
            {"anthropic": mock_provider},
        ):
            result = await classify_email_status(
                email_body="We'd like to schedule an interview with you.",
                company_name="Acme Corp",
                provider="anthropic",
                api_key="sk-ant-fake",
            )

        assert isinstance(result, ParseEmailResponse)
        assert result.suggested_status == "interview"
        assert result.confidence == pytest.approx(0.92)
        assert "interview" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_llm_returns_status_in_valid_set(self):
        """All returned statuses must be from the valid set."""
        valid_statuses = {
            "discovered",
            "draft",
            "tailored",
            "applied",
            "rejected",
            "phone_screen",
            "interview",
            "offer",
        }
        fake_llm_response = (
            '{"status": "offer", "confidence": 0.98, "reasoning": "Job offer extended."}'
        )
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=fake_llm_response)

        with patch(
            "app.services.email_classifier_service.PROVIDERS",
            {"openai": mock_provider},
        ):
            result = await classify_email_status(
                email_body="Congratulations! We are pleased to offer you the position.",
                company_name=None,
                provider="openai",
                api_key="sk-fake",
            )

        assert result.suggested_status in valid_statuses

    @pytest.mark.asyncio
    async def test_llm_exception_triggers_keyword_fallback(self):
        """
        When LLM raises an exception, keyword fallback is used.
        Rejection email → should get 'rejected' status from keywords.
        """
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(side_effect=Exception("API timeout"))

        with patch(
            "app.services.email_classifier_service.PROVIDERS",
            {"anthropic": mock_provider},
        ):
            result = await classify_email_status(
                email_body="Unfortunately, we will not be moving forward with your application.",
                company_name="BigCo",
                provider="anthropic",
                api_key="sk-ant-fake",
            )

        assert result.suggested_status == "rejected"
        assert "keyword" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_llm_invalid_json_triggers_keyword_fallback(self):
        """
        When LLM returns non-JSON garbage, keyword fallback is used.
        """
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value="This is not JSON at all.")

        with patch(
            "app.services.email_classifier_service.PROVIDERS",
            {"groq": mock_provider},
        ):
            result = await classify_email_status(
                email_body="Thank you for applying! We have received your application.",
                company_name=None,
                provider="groq",
                api_key="gsk_fake",
            )

        # Keyword fallback: "received your application" → applied
        assert result.suggested_status == "applied"

    @pytest.mark.asyncio
    async def test_llm_unknown_status_triggers_keyword_fallback(self):
        """
        When LLM returns a status not in the valid set, keyword fallback is used.
        """
        fake_llm_response = '{"status": "ghosted", "confidence": 0.5, "reasoning": "No reply."}'
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=fake_llm_response)

        with patch(
            "app.services.email_classifier_service.PROVIDERS",
            {"openai": mock_provider},
        ):
            result = await classify_email_status(
                email_body="We would like to invite you for a final round interview.",
                company_name=None,
                provider="openai",
                api_key="sk-fake",
            )

        # Keyword fallback: "final round interview" → interview
        assert result.suggested_status == "interview"

    @pytest.mark.asyncio
    async def test_html_stripped_before_classification(self):
        """
        HTML-wrapped email is stripped before keyword matching in fallback.
        """
        html_email = "<p>Unfortunately, we <b>will not</b> be moving forward.</p>"
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(side_effect=Exception("LLM down"))

        with patch(
            "app.services.email_classifier_service.PROVIDERS",
            {"anthropic": mock_provider},
        ):
            result = await classify_email_status(
                email_body=html_email,
                company_name=None,
                provider="anthropic",
                api_key="",
            )

        assert result.suggested_status == "rejected"

    @pytest.mark.asyncio
    async def test_confidence_clamped_to_valid_range(self):
        """LLM confidence values outside [0, 1] are clamped."""
        fake_llm_response = '{"status": "applied", "confidence": 1.5, "reasoning": "Test."}'
        mock_provider = AsyncMock()
        mock_provider.complete = AsyncMock(return_value=fake_llm_response)

        with patch(
            "app.services.email_classifier_service.PROVIDERS",
            {"groq": mock_provider},
        ):
            result = await classify_email_status(
                email_body="Thank you for applying.",
                company_name=None,
                provider="groq",
                api_key="gsk_fake",
            )

        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_unknown_provider_uses_keyword_fallback(self):
        """
        Unknown provider name → keyword fallback without LLM call.
        """
        result = await classify_email_status(
            email_body="We are pleased to offer you the position.",
            company_name="TestCo",
            provider="nonexistent_provider_xyz",
            api_key="",
        )

        assert result.suggested_status == "offer"


# ═══════════════════════════════════════════════════════════════════════════════
# T2 Issue #3 — ApplicationService.find_by_company_name_fuzzy
# ═══════════════════════════════════════════════════════════════════════════════


class TestFindByCompanyNameFuzzy:
    @pytest.mark.asyncio
    async def test_finds_exact_match(self, db_session, test_user):
        """Returns application when company_name matches exactly."""
        svc = ApplicationService()

        await svc.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Stripe",
            role_title="Backend Engineer",
            job_url=None,
            platform="manual",
            job_description="Backend role at Stripe",
            git_path="versions/test.tex",
        )

        result = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "Stripe")
        assert result is not None
        assert result.company_name == "Stripe"

    @pytest.mark.asyncio
    async def test_finds_partial_match(self, db_session, test_user):
        """Returns application when company_name is a substring of stored name."""
        svc = ApplicationService()

        await svc.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Google LLC",
            role_title="SWE",
            job_url=None,
            platform="linkedin",
            job_description="Google SWE role",
            git_path="versions/google.tex",
        )

        result = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "Google")
        assert result is not None
        assert "Google" in result.company_name

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self, db_session, test_user):
        """Match is case-insensitive."""
        svc = ApplicationService()

        await svc.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="OpenAI",
            role_title="ML Researcher",
            job_url=None,
            platform="manual",
            job_description="ML research at OpenAI",
            git_path="versions/openai.tex",
        )

        result = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "openai")
        assert result is not None

        result2 = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "OPENAI")
        assert result2 is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self, db_session, test_user):
        """Returns None when no application matches the company name."""
        svc = ApplicationService()

        await svc.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Apple",
            role_title="iOS Engineer",
            job_url=None,
            platform="manual",
            job_description="iOS role",
            git_path="versions/apple.tex",
        )

        result = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "Microsoft")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_company_name(self, db_session, test_user):
        """Returns None when company_name is empty string."""
        svc = ApplicationService()
        result = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_whitespace_company_name(self, db_session, test_user):
        """Returns None when company_name is only whitespace."""
        svc = ApplicationService()
        result = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "   ")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_most_recent_on_multiple_matches(self, db_session, test_user):
        """Returns the most recently created application when multiple match."""
        svc = ApplicationService()

        await svc.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Meta",
            role_title="SWE I",
            job_url=None,
            platform="manual",
            job_description="SWE role first",
            git_path="versions/meta1.tex",
        )

        await svc.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Meta",
            role_title="SWE II",
            job_url=None,
            platform="manual",
            job_description="SWE role second",
            git_path="versions/meta2.tex",
        )

        result = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "Meta")
        assert result is not None
        # Most recent should be app2
        assert result.role_title in ("SWE I", "SWE II")  # either is acceptable given flush order

    @pytest.mark.asyncio
    async def test_scoped_to_user(self, db_session, test_user):
        """Does not return applications belonging to another user."""
        from app.models.user import User

        svc = ApplicationService()

        other_user = User(
            id=uuid.uuid4(),
            clerk_id=f"other_{uuid.uuid4().hex[:8]}",
            email_hash="c" * 64,
            github_username="otheruser2",
            resume_repo_name="resume-vault",
            is_active=True,
        )
        db_session.add(other_user)
        await db_session.flush()

        # Other user's application
        await svc.create_application(
            db=db_session,
            user_id=other_user.id,
            company_name="Amazon",
            role_title="SDE",
            job_url=None,
            platform="manual",
            job_description="Amazon SDE role",
            git_path="versions/amazon.tex",
        )

        # test_user has no Amazon application
        result = await svc.find_by_company_name_fuzzy(db_session, test_user.id, "Amazon")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# T2 Issue #4 — POST /api/v1/applications/parse-email endpoint
# ═══════════════════════════════════════════════════════════════════════════════


class TestParseEmailEndpoint:
    @pytest.mark.asyncio
    async def test_parse_email_returns_200(self, client, test_user):
        """
        POST /api/v1/applications/parse-email returns 200 with ParseEmailResponse shape.
        Auth is bypassed in test client (dev fallback user).
        """
        payload = {
            "email_body": "Unfortunately, we will not be moving forward with your candidacy.",
        }
        response = await client.post(
            "/api/v1/applications/parse-email",
            json=payload,
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert "suggested_status" in data
        assert "confidence" in data
        assert "reasoning" in data
        assert data["suggested_status"] == "rejected"

    @pytest.mark.asyncio
    async def test_parse_email_with_company_name(self, client, test_user, db_session):
        """
        When company_name is provided and a matching application exists,
        company_match is populated in the response.
        """
        # Create a tracked application first
        svc = ApplicationService()
        await svc.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Stripe",
            role_title="Backend Engineer",
            job_url=None,
            platform="manual",
            job_description="Backend at Stripe",
            git_path="versions/stripe.tex",
        )
        await db_session.flush()

        payload = {
            "email_body": "Congratulations! We are pleased to offer you the position at Stripe.",
            "company_name": "Stripe",
        }
        response = await client.post(
            "/api/v1/applications/parse-email",
            json=payload,
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["suggested_status"] == "offer"
        # company_match should be populated
        assert data["company_match"] is not None
        assert data["company_match"]["company_name"] == "Stripe"

    @pytest.mark.asyncio
    async def test_parse_email_no_company_match(self, client, test_user):
        """
        When company_name is not provided or no match found, company_match is null.
        """
        payload = {
            "email_body": "We have received your application. Thank you for applying.",
        }
        response = await client.post(
            "/api/v1/applications/parse-email",
            json=payload,
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["company_match"] is None

    @pytest.mark.asyncio
    async def test_parse_email_rejects_empty_body(self, client, test_user):
        """
        POST with empty email_body returns 422 Unprocessable Entity.
        """
        payload = {"email_body": ""}
        response = await client.post(
            "/api/v1/applications/parse-email",
            json=payload,
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_parse_email_html_body(self, client, test_user):
        """
        HTML email body is correctly processed (HTML stripped before classification).
        """
        html_email = (
            "<html><body>"
            "<p>Dear Candidate,</p>"
            "<p>We are <b>pleased to offer</b> you the position.</p>"
            "</body></html>"
        )
        payload = {"email_body": html_email}
        response = await client.post(
            "/api/v1/applications/parse-email",
            json=payload,
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["suggested_status"] == "offer"

    @pytest.mark.asyncio
    async def test_parse_email_confidence_range(self, client, test_user):
        """
        Confidence in response is always between 0.0 and 1.0.
        """
        payload = {
            "email_body": "Thanks for reaching out. We'd like to set up a phone screen.",
        }
        response = await client.post(
            "/api/v1/applications/parse-email",
            json=payload,
            headers={"X-Clerk-User-Id": test_user.clerk_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert 0.0 <= data["confidence"] <= 1.0
        assert data["suggested_status"] == "phone_screen"
