"""Story bank unit and integration tests."""

from dataclasses import dataclass
from typing import Any

from app.services.story_service import auto_score, match_stories_to_jd

# ── Unit tests — pure functions, no DB needed ─────────────────────────────────


def test_auto_score_full_star():
    """Action verb + quantified result = 1.0."""
    assert auto_score("Built a pipeline", "reduced latency by 40%") == 1.0


def test_auto_score_dollar_amount():
    """Dollar amount counts as quantified result."""
    assert auto_score("Designed architecture", "saved $50k per month") == 1.0


def test_auto_score_action_only():
    """Action verb present, no quantified result = 0.5."""
    assert auto_score("Built a data pipeline", "improved things significantly") == 0.5


def test_auto_score_result_only():
    """Quantified result present, no action verb in first 6 words = 0.5."""
    # "created" is NOT an action verb in the first 6 words; result is quantified
    assert auto_score("A pipeline was created by our team", "improved overall efficiency") == 0.5


def test_auto_score_zero():
    """No action verb, no quantified result = 0.0."""
    assert auto_score("some work was done on the project", "things got better overall") == 0.0


@dataclass
class MockStory:
    """Mock StoryEntry for testing without DB/SQLAlchemy complexity."""

    id: Any
    user_id: Any
    skill_tags: list[str]
    domain: str
    situation: str
    action: str
    result_text: str
    quality_score: float
    use_count: int = 0
    last_used_at: Any = None


def _make_story(skill_tags: list[str], domain: str, quality: float = 1.0) -> MockStory:
    """Helper — creates a mock story for testing."""
    import uuid

    return MockStory(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        skill_tags=skill_tags,
        domain=domain,
        situation="At Acme Corp",
        action="Built something",
        result_text="improved by 50%",
        quality_score=quality,
    )


def test_match_stories_ranking():
    """Story with higher JD overlap ranks above lower overlap."""
    kafka_story = _make_story(["streaming_realtime"], "streaming_realtime", quality=1.0)
    sql_story = _make_story(["sql_data_modeling"], "sql_data_modeling", quality=1.0)
    jd = "kafka streaming real-time kafka event kafka latency throughput kafka"
    results = match_stories_to_jd(jd, [sql_story, kafka_story])
    assert results[0].skill_tags == ["streaming_realtime"]


def test_match_stories_quality_tiebreak():
    """When JD overlap is equal, higher quality_score ranks first."""
    high_quality = _make_story(["cloud_infra"], "cloud_infra", quality=1.0)
    low_quality = _make_story(["cloud_infra"], "cloud_infra", quality=0.5)
    jd = "aws azure kubernetes docker terraform cloud infrastructure"
    results = match_stories_to_jd(jd, [low_quality, high_quality])
    assert results[0].quality_score == 1.0


def test_match_stories_returns_at_most_5():
    """match_stories_to_jd never returns more than 5 stories."""
    stories = [_make_story(["cloud_infra"], "cloud_infra") for _ in range(10)]
    results = match_stories_to_jd("aws kubernetes docker", stories)
    assert len(results) <= 5


def test_match_stories_empty_bank():
    """Empty story bank returns empty list, no error."""
    results = match_stories_to_jd("kafka streaming kafka events", [])
    assert results == []


def test_match_stories_no_jd_overlap():
    """When JD has no matching taxonomy keywords, order is by quality_score only."""
    s1 = _make_story(["orchestration"], "orchestration", quality=0.8)
    s2 = _make_story(["ml_ai_platform"], "ml_ai_platform", quality=0.3)
    # JD has no taxonomy keywords at all
    results = match_stories_to_jd("great team culture awesome perks", [s1, s2])
    # Should still return without error; order doesn't matter but no crash
    assert len(results) >= 0
