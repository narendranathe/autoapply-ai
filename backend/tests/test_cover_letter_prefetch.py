"""
Tests for GET /vault/cover-letters used by CoverLetterPreFetcher (#61).

The extension pre-fetches saved cover letters on page load so they are available
instantly when the user opens the cover letter panel. These tests verify the
endpoint returns the correct shape, supports company filtering, and handles
the empty-vault case.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user, get_db

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cover_letter_answer(
    company_name: str = "TestCorp",
    role_title: str = "Software Engineer",
    answer_text: str = "Dear Hiring Manager, I am excited to apply...",
    reward_score: float | None = 0.8,
    llm_provider_used: str = "anthropic",
) -> MagicMock:
    """Return a minimal ApplicationAnswer-like mock for a cover letter."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.company_name = company_name
    row.role_title = role_title
    row.answer_text = answer_text
    row.word_count = len(answer_text.split())
    row.reward_score = reward_score
    row.llm_provider_used = llm_provider_used
    row.question_category = "cover_letter"
    row.created_at = MagicMock()
    row.created_at.isoformat.return_value = "2025-01-15T10:00:00"
    return row


def _make_app_with_overrides(mock_user: MagicMock) -> object:
    """Create a FastAPI test app with auth + DB dependencies overridden."""
    from app.main import create_app

    mock_db = AsyncMock()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return app, mock_db


# ---------------------------------------------------------------------------
# Test 1: endpoint exists and returns 200 with correct shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cover_letters_endpoint_returns_200_with_items_and_total():
    """
    GET /api/v1/vault/cover-letters must return HTTP 200 with
    {"items": [...], "total": <int>} — the shape CoverLetterPreFetcher expects.
    """
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.clerk_id = "test_clerk_001"

    app, mock_db = _make_app_with_overrides(mock_user)

    rows = [_make_cover_letter_answer()]

    # Mock the DB execute chain: execute → scalars → all
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/vault/cover-letters")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)


# ---------------------------------------------------------------------------
# Test 2: company filter returns empty list for non-existent company
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cover_letters_company_filter_returns_empty_for_unknown_company():
    """
    GET /vault/cover-letters?company=NonExistentXYZ must return
    items=[] and total=0 when no matching cover letters exist.
    """
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.clerk_id = "test_clerk_002"

    app, mock_db = _make_app_with_overrides(mock_user)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/vault/cover-letters",
            params={"company": "NonExistentCompanyXYZ999"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# Test 3: each item contains the required fields for CoverLetterPreFetcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cover_letters_items_contain_required_fields():
    """
    Each item returned by GET /vault/cover-letters must have:
    id, company_name, role_title, answer_text, word_count, reward_score,
    llm_provider_used, created_at.
    """
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.clerk_id = "test_clerk_003"

    app, mock_db = _make_app_with_overrides(mock_user)

    rows = [
        _make_cover_letter_answer(company_name="Stripe", role_title="Backend Engineer"),
        _make_cover_letter_answer(company_name="Vercel", role_title="Platform Eng"),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/vault/cover-letters")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2

    required_fields = {
        "id",
        "company_name",
        "role_title",
        "answer_text",
        "word_count",
        "reward_score",
        "llm_provider_used",
        "created_at",
    }
    for item in data["items"]:
        missing = required_fields - set(item.keys())
        assert not missing, f"Cover letter item is missing fields: {missing}"


# ---------------------------------------------------------------------------
# Test 4: total reflects the count of items returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cover_letters_total_matches_items_length():
    """
    total in the response must equal len(items) — CoverLetterPreFetcher uses
    total to decide whether to show the "From Memory" suggestion UI.
    """
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.clerk_id = "test_clerk_004"

    app, mock_db = _make_app_with_overrides(mock_user)

    rows = [_make_cover_letter_answer(company_name=f"Company{i}") for i in range(4)]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/vault/cover-letters")

    data = resp.json()
    assert data["total"] == len(data["items"])
    assert data["total"] == 4


# ---------------------------------------------------------------------------
# Test 5: unauthenticated request is rejected with 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cover_letters_requires_auth():
    """
    GET /vault/cover-letters without authentication must return 401.
    Ensures the endpoint is not accidentally left open.
    """
    from app.main import create_app

    app = create_app()
    # No dependency overrides — real auth dependency will reject the request

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/vault/cover-letters")

    assert resp.status_code == 401
