"""
TDD tests for POST /vault/retrieve/batch — Issue #16.

Batch endpoint allows Job Scout to retrieve ATS scoring data for N job cards
in a single network round-trip instead of N serial requests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import at module level so the real function reference is captured before
# tests/unit/test_work_history.py poisons app.dependencies.get_current_user = None
# during pytest collection.
from app.dependencies import get_current_user, get_db  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_advice(company: str, ats_score: float | None = 82.0):
    """Return a minimal PositioningAdvice-like mock."""
    best = MagicMock()
    best.resume_id = "00000000-0000-0000-0000-000000000001"
    best.version_tag = "v1"
    best.filename = "resume.pdf"
    best.file_type = "pdf"
    best.target_company = company
    best.target_role = "SWE"
    best.ats_score = ats_score
    best.similarity_score = 0.9
    best.last_used = "2025-01-01"
    best.usage_outcomes = []
    best.github_path = None
    best.latex_content = None

    advice = MagicMock()
    advice.best_resume = best
    advice.company_history = [best]
    advice.ats_result = MagicMock()
    advice.ats_result.overall_score = ats_score or 0.0
    advice.ats_result.keyword_coverage = 0.8
    advice.ats_result.skills_present = ["Python"]
    advice.ats_result.skills_gap = []
    advice.ats_result.quantification_score = 0.7
    advice.ats_result.experience_alignment = 0.8
    advice.ats_result.mq_coverage = 0.9
    advice.ats_result.suggestions = []
    advice.ats_result.total_jd_keywords = 10
    advice.ats_result.matched_keywords = 8
    advice.positioning_summary = f"Good fit for {company}"
    advice.reuse_recommendation = "tweak"
    return advice


def _make_history():
    """Return a list with one ResumeWithScore-like mock (company-only retrieval)."""
    r = MagicMock()
    r.resume_id = "00000000-0000-0000-0000-000000000002"
    r.version_tag = "v1"
    r.filename = "resume.pdf"
    r.file_type = "pdf"
    r.target_company = "ACME"
    r.target_role = "SWE"
    r.ats_score = None
    r.similarity_score = 0.7
    r.last_used = "2025-02-01"
    r.usage_outcomes = []
    r.github_path = None
    r.latex_content = None
    return [r]


# ---------------------------------------------------------------------------
# Test 1: batch with 2 jobs returns 2 results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_retrieve_returns_one_result_per_job():
    """
    POST /vault/retrieve/batch with a list of 2 jobs must return 2 results.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-001"

    company_a = "Stripe"
    company_b = "Notion"

    with patch(
        "app.routers.vault._retrieval_agent",
    ) as mock_agent:
        mock_agent.get_positioning_advice = AsyncMock(
            side_effect=[
                _make_advice(company_a, ats_score=85.0),
                _make_advice(company_b, ats_score=72.0),
            ]
        )

        from app.routers.vault import batch_retrieve
        from app.schemas.vault_batch import BatchRetrieveItem, BatchRetrieveRequest

        req = BatchRetrieveRequest(
            jobs=[
                BatchRetrieveItem(company=company_a, role="Backend Eng", jd_snippet="Python APIs"),
                BatchRetrieveItem(company=company_b, role="Product Eng", jd_snippet="React Notion"),
            ]
        )
        response = await batch_retrieve(req, db=mock_db, user=mock_user)

    assert len(response.results) == 2


# ---------------------------------------------------------------------------
# Test 2: empty jobs list returns empty results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_retrieve_empty_jobs_returns_empty():
    """
    POST /vault/retrieve/batch with jobs=[] must return results=[].
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-002"

    from app.routers.vault import batch_retrieve
    from app.schemas.vault_batch import BatchRetrieveRequest

    req = BatchRetrieveRequest(jobs=[])
    response = await batch_retrieve(req, db=mock_db, user=mock_user)

    assert response.results == []


# ---------------------------------------------------------------------------
# Test 3: batch of 3 jobs returns 3 results with ats_score for each
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_retrieve_three_jobs_with_ats_scores():
    """
    Batch of 3 jobs must return 3 BatchRetrieveResult items, each with an ats_score.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-003"

    companies = ["Google", "Meta", "Apple"]
    scores = [90.0, 78.0, 65.0]

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_positioning_advice = AsyncMock(
            side_effect=[_make_advice(c, s) for c, s in zip(companies, scores, strict=False)]
        )

        from app.routers.vault import batch_retrieve
        from app.schemas.vault_batch import BatchRetrieveItem, BatchRetrieveRequest

        req = BatchRetrieveRequest(
            jobs=[
                BatchRetrieveItem(company=c, role="SWE", jd_snippet="Python ML systems")
                for c in companies
            ]
        )
        response = await batch_retrieve(req, db=mock_db, user=mock_user)

    assert len(response.results) == 3
    for result, expected_score in zip(response.results, scores, strict=False):
        assert result.ats_score == expected_score


# ---------------------------------------------------------------------------
# Test 4: results maintain order (result[i] corresponds to jobs[i])
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_retrieve_preserves_order():
    """
    Results must be in the same order as the input jobs list (asyncio.gather preserves order).
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-004"

    companies = ["Alpha", "Beta", "Gamma", "Delta"]

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_positioning_advice = AsyncMock(
            side_effect=[_make_advice(c, ats_score=float(i * 10)) for i, c in enumerate(companies)]
        )

        from app.routers.vault import batch_retrieve
        from app.schemas.vault_batch import BatchRetrieveItem, BatchRetrieveRequest

        req = BatchRetrieveRequest(
            jobs=[
                BatchRetrieveItem(company=c, role="Eng", jd_snippet="Python systems")
                for c in companies
            ]
        )
        response = await batch_retrieve(req, db=mock_db, user=mock_user)

    assert len(response.results) == 4
    for i, (result, company) in enumerate(zip(response.results, companies, strict=False)):
        assert result.company == company, f"Position {i}: expected {company}, got {result.company}"
        assert result.ats_score == float(i * 10)


# ---------------------------------------------------------------------------
# Test 5: max 50 jobs enforced (51 jobs → 422)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_retrieve_max_50_enforced():
    """
    Sending 51 jobs must fail schema validation with a 422 Unprocessable Entity.
    Uses the HTTP client to test the FastAPI validation layer.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-005"

    app = create_app()
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user

    # 51 jobs — must exceed the max_length=50 constraint
    payload = {
        "jobs": [
            {"company": f"Company{i}", "role": "SWE", "jd_snippet": "Python"} for i in range(51)
        ]
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/vault/retrieve/batch", json=payload)

    assert (
        response.status_code == 422
    ), f"Expected 422 for 51 jobs, got {response.status_code}: {response.text}"
