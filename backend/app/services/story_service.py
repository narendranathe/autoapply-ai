"""
Story bank service.

Contains vendored SIGNAL_TAXONOMY and scoring logic from tailor-resume-work/
jd_gap_analyzer.py and star_validator.py. Keep in sync with those sources.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story import StoryEntry

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Vendored from tailor-resume-work/tailor_resume/_scripts/jd_gap_analyzer.py
# SIGNAL_TAXONOMY — keep in sync with source on structural changes
# ---------------------------------------------------------------------------
SIGNAL_TAXONOMY: dict[str, list[str]] = {
    "testing_ci_cd": [
        "test",
        "testing",
        "pytest",
        "unit test",
        "integration test",
        "ci",
        "cd",
        "ci/cd",
        "github actions",
        "azure devops",
        "devops",
        "pipeline",
        "build",
        "deploy",
        "deployment",
        "automation",
    ],
    "data_quality_observability": [
        "data quality",
        "data contract",
        "schema",
        "schema enforcement",
        "observability",
        "monitoring",
        "anomaly",
        "great expectations",
        "monte carlo",
        "soda",
        "freshness",
        "null rate",
        "volume check",
    ],
    "orchestration": [
        "airflow",
        "dagster",
        "prefect",
        "databricks jobs",
        "orchestration",
        "dag",
        "workflow",
        "scheduling",
        "backfill",
        "retry",
        "idempotent",
    ],
    "semantic_layer_governance": [
        "semantic layer",
        "metrics layer",
        "governed metrics",
        "dbt",
        "business logic",
        "single source",
        "lineage",
        "catalog",
        "governance",
        "rbac",
        "access control",
    ],
    "architecture_finops": [
        "architecture",
        "cost",
        "finops",
        "tco",
        "cloud cost",
        "optimize",
        "partition",
        "pruning",
        "compaction",
        "delta lake",
        "iceberg",
        "open table",
        "parquet",
        "storage",
        "compute",
    ],
    "streaming_realtime": [
        "streaming",
        "real-time",
        "kafka",
        "kinesis",
        "pubsub",
        "flink",
        "spark streaming",
        "event",
        "events",
        "latency",
        "throughput",
    ],
    "ml_ai_platform": [
        "ml",
        "machine learning",
        "model",
        "mlflow",
        "feature store",
        "inference",
        "training",
        "llm",
        "rag",
        "embedding",
        "vector",
        "langchain",
        "openai",
        "ai platform",
    ],
    "cloud_infra": [
        "azure",
        "aws",
        "gcp",
        "cloud",
        "kubernetes",
        "k8s",
        "docker",
        "terraform",
        "iac",
        "infrastructure",
        "container",
        "microservices",
    ],
    "leadership_ownership": [
        "lead",
        "leading",
        "mentor",
        "mentoring",
        "ownership",
        "cross-functional",
        "stakeholder",
        "communication",
        "roadmap",
        "strategy",
        "decision",
    ],
    "sql_data_modeling": [
        "sql",
        "data model",
        "data modeling",
        "dimensional",
        "star schema",
        "snowflake schema",
        "normalization",
        "olap",
        "oltp",
        "dw",
        "data warehouse",
    ],
}

# ---------------------------------------------------------------------------
# Vendored inline from star_validator — quantified result detection
# ---------------------------------------------------------------------------
_ACTION_VERBS = {
    "built",
    "designed",
    "led",
    "reduced",
    "increased",
    "improved",
    "migrated",
    "implemented",
    "created",
    "deployed",
    "automated",
    "optimized",
    "scaled",
    "refactored",
    "delivered",
    "launched",
}
_RESULT_PATTERN = re.compile(r"\b\d+(\.\d+)?\s?%|\$\s?\d[\d,]*|from\b.{3,40}\bto\b", re.IGNORECASE)


def auto_score(action: str, result_text: str) -> float:
    """Inline STAR compliance score. Returns 0.0, 0.5, or 1.0."""
    combined = f"{action} {result_text}"
    first_words = combined.lower().split()[:6]
    has_action = any(v in first_words for v in _ACTION_VERBS)
    has_result = bool(_RESULT_PATTERN.search(combined))
    return round(0.5 * int(has_action) + 0.5 * int(has_result), 2)


# ---------------------------------------------------------------------------
# Match algorithm
# ---------------------------------------------------------------------------
def match_stories_to_jd(jd_text: str, stories: list[StoryEntry]) -> list[StoryEntry]:
    """Return top-5 stories most relevant to the JD, ranked by overlap * quality."""
    jd_lower = jd_text.lower()
    category_freq: dict[str, int] = {
        cat: sum(jd_lower.count(kw) for kw in kws) for cat, kws in SIGNAL_TAXONOMY.items()
    }

    def story_score(s: StoryEntry) -> float:
        tags: list[str] = s.skill_tags if isinstance(s.skill_tags, list) else []
        overlap = sum(category_freq.get(tag, 0) for tag in tags)
        return overlap * s.quality_score

    return sorted(stories, key=story_score, reverse=True)[:5]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
async def get_user_stories(
    db: AsyncSession,
    user_id: uuid.UUID,
    domain: str | None = None,
    skill: str | None = None,
    min_quality: float = 0.0,
) -> list[StoryEntry]:
    stmt = (
        select(StoryEntry)
        .where(StoryEntry.user_id == user_id)
        .where(StoryEntry.quality_score >= min_quality)
        .order_by(StoryEntry.quality_score.desc())
    )
    if domain:
        stmt = stmt.where(StoryEntry.domain == domain)
    if skill:
        stmt = stmt.where(StoryEntry.skill_tags.contains([skill]))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def increment_story_usage(db: AsyncSession, story_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Increment use_count and set last_used_at. Verifies ownership."""
    result = await db.execute(
        select(StoryEntry).where(StoryEntry.id == story_id, StoryEntry.user_id == user_id)
    )
    story = result.scalar_one_or_none()
    if story:
        story.use_count += 1
        story.last_used_at = datetime.now(tz=UTC)
        await db.commit()
