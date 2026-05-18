"""
Tests for GET /vault/analytics flat top-level fields — Issue #139.

The Mirror dashboard reads `vault.avg_ats_score` and `vault.total_resumes` as
flat top-level fields. This module verifies the endpoint exposes them
alongside the existing nested `resumes.total` shape.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _scalar_result(value):
    """Wrap a value so result.scalar_one() / scalar_one_or_none() return it."""
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_result(items):
    """Wrap an iterable so result.scalars().all() returns it."""
    r = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = list(items)
    r.scalars.return_value = scalars
    return r


def _mock_db_with_resume_stats(
    total_resumes: int,
    unique_companies: int,
    avg_ats: float | None,
    answers: list | None = None,
) -> AsyncMock:
    """
    Build an AsyncSession mock whose four .execute() calls return, in order:
      1. all application answers
      2. count(Resume.id)
      3. count(distinct(Resume.target_company))
      4. avg(Resume.ats_score)
    """
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalars_result(answers or []),
            _scalar_result(total_resumes),
            _scalar_result(unique_companies),
            _scalar_result(avg_ats),
        ]
    )
    return db


@pytest.mark.asyncio
async def test_analytics_returns_flat_avg_ats_score():
    """avg_ats_score must be a flat top-level field (3 dp) when scores exist."""
    db = _mock_db_with_resume_stats(total_resumes=3, unique_companies=2, avg_ats=78.6666666)
    user = MagicMock(id="user-uuid-001")

    from app.routers.vault.history import get_vault_analytics

    result = await get_vault_analytics(db=db, user=user)

    assert "avg_ats_score" in result
    assert result["avg_ats_score"] == 78.667


@pytest.mark.asyncio
async def test_analytics_avg_ats_score_null_when_no_scored_resumes():
    """avg_ats_score is None when no resumes have an ats_score."""
    db = _mock_db_with_resume_stats(total_resumes=0, unique_companies=0, avg_ats=None)
    user = MagicMock(id="user-uuid-002")

    from app.routers.vault.history import get_vault_analytics

    result = await get_vault_analytics(db=db, user=user)

    assert result["avg_ats_score"] is None


@pytest.mark.asyncio
async def test_analytics_returns_flat_total_resumes_alongside_nested():
    """total_resumes is exposed flat AND the nested resumes.total survives."""
    db = _mock_db_with_resume_stats(total_resumes=5, unique_companies=3, avg_ats=82.0)
    user = MagicMock(id="user-uuid-003")

    from app.routers.vault.history import get_vault_analytics

    result = await get_vault_analytics(db=db, user=user)

    assert result["total_resumes"] == 5
    assert result["resumes"]["total"] == 5
    assert result["resumes"]["unique_companies"] == 3


@pytest.mark.asyncio
async def test_analytics_response_matches_frontend_contract():
    """
    Validate the response against the dashboard VaultAnalyticsResponse interface:
    flat fields total_resumes (number), avg_ats_score (number | null),
    avg_reward_score (number | null).
    """
    db = _mock_db_with_resume_stats(total_resumes=2, unique_companies=1, avg_ats=91.25)
    user = MagicMock(id="user-uuid-004")

    from app.routers.vault.history import get_vault_analytics

    result = await get_vault_analytics(db=db, user=user)

    assert isinstance(result["total_resumes"], int)
    assert isinstance(result["avg_ats_score"], float)
    assert result["avg_reward_score"] is None or isinstance(result["avg_reward_score"], float)


@pytest.mark.asyncio
async def test_analytics_flat_avg_reward_mirrors_nested_value():
    """Flat avg_reward_score must equal answers.avg_reward_score for consistency."""
    answer = MagicMock(
        feedback="used_as_is",
        question_category="why_company",
        reward_score=0.9,
        company_name="ACME",
    )
    db = _mock_db_with_resume_stats(
        total_resumes=1,
        unique_companies=1,
        avg_ats=70.0,
        answers=[answer],
    )
    user = MagicMock(id="user-uuid-005")

    from app.routers.vault.history import get_vault_analytics

    result = await get_vault_analytics(db=db, user=user)

    assert result["avg_reward_score"] == result["answers"]["avg_reward_score"]
    assert result["avg_reward_score"] == 0.9
