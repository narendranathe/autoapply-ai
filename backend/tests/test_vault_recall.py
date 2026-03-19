"""
Tests for VaultRecallConnector backend changes — similarity_score in /vault/answers/similar.

Issue #58: /vault/answers/similar now returns similarity_score per answer, computed as
reward_score * 0.7 + tfidf_similarity(question_text) * 0.3 (composite score, 0.0–1.0).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_answer(
    question_text: str = "Tell me about your Python experience",
    answer_text: str = "I have 5 years of Python experience.",
    category: str = "technical",
    reward_score: float = 0.8,
) -> MagicMock:
    """Return a minimal ApplicationAnswer-like mock."""
    ans = MagicMock()
    ans.id = "00000000-0000-0000-0000-000000000001"
    ans.question_text = question_text
    ans.answer_text = answer_text
    ans.company_name = "TestCorp"
    ans.question_category = category
    ans.reward_score = reward_score
    ans.feedback = "accepted"
    ans.word_count = len(answer_text.split())
    ans.created_at = MagicMock()
    ans.created_at.isoformat.return_value = "2025-01-01T00:00:00"
    return ans


# ---------------------------------------------------------------------------
# Test 1: /similar returns similarity_score in each answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_similar_endpoint_returns_similarity_score():
    """
    GET /vault/answers/similar returns similarity_score per answer.
    similarity_score must be a float in [0.0, 1.0].
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-001"

    answer = _make_answer(
        question_text="Tell me about your Python experience",
        category="technical",
    )
    # Return value: list of (composite_score, answer) tuples
    mock_best = [(0.85, answer)]

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_best_answers_for_question = AsyncMock(return_value=mock_best)

        from app.routers.vault.answers import get_similar_answers

        result = await get_similar_answers(
            question_text="Describe your Python skills",
            question_category="technical",
            top_k=3,
            db=mock_db,
            user=mock_user,
        )

    assert "answers" in result
    assert len(result["answers"]) == 1
    item = result["answers"][0]
    assert "similarity_score" in item, "similarity_score key must be present in each answer"
    assert isinstance(item["similarity_score"], float)
    assert 0.0 <= item["similarity_score"] <= 1.0


# ---------------------------------------------------------------------------
# Test 2: similarity_score equals the composite score (rounded to 4dp)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_similarity_score_matches_composite_score():
    """
    similarity_score in the response must equal the composite score returned by
    get_best_answers_for_question, rounded to 4 decimal places.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-002"

    answer = _make_answer(reward_score=0.9)
    composite = 0.7123456789  # raw composite from the ranking function
    expected_rounded = round(composite, 4)

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_best_answers_for_question = AsyncMock(return_value=[(composite, answer)])

        from app.routers.vault.answers import get_similar_answers

        result = await get_similar_answers(
            question_text="test question",
            question_category="technical",
            top_k=1,
            db=mock_db,
            user=mock_user,
        )

    assert result["answers"][0]["similarity_score"] == expected_rounded


# ---------------------------------------------------------------------------
# Test 3: empty vault returns empty list without error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_vault_returns_empty_list():
    """
    When no answers exist, get_similar_answers returns answers=[] and total=0.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-003"

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_best_answers_for_question = AsyncMock(return_value=[])

        from app.routers.vault.answers import get_similar_answers

        result = await get_similar_answers(
            question_text="Any question",
            question_category="custom",
            top_k=3,
            db=mock_db,
            user=mock_user,
        )

    assert result["answers"] == []
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# Test 4: multiple answers all have valid similarity_score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_answers_all_have_similarity_score():
    """
    When top_k=3, all returned answers must have similarity_score in [0.0, 1.0].
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-004"

    answers = [
        (_make_answer(question_text=f"Question {i}", reward_score=float(i) / 10), score)
        for i, score in [(8, 0.85), (7, 0.72), (6, 0.61)]
    ]
    # Restructure to (score, answer) tuples as the real function returns
    scored = [(score, ans) for ans, score in answers]

    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_best_answers_for_question = AsyncMock(return_value=scored)

        from app.routers.vault.answers import get_similar_answers

        result = await get_similar_answers(
            question_text="Python engineering question",
            question_category="technical",
            top_k=3,
            db=mock_db,
            user=mock_user,
        )

    assert len(result["answers"]) == 3
    assert result["total"] == 3
    for item in result["answers"]:
        assert "similarity_score" in item
        assert 0.0 <= item["similarity_score"] <= 1.0


# ---------------------------------------------------------------------------
# Test 5: response includes all required fields alongside similarity_score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_similar_response_includes_all_required_fields():
    """
    Each answer in the /similar response must include the full set of fields
    expected by the VaultRecallConnector extension module.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-005"

    answer = _make_answer()
    with patch("app.routers.vault._retrieval_agent") as mock_agent:
        mock_agent.get_best_answers_for_question = AsyncMock(return_value=[(0.75, answer)])

        from app.routers.vault.answers import get_similar_answers

        result = await get_similar_answers(
            question_text="Tell me about yourself",
            question_category="behavioral",
            top_k=1,
            db=mock_db,
            user=mock_user,
        )

    required_fields = {
        "answer_id",
        "question_text",
        "answer_text",
        "company_name",
        "question_category",
        "reward_score",
        "similarity_score",
        "feedback",
        "word_count",
        "created_at",
    }
    item = result["answers"][0]
    missing = required_fields - set(item.keys())
    assert not missing, f"Response is missing fields: {missing}"
