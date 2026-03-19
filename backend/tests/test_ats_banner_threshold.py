"""
Tests for ATS score retrieval — ensures ats_result is returned correctly from
POST /vault/retrieve for the ATS banner threshold feature (#59).

The banner in the extension shows/hides based on ats_result.overall_score; these
tests verify the backend correctly surfaces (or omits) ats_result.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ats_result(overall_score: float = 82.0) -> MagicMock:
    """Return a minimal ATSResult-like mock."""
    ats = MagicMock()
    ats.overall_score = overall_score
    ats.keyword_coverage = 0.8
    ats.skills_present = ["Python", "FastAPI"]
    ats.skills_gap = ["Kubernetes"]
    ats.quantification_score = 0.7
    ats.experience_alignment = 0.85
    ats.mq_coverage = 0.9
    ats.suggestions = ["Add metrics to bullet points"]
    ats.total_jd_keywords = 20
    ats.matched_keywords = 16
    return ats


def _make_advice(company: str, with_ats: bool = True) -> MagicMock:
    """Return a minimal PositioningAdvice-like mock."""
    best = MagicMock()
    best.resume_id = "00000000-0000-0000-0000-000000000001"
    best.version_tag = "v1"
    best.filename = "resume.pdf"
    best.file_type = "pdf"
    best.target_company = company
    best.target_role = "SWE"
    best.ats_score = 82.0 if with_ats else None
    best.similarity_score = 0.9
    best.last_used = "2025-01-01"
    best.usage_outcomes = []
    best.github_path = None
    best.latex_content = None

    advice = MagicMock()
    advice.best_resume = best
    advice.company_history = [best]
    advice.ats_result = _make_ats_result() if with_ats else None
    advice.positioning_summary = f"Good fit for {company}"
    advice.reuse_recommendation = "tweak"
    return advice


# ---------------------------------------------------------------------------
# Test 1: retrieve with jd_text returns ats_result dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_with_jd_returns_ats_result():
    """
    POST /vault/retrieve with jd_text must return ats_result as a dict
    containing overall_score — used by the ATS banner threshold check.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-001"

    advice = _make_advice("TestCorp", with_ats=True)

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_positioning_advice = AsyncMock(return_value=advice)

        from app.routers.vault.retrieve import retrieve_resumes

        result = await retrieve_resumes(
            company_name="TestCorp",
            jd_text="Looking for a Python engineer with FastAPI experience",
            top_k=5,
            db=mock_db,
            user=mock_user,
        )

    assert "ats_result" in result
    assert result["ats_result"] is not None
    assert "overall_score" in result["ats_result"]
    assert isinstance(result["ats_result"]["overall_score"], float)


# ---------------------------------------------------------------------------
# Test 2: retrieve without jd_text returns ats_result=None (company-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_without_jd_returns_null_ats_result():
    """
    POST /vault/retrieve without jd_text (company-only lookup) must return
    ats_result=None — banner should not show when no JD is provided.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-002"

    history_entry = MagicMock()
    history_entry.resume_id = "00000000-0000-0000-0000-000000000002"
    history_entry.version_tag = "v1"
    history_entry.filename = "resume.pdf"
    history_entry.file_type = "pdf"
    history_entry.target_company = "TestCorp"
    history_entry.target_role = "SWE"
    history_entry.ats_score = None
    history_entry.similarity_score = 0.7
    history_entry.last_used = "2025-02-01"
    history_entry.usage_outcomes = []
    history_entry.github_path = None
    history_entry.latex_content = None

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.retrieve_by_company = AsyncMock(return_value=[history_entry])

        from app.routers.vault.retrieve import retrieve_resumes

        result = await retrieve_resumes(
            company_name="TestCorp",
            jd_text=None,
            top_k=5,
            db=mock_db,
            user=mock_user,
        )

    assert "ats_result" in result
    assert result["ats_result"] is None


# ---------------------------------------------------------------------------
# Test 3: ats_result dict contains all fields needed by the extension banner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ats_result_contains_required_fields():
    """
    ats_result must include overall_score, keyword_coverage, skills_present,
    skills_gap, and suggestions — all consumed by the ATS banner UI.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-003"

    advice = _make_advice("BannerCorp", with_ats=True)

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_positioning_advice = AsyncMock(return_value=advice)

        from app.routers.vault.retrieve import retrieve_resumes

        result = await retrieve_resumes(
            company_name="BannerCorp",
            jd_text="Senior Python backend role",
            top_k=5,
            db=mock_db,
            user=mock_user,
        )

    ats = result["ats_result"]
    required = {
        "overall_score",
        "keyword_coverage",
        "skills_present",
        "skills_gap",
        "suggestions",
    }
    missing = required - set(ats.keys())
    assert not missing, f"ats_result is missing fields needed by banner: {missing}"


# ---------------------------------------------------------------------------
# Test 4: empty history (no resumes) → ats_result is None, no error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_empty_history_no_error():
    """
    When user has no uploaded resumes, retrieve_resumes must return gracefully
    with best_match=None and ats_result=None (no exception raised).
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-004"

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.retrieve_by_company = AsyncMock(return_value=[])

        from app.routers.vault.retrieve import retrieve_resumes

        result = await retrieve_resumes(
            company_name="EmptyCorp",
            jd_text=None,
            top_k=5,
            db=mock_db,
            user=mock_user,
        )

    assert result["best_match"] is None
    assert result["ats_result"] is None
    assert result["company_history"] == []


# ---------------------------------------------------------------------------
# Test 5: ats_result.overall_score reflects the ATSResult value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ats_overall_score_value_is_preserved():
    """
    The overall_score in the response must match the value from the ATSResult object.
    This ensures the banner threshold check (e.g. score < 70 → show warning) is reliable.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-005"

    expected_score = 64.5
    advice = _make_advice("ThresholdCorp", with_ats=True)
    advice.ats_result.overall_score = expected_score

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_positioning_advice = AsyncMock(return_value=advice)

        from app.routers.vault.retrieve import retrieve_resumes

        result = await retrieve_resumes(
            company_name="ThresholdCorp",
            jd_text="Python backend engineering",
            top_k=5,
            db=mock_db,
            user=mock_user,
        )

    assert result["ats_result"]["overall_score"] == expected_score
