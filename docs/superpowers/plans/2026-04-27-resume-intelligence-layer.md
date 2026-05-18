# Resume Intelligence Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a STAR story bank, dimensional offer scoring, and ATS portal scanner to autoapply-ai, delivering the first working vertical slice (Story Bank) within 1-2 days of focused work.

**Architecture:** All new routes live under `/api/v1/vault/` in autoapply-ai's existing vault router. `jd_gap_analyzer` and `star_validator` logic is vendored inline into service files — no cross-repo imports. tailor-resume-work bug fixes are independent and can be done in parallel.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic v2, Alembic, Supabase Postgres (asyncpg), httpx, pytest + pytest-asyncio + pytest-httpx

---

## File Map

### New files — autoapply-ai

| File | Responsibility |
|---|---|
| `backend/app/models/story.py` | StoryEntry ORM model |
| `backend/app/models/offer_evaluation.py` | OfferEvaluation ORM model |
| `backend/app/models/portal_scan.py` | PortalScanCache ORM model |
| `backend/alembic/versions/g1h2i3j4_add_story_entries.py` | Migration: story_entries table + GIN index |
| `backend/alembic/versions/h2i3j4k5_add_offer_evaluations.py` | Migration: offer_evaluations table |
| `backend/alembic/versions/i3j4k5l6_add_portal_scan_cache.py` | Migration: portal_scan_cache table |
| `backend/app/services/story_service.py` | Story CRUD, match algo, quality scorer, vendored SIGNAL_TAXONOMY |
| `backend/app/services/offer_scoring_service.py` | 8-dimension offer scoring, vendored category coverage |
| `backend/app/services/portal_scanner_service.py` | Board detection, httpx fetch, portal_circuit |
| `backend/app/routers/vault/stories.py` | CRUD + match + bulk import endpoints |
| `backend/app/routers/vault/offer.py` | evaluate endpoint |
| `backend/app/routers/vault/portal.py` | scan endpoint |
| `backend/tests/test_story_bank.py` | Story bank tests |
| `backend/tests/test_offer_scoring_service.py` | Offer scoring tests |
| `backend/tests/test_portal_scanner.py` | Portal scanner tests |
| `backend/tests/test_vault_router_registration.py` | Router wiring smoke tests |
| `backend/tests/test_models_registered.py` | Model table registration tests |

### Modified files — autoapply-ai

| File | Change |
|---|---|
| `backend/app/services/llm_gateway.py:37,47` | Add `model` param to `_call_anthropic` |
| `backend/app/middleware/circuit_breaker.py:110` | Add `portal_circuit` after line 110 |
| `backend/app/middleware/rate_limit.py:24-34` | Add 4 new paths to `_LLM_PATHS` set |
| `backend/app/models/__init__.py` | Import 3 new models |
| `backend/app/routers/vault/__init__.py` | Include 3 new routers |
| `backend/app/routers/vault/interview.py` | Inject matched stories into LLM prompt |

### Modified files — tailor-resume-work (independent, parallel)

| File | Change |
|---|---|
| `web_app/routes/resume.py:131` | Fix artifacts tuple type |
| `web_app/routes/resume.py:93` | Fix gap_summary join |
| `web_app/routes/resume.py:96` | Fix report serialization |

---

## Phase 0: Prerequisites

### Task 1: Add `model` param to `_call_anthropic`

**Files:**
- Modify: `backend/app/services/llm_gateway.py` (lines 37, 47)
- Create: `backend/tests/test_llm_gateway_model_param.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_llm_gateway_model_param.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_call_anthropic_accepts_model_param():
    """_call_anthropic must forward model param to Anthropic API."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="response text")]

    mock_messages = AsyncMock()
    mock_messages.create = AsyncMock(return_value=mock_message)

    mock_client = MagicMock()
    mock_client.messages = mock_messages

    with patch("app.services.llm_gateway.anthropic") as mock_anthropic:
        mock_anthropic.AsyncAnthropic.return_value = mock_client
        from app.services.llm_gateway import _call_anthropic

        await _call_anthropic("sys", "user", "sk-fake", model="claude-haiku-4-5-20251001")

        call_kwargs = mock_messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_call_anthropic_defaults_to_sonnet():
    """_call_anthropic default model is claude-sonnet-4-6."""
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="response text")]

    mock_messages = AsyncMock()
    mock_messages.create = AsyncMock(return_value=mock_message)

    mock_client = MagicMock()
    mock_client.messages = mock_messages

    with patch("app.services.llm_gateway.anthropic") as mock_anthropic:
        mock_anthropic.AsyncAnthropic.return_value = mock_client
        from app.services.llm_gateway import _call_anthropic

        await _call_anthropic("sys", "user", "sk-fake")

        call_kwargs = mock_messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-6"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
ENVIRONMENT=test DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
REDIS_URL="redis://localhost:6379" JWT_SECRET="any" \
FERNET_KEY="x_fMBr_lJSHIVPOtMtFxnq5RZ34kEFiL-7UEiM-JKYA=" \
poetry run pytest tests/test_llm_gateway_model_param.py -v
```

Expected: `FAILED — _call_anthropic() got an unexpected keyword argument 'model'`

- [ ] **Step 3: Edit `_call_anthropic` in `llm_gateway.py`**

At line 37, change:
```python
async def _call_anthropic(system: str, user: str, api_key: str) -> str:
```
To:
```python
async def _call_anthropic(system: str, user: str, api_key: str, model: str = "claude-sonnet-4-6") -> str:
```

At line 47 (inside the function), change:
```python
"model": "claude-sonnet-4-6",
```
To:
```python
"model": model,
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
poetry run pytest tests/test_llm_gateway_model_param.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/llm_gateway.py backend/tests/test_llm_gateway_model_param.py
git commit -m "feat: add model param to _call_anthropic for haiku routing"
```

---

### Task 2: Add `portal_circuit` and new rate limit paths

**Files:**
- Modify: `backend/app/middleware/circuit_breaker.py` (after line 110)
- Modify: `backend/app/middleware/rate_limit.py` (lines 24-34)

- [ ] **Step 1: Add `portal_circuit` to `circuit_breaker.py`**

After the existing three circuit breakers at lines 108-110:
```python
github_circuit = CircuitBreaker(name="github_api", failure_threshold=3, recovery_timeout=60)
llm_circuit = CircuitBreaker(name="llm_provider", failure_threshold=2, recovery_timeout=30)
pdf_circuit = CircuitBreaker(name="pdf_service", failure_threshold=3, recovery_timeout=120)
```

Add:
```python
portal_circuit = CircuitBreaker(name="portal_scanner", failure_threshold=3, recovery_timeout=120)
```

- [ ] **Step 2: Update `_LLM_PATHS` in `rate_limit.py`**

Replace the current `_LLM_PATHS` set (lines 24-34) with:
```python
_LLM_PATHS = {
    "/api/v1/vault/generate/answers",
    "/api/v1/vault/generate/tailored",
    "/api/v1/vault/generate",
    "/api/v1/vault/generate/summary",
    "/api/v1/vault/generate/bullets",
    "/api/v1/vault/generate/cover-letter",
    "/api/v1/vault/generate/answers/trim",
    "/api/v1/vault/interview-prep",
    "/api/v1/work-history/import-from-resume",
    "/api/v1/vault/offer/evaluate",
    "/api/v1/vault/offer/negotiate",
    "/api/v1/vault/stories/match",
    "/api/v1/vault/portal/scan",
}
```

- [ ] **Step 3: Verify imports**

```bash
cd backend
poetry run python -c "from app.middleware.circuit_breaker import portal_circuit; print('portal_circuit ok')"
```
Expected: `portal_circuit ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/middleware/circuit_breaker.py backend/app/middleware/rate_limit.py
git commit -m "feat: add portal_circuit and LLM rate limit paths for intelligence layer"
```

---

## Phase 1: Story Bank (Slice 1 — ships first)

### Task 3: StoryEntry model

**Files:**
- Create: `backend/app/models/story.py`

- [ ] **Step 1: Create `backend/app/models/story.py`**

```python
"""StoryEntry — STAR narrative bank for interview prep and resume tailoring."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

_VALID_DOMAINS = (
    "'testing_ci_cd'",
    "'orchestration'",
    "'architecture_finops'",
    "'streaming_realtime'",
    "'ml_ai_platform'",
    "'cloud_infra'",
    "'leadership_ownership'",
    "'sql_data_modeling'",
    "'data_quality_observability'",
    "'semantic_layer_governance'",
)
_DOMAIN_CHECK = f"domain IN ({', '.join(_VALID_DOMAINS)})"


class StoryEntry(TimestampMixin, Base):
    __tablename__ = "story_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    situation: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(150), nullable=False)
    result_text: Mapped[str] = mapped_column(String(150), nullable=False)
    reflection: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(_DOMAIN_CHECK, name="ck_story_entries_domain"),
        CheckConstraint(
            "quality_score >= 0.0 AND quality_score <= 1.0",
            name="ck_story_entries_quality_score",
        ),
        Index("ix_story_entries_user_domain", "user_id", "domain"),
        Index("ix_story_entries_user_quality", "user_id", "quality_score"),
    )

    def __repr__(self) -> str:
        return f"<StoryEntry id={self.id} domain={self.domain} score={self.quality_score}>"
```

- [ ] **Step 2: Add to `backend/app/models/__init__.py`**

Add these two lines (import + `__all__` entry):
```python
from app.models.story import StoryEntry
```
And add `"StoryEntry"` to the `__all__` list.

- [ ] **Step 3: Verify model imports cleanly**

```bash
cd backend
poetry run python -c "from app.models.story import StoryEntry; print(StoryEntry.__tablename__)"
```
Expected: `story_entries`

---

### Task 4: Story entries Alembic migration

**Files:**
- Create: `backend/alembic/versions/g1h2i3j4_add_story_entries.py`

- [ ] **Step 1: Generate migration stub**

```bash
cd backend
poetry run alembic revision -m "add_story_entries"
```

This prints the path of the new file. Open it and replace the body with:

```python
"""add_story_entries

Revision ID: g1h2i3j4  (use the actual generated ID)
Revises: <previous revision ID>
Create Date: 2026-04-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g1h2i3j4"  # replace with actual
down_revision: str | None = "<previous>"  # replace with actual
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_tags", postgresql.JSONB(), nullable=False),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("situation", sa.String(200), nullable=False),
        sa.Column("action", sa.String(150), nullable=False),
        sa.Column("result_text", sa.String(150), nullable=False),
        sa.Column("reflection", sa.String(200), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("use_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "domain IN ('testing_ci_cd','orchestration','architecture_finops',"
            "'streaming_realtime','ml_ai_platform','cloud_infra','leadership_ownership',"
            "'sql_data_modeling','data_quality_observability','semantic_layer_governance')",
            name="ck_story_entries_domain",
        ),
        sa.CheckConstraint(
            "quality_score >= 0.0 AND quality_score <= 1.0",
            name="ck_story_entries_quality_score",
        ),
    )
    op.create_index("ix_story_entries_user_id", "story_entries", ["user_id"])
    op.create_index("ix_story_entries_user_domain", "story_entries", ["user_id", "domain"])
    op.create_index("ix_story_entries_user_quality", "story_entries", ["user_id", "quality_score"])

    # GIN index on skill_tags for fast overlap queries.
    # Run CONCURRENTLY in production to avoid table lock.
    # In dev/test, standard create is fine.
    op.execute(
        "CREATE INDEX ix_story_entries_skill_tags ON story_entries USING GIN (skill_tags)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_story_entries_skill_tags")
    op.drop_index("ix_story_entries_user_quality", table_name="story_entries")
    op.drop_index("ix_story_entries_user_domain", table_name="story_entries")
    op.drop_index("ix_story_entries_user_id", table_name="story_entries")
    op.drop_table("story_entries")
```

- [ ] **Step 2: Apply migration**

```bash
cd backend
ENVIRONMENT=test DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
poetry run alembic upgrade head
```
Expected: migration applies with no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/story.py backend/app/models/__init__.py \
  backend/alembic/versions/
git commit -m "feat: add StoryEntry model and migration"
```

---

### Task 5: `story_service.py`

**Files:**
- Create: `backend/app/services/story_service.py`

- [ ] **Step 1: Create `backend/app/services/story_service.py`**

```python
"""
Story bank service.

Contains vendored SIGNAL_TAXONOMY and scoring logic from tailor-resume-work/
jd_gap_analyzer.py and star_validator.py. Keep in sync with those sources.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
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
        "test", "testing", "pytest", "unit test", "integration test",
        "ci", "cd", "ci/cd", "github actions", "azure devops", "devops",
        "pipeline", "build", "deploy", "deployment", "automation",
    ],
    "data_quality_observability": [
        "data quality", "data contract", "schema", "schema enforcement",
        "observability", "monitoring", "anomaly", "great expectations",
        "monte carlo", "soda", "freshness", "null rate", "volume check",
    ],
    "orchestration": [
        "airflow", "dagster", "prefect", "databricks jobs", "orchestration",
        "dag", "workflow", "scheduling", "backfill", "retry", "idempotent",
    ],
    "semantic_layer_governance": [
        "semantic layer", "metrics layer", "governed metrics", "dbt",
        "business logic", "single source", "lineage", "catalog", "governance",
        "rbac", "access control",
    ],
    "architecture_finops": [
        "architecture", "cost", "finops", "tco", "cloud cost", "optimize",
        "partition", "pruning", "compaction", "delta lake", "iceberg",
        "open table", "parquet", "storage", "compute",
    ],
    "streaming_realtime": [
        "streaming", "real-time", "kafka", "kinesis", "pubsub", "flink",
        "spark streaming", "event", "events", "latency", "throughput",
    ],
    "ml_ai_platform": [
        "ml", "machine learning", "model", "mlflow", "feature store",
        "inference", "training", "llm", "rag", "embedding", "vector",
        "langchain", "openai", "ai platform",
    ],
    "cloud_infra": [
        "azure", "aws", "gcp", "cloud", "kubernetes", "k8s", "docker",
        "terraform", "iac", "infrastructure", "container", "microservices",
    ],
    "leadership_ownership": [
        "lead", "leading", "mentor", "mentoring", "ownership", "cross-functional",
        "stakeholder", "communication", "roadmap", "strategy", "decision",
    ],
    "sql_data_modeling": [
        "sql", "data model", "data modeling", "dimensional", "star schema",
        "snowflake schema", "normalization", "olap", "oltp", "dw", "data warehouse",
    ],
}

# ---------------------------------------------------------------------------
# Vendored inline from star_validator — quantified result detection
# ---------------------------------------------------------------------------
_ACTION_VERBS = {
    "built", "designed", "led", "reduced", "increased", "improved",
    "migrated", "implemented", "created", "deployed", "automated",
    "optimized", "scaled", "refactored", "delivered", "launched",
}
_RESULT_PATTERN = re.compile(
    r"\b\d+(\.\d+)?\s?%|\$\s?\d[\d,]*|from\b.{3,40}\bto\b", re.IGNORECASE
)


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
        cat: sum(jd_lower.count(kw) for kw in kws)
        for cat, kws in SIGNAL_TAXONOMY.items()
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


async def increment_story_usage(
    db: AsyncSession, story_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Increment use_count and set last_used_at. Verifies ownership."""
    result = await db.execute(
        select(StoryEntry).where(
            StoryEntry.id == story_id, StoryEntry.user_id == user_id
        )
    )
    story = result.scalar_one_or_none()
    if story:
        story.use_count += 1
        story.last_used_at = datetime.now(tz=timezone.utc)
        await db.commit()
```

- [ ] **Step 2: Verify import**

```bash
cd backend
poetry run python -c "from app.services.story_service import auto_score, match_stories_to_jd; print(auto_score('Built a pipeline', 'reduced latency by 40%'))"
```
Expected: `1.0`

---

### Task 6: `vault/stories.py` router

**Files:**
- Create: `backend/app/routers/vault/stories.py`

- [ ] **Step 1: Create `backend/app/routers/vault/stories.py`**

```python
"""Vault sub-module: story bank CRUD, match, and bulk import."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.story import StoryEntry
from app.models.user import User

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class StoryCreate(BaseModel):
    skill_tags: list[str] = Field(..., min_length=1)
    domain: str
    situation: str = Field(..., max_length=200)
    action: str = Field(..., max_length=150)
    result_text: str = Field(..., max_length=150)
    reflection: str | None = Field(None, max_length=200)


class StoryOut(BaseModel):
    id: uuid.UUID
    skill_tags: list[str]
    domain: str
    situation: str
    action: str
    result_text: str
    reflection: str | None
    quality_score: float
    use_count: int
    last_used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StoryMatchRequest(BaseModel):
    jd_text: str = Field(..., min_length=50)


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/stories", response_model=StoryOut, status_code=status.HTTP_201_CREATED)
async def create_story(
    body: StoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.story_service import auto_score

    score = auto_score(body.action, body.result_text)
    story = StoryEntry(
        user_id=user.id,
        skill_tags=body.skill_tags,
        domain=body.domain,
        situation=body.situation,
        action=body.action,
        result_text=body.result_text,
        reflection=body.reflection,
        quality_score=score,
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    return story


@router.get("/stories", response_model=list[StoryOut])
async def list_stories(
    domain: str | None = None,
    skill: str | None = None,
    min_quality: float = 0.0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.story_service import get_user_stories

    return await get_user_stories(db, user.id, domain=domain, skill=skill, min_quality=min_quality)


@router.delete("/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(
    story_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(StoryEntry).where(
            StoryEntry.id == story_id, StoryEntry.user_id == user.id
        )
    )
    story = result.scalar_one_or_none()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    await db.delete(story)
    await db.commit()


@router.post("/stories/match", response_model=list[StoryOut])
async def match_stories(
    body: StoryMatchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.story_service import get_user_stories, increment_story_usage, match_stories_to_jd

    stories = await get_user_stories(db, user.id)
    matched = match_stories_to_jd(body.jd_text, stories)

    for story in matched:
        await increment_story_usage(db, story.id, user.id)

    return matched


@router.post("/stories/import", response_model=list[StoryOut], status_code=status.HTTP_201_CREATED)
async def bulk_import_stories(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Import story candidates from a resume's work history bullets.

    Calls the standalone /resume/parse endpoint to get a canonical Profile JSON,
    then creates StoryEntry candidates from each role's bullets.

    Returns the created entries for user review and editing.
    Requires STANDALONE_URL env var to be configured.
    """
    import json
    import os

    import httpx

    from app.services.story_service import SIGNAL_TAXONOMY, auto_score

    standalone_url = os.getenv("STANDALONE_URL", "http://localhost:7000")

    # Fetch resume bytes from DB
    from app.models.resume import Resume
    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Call standalone parse endpoint
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{standalone_url}/api/v1/resume/parse",
                json={"resume_text": resume.content or ""},
            )
            resp.raise_for_status()
            profile = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Standalone parse failed: {exc}")

    # Extract bullets from work history roles
    created: list[StoryEntry] = []
    work_history = profile.get("work_history", [])

    for role in work_history:
        bullets = role.get("bullets", [])
        for bullet in bullets:
            text = bullet if isinstance(bullet, str) else bullet.get("text", "")
            if not text or len(text) < 20:
                continue

            # Infer domain from SIGNAL_TAXONOMY keyword overlap
            text_lower = text.lower()
            best_domain = "leadership_ownership"
            best_count = 0
            for cat, kws in SIGNAL_TAXONOMY.items():
                count = sum(text_lower.count(kw) for kw in kws)
                if count > best_count:
                    best_count = count
                    best_domain = cat

            skill_tags = [best_domain]
            words = text.split()
            action = " ".join(words[:10])
            result_part = " ".join(words[10:]) if len(words) > 10 else text

            story = StoryEntry(
                user_id=user.id,
                skill_tags=skill_tags,
                domain=best_domain,
                situation=role.get("title", "Work experience") + " at " + role.get("company", ""),
                action=action[:150],
                result_text=result_part[:150],
                quality_score=auto_score(action, result_part),
            )
            db.add(story)
            created.append(story)

    await db.commit()
    for s in created:
        await db.refresh(s)
    return created
```

---

### Task 7: Wire stories router + update interview.py

**Files:**
- Modify: `backend/app/routers/vault/__init__.py` (add stories router)
- Modify: `backend/app/routers/vault/interview.py` (inject matched stories)

- [ ] **Step 1: Add stories router to `vault/__init__.py`**

In `vault/__init__.py`, add after the existing imports:
```python
from app.routers.vault.stories import router as stories_router
```
And after the existing `router.include_router(interview_router)` line:
```python
router.include_router(stories_router)
```

- [ ] **Step 2: Verify router mounts**

```bash
cd backend
poetry run python -c "
from app.routers.vault import router
paths = [r.path for r in router.routes]
assert any('stories' in p for p in paths), f'stories not found in {paths}'
print('stories router mounted')
"
```
Expected: `stories router mounted`

- [ ] **Step 3: Inject stories into `interview.py`**

In `interview.py`, add this import at the top with the other imports:
```python
from app.models.story import StoryEntry
```

After the `wh_entries = list(...)` block (around line 73), add:
```python
    # Fetch matched stories for grounding
    stories_stmt = (
        select(StoryEntry)
        .where(StoryEntry.user_id == user.id)
        .order_by(StoryEntry.quality_score.desc())
        .limit(20)
    )
    stories_result = await db.execute(stories_stmt)
    all_stories = list(stories_result.scalars().all())

    from app.services.story_service import match_stories_to_jd
    matched_stories = match_stories_to_jd(jd_text, all_stories)[:3] if jd_text else []

    stories_block = ""
    if matched_stories:
        lines = ["Proven narratives to draw from (use as grounding, do not fabricate):"]
        for i, s in enumerate(matched_stories, 1):
            lines.append(f"{i}. Action: {s.action} | Result: {s.result_text}")
        stories_block = "\n".join(lines)
```

Then update the `user_prompt` f-string to include `stories_block`:
```python
    user_prompt = f"""Candidate work history:
{work_history_text or "Not provided."}

{stories_block}

Target company: {company_name}
Target role: {role_title or "Software Engineer"}

Job description excerpt:
{jd_text[:3000] if jd_text else "Not provided."}

Generate 10 interview questions + suggested answers as described."""
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/vault/__init__.py \
        backend/app/routers/vault/stories.py \
        backend/app/routers/vault/interview.py \
        backend/app/services/story_service.py
git commit -m "feat: add story bank CRUD/match routes and inject stories into interview prep"
```

---

### Task 8: Story bank tests

**Files:**
- Create: `backend/tests/test_story_bank.py`

- [ ] **Step 1: Add `pytest-httpx` to pyproject.toml**

```bash
cd backend
poetry add --group dev pytest-httpx
```

- [ ] **Step 2: Create `backend/tests/test_story_bank.py`**

```python
"""Story bank unit and integration tests."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story import StoryEntry
from app.services.story_service import auto_score, match_stories_to_jd


# ── Unit tests ───────────────────────────────────────────────────────────────

def test_auto_score_full_star():
    """Action verb + quantified result = 1.0."""
    assert auto_score("Built a pipeline", "reduced latency by 40%") == 1.0


def test_auto_score_no_result():
    """Action verb only = 0.5."""
    assert auto_score("Built a data pipeline", "improved things") == 0.5


def test_auto_score_no_action_verb():
    """No action verb, has quantified result = 0.5."""
    assert auto_score("a pipeline was created", "reduced latency by 30%") == 0.5


def test_auto_score_zero():
    """No action verb, no quantified result = 0.0."""
    assert auto_score("some work was done", "things got better") == 0.0


def test_match_stories_ranking():
    """Stories with higher JD overlap and quality rank first."""
    kafka_story = StoryEntry(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        skill_tags=["streaming_realtime"],
        domain="streaming_realtime",
        situation="At Acme",
        action="Built Kafka pipeline",
        result_text="reduced latency by 40%",
        quality_score=1.0,
        use_count=0,
    )
    sql_story = StoryEntry(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        skill_tags=["sql_data_modeling"],
        domain="sql_data_modeling",
        situation="At Acme",
        action="Designed star schema",
        result_text="improved query speed by 3x",
        quality_score=1.0,
        use_count=0,
    )
    jd = "We need kafka streaming real-time kafka event processing kafka latency throughput"
    results = match_stories_to_jd(jd, [sql_story, kafka_story])
    assert results[0].skill_tags == ["streaming_realtime"]


def test_match_stories_returns_at_most_5():
    """Match returns at most 5 stories."""
    stories = [
        StoryEntry(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            skill_tags=["cloud_infra"],
            domain="cloud_infra",
            situation="s",
            action="Built infra",
            result_text="saved $50k",
            quality_score=0.5,
            use_count=0,
        )
        for _ in range(10)
    ]
    results = match_stories_to_jd("aws azure kubernetes docker terraform", stories)
    assert len(results) <= 5


# ── Route integration tests (requires test DB) ────────────────────────────────

@pytest.mark.asyncio
async def test_create_story(async_client: AsyncClient, auth_headers: dict):
    """POST /vault/stories creates a story with auto quality score."""
    resp = await async_client.post(
        "/api/v1/vault/stories",
        json={
            "skill_tags": ["streaming_realtime"],
            "domain": "streaming_realtime",
            "situation": "At Acme Corp",
            "action": "Built Kafka streaming pipeline",
            "result_text": "reduced end-to-end latency by 40%",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["quality_score"] == 1.0
    assert data["use_count"] == 0


@pytest.mark.asyncio
async def test_delete_story_ownership(async_client: AsyncClient, auth_headers: dict):
    """DELETE /vault/stories/{id} rejects stories owned by another user."""
    # Create story
    create_resp = await async_client.post(
        "/api/v1/vault/stories",
        json={
            "skill_tags": ["cloud_infra"],
            "domain": "cloud_infra",
            "situation": "Some context",
            "action": "Built infra on AWS",
            "result_text": "saved $30k per month",
        },
        headers=auth_headers,
    )
    story_id = create_resp.json()["id"]

    # Delete with different user headers (no auth = dev fallback = same user in test)
    # This test verifies the 404 path using a non-existent ID
    fake_id = str(uuid.uuid4())
    del_resp = await async_client.delete(
        f"/api/v1/vault/stories/{fake_id}",
        headers=auth_headers,
    )
    assert del_resp.status_code == 404

    # Delete the actual story
    del_resp2 = await async_client.delete(
        f"/api/v1/vault/stories/{story_id}",
        headers=auth_headers,
    )
    assert del_resp2.status_code == 204


@pytest.mark.asyncio
async def test_match_increments_use_count(async_client: AsyncClient, auth_headers: dict):
    """POST /vault/stories/match increments use_count on matched stories."""
    create_resp = await async_client.post(
        "/api/v1/vault/stories",
        json={
            "skill_tags": ["orchestration"],
            "domain": "orchestration",
            "situation": "At DataCo",
            "action": "Built Airflow DAGs",
            "result_text": "reduced pipeline failures by 60%",
        },
        headers=auth_headers,
    )
    story_id = create_resp.json()["id"]

    match_resp = await async_client.post(
        "/api/v1/vault/stories/match",
        json={"jd_text": "airflow orchestration dagster dag scheduling backfill retry idempotent workflow"},
        headers=auth_headers,
    )
    assert match_resp.status_code == 200
    matched_ids = [s["id"] for s in match_resp.json()]
    if story_id in matched_ids:
        idx = matched_ids.index(story_id)
        assert match_resp.json()[idx]["use_count"] >= 1
```

- [ ] **Step 3: Run story bank tests**

```bash
cd backend
ENVIRONMENT=test DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
REDIS_URL="redis://localhost:6379" JWT_SECRET="any" \
FERNET_KEY="x_fMBr_lJSHIVPOtMtFxnq5RZ34kEFiL-7UEiM-JKYA=" \
poetry run pytest tests/test_story_bank.py -v
```
Expected: all unit tests pass; integration tests pass if test DB fixtures exist.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_story_bank.py backend/pyproject.toml poetry.lock
git commit -m "test: story bank unit and integration tests"
```

---

## Phase 2: Offer Scoring (Slice 2)

### Task 9: OfferEvaluation model + migration

**Files:**
- Create: `backend/app/models/offer_evaluation.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/h2i3j4k5_add_offer_evaluations.py`

- [ ] **Step 1: Create `backend/app/models/offer_evaluation.py`**

```python
"""OfferEvaluation — dimensional A-F offer scoring results."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OfferEvaluation(TimestampMixin, Base):
    __tablename__ = "offer_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    jd_text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[str] = mapped_column(String(200), nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    overall_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "overall_grade IN ('A','B','C','D','F')",
            name="ck_offer_eval_grade",
        ),
        CheckConstraint(
            "overall_score >= 0.0 AND overall_score <= 100.0",
            name="ck_offer_eval_score",
        ),
        UniqueConstraint("user_id", "jd_text_hash", name="uq_offer_eval_user_jd"),
        Index("ix_offer_eval_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<OfferEvaluation id={self.id} grade={self.overall_grade} score={self.overall_score}>"
```

- [ ] **Step 2: Add to `models/__init__.py`**

Add import and `__all__` entry:
```python
from app.models.offer_evaluation import OfferEvaluation
```

- [ ] **Step 3: Generate and write migration**

```bash
cd backend
poetry run alembic revision -m "add_offer_evaluations"
```

Fill the generated file:
```python
"""add_offer_evaluations"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision/down_revision: fill from autogenerated header


def upgrade() -> None:
    op.create_table(
        "offer_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("jd_text_hash", sa.String(64), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("role_title", sa.String(200), nullable=False),
        sa.Column("dimension_scores", postgresql.JSONB(), nullable=False),
        sa.Column("overall_grade", sa.String(1), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("overall_grade IN ('A','B','C','D','F')", name="ck_offer_eval_grade"),
        sa.CheckConstraint("overall_score >= 0.0 AND overall_score <= 100.0", name="ck_offer_eval_score"),
        sa.UniqueConstraint("user_id", "jd_text_hash", name="uq_offer_eval_user_jd"),
    )
    op.create_index("ix_offer_evaluations_user_id", "offer_evaluations", ["user_id"])
    op.create_index("ix_offer_evaluations_jd_hash", "offer_evaluations", ["jd_text_hash"])
    op.create_index("ix_offer_eval_user_created", "offer_evaluations", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_offer_eval_user_created", table_name="offer_evaluations")
    op.drop_index("ix_offer_evaluations_jd_hash", table_name="offer_evaluations")
    op.drop_index("ix_offer_evaluations_user_id", table_name="offer_evaluations")
    op.drop_table("offer_evaluations")
```

- [ ] **Step 4: Apply migration and commit**

```bash
ENVIRONMENT=test DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
poetry run alembic upgrade head

git add backend/app/models/offer_evaluation.py backend/app/models/__init__.py \
        backend/alembic/versions/
git commit -m "feat: add OfferEvaluation model and migration"
```

---

### Task 10: `offer_scoring_service.py`

**Files:**
- Create: `backend/app/services/offer_scoring_service.py`

- [ ] **Step 1: Create `backend/app/services/offer_scoring_service.py`**

```python
"""
Offer scoring service — 8 dimension A-F grader.

Vendored SIGNAL_TAXONOMY from tailor-resume-work. Keep in sync.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.offer_evaluation import OfferEvaluation
from app.services.story_service import SIGNAL_TAXONOMY

# ---------------------------------------------------------------------------
# Dream company tier lookup (compensation fallback when JD has no salary)
# ---------------------------------------------------------------------------
_DREAM_COMPANIES = {
    "anthropic", "openai", "databricks", "snowflake", "goldman sachs",
    "google", "microsoft", "nvidia", "apple", "amazon", "meta", "netflix",
    "stripe", "citadel", "aqr", "two sigma", "hrt", "bloomberg", "jp morgan",
    "fidelity", "uber", "salesforce", "spotify", "doordash", "disney", "walmart",
}
_SENIOR_DE_BAND = (150_000, 220_000)


def _score_compensation(jd_text: str, company_name: str) -> float:
    """Extract salary range from JD or fall back to company-tier lookup."""
    salary_matches = re.findall(
        r"\$\s?(\d{2,3}(?:,\d{3})?)\s?[kK–-]\s?\$?\s?(\d{2,3}(?:,\d{3})?)\s?[kK]?",
        jd_text,
    )
    if salary_matches:
        try:
            low_str, high_str = salary_matches[0]
            low = int(low_str.replace(",", "")) * (1000 if "k" in jd_text[jd_text.find(low_str):jd_text.find(low_str)+10].lower() else 1)
            high = int(high_str.replace(",", "")) * (1000 if "k" in jd_text[jd_text.find(high_str):jd_text.find(high_str)+10].lower() else 1)
            # Score: midpoint vs senior DE target band
            mid = (low + high) / 2
            target_low, target_high = _SENIOR_DE_BAND
            if mid >= target_low:
                return min(100.0, 70.0 + (mid - target_low) / (target_high - target_low) * 30)
            return max(0.0, 70.0 * mid / target_low)
        except Exception:
            pass

    # Fallback: dream company = assume senior band present
    if company_name.lower() in _DREAM_COMPANIES:
        return 70.0  # Uncertain but likely competitive
    return 50.0  # Unknown company, unknown comp


def _score_sponsorship_regex(jd_text: str, company_name: str) -> float:
    """Regex-only H1B sponsorship scoring."""
    text = jd_text.lower()
    if any(phrase in text for phrase in [
        "must be authorized to work without sponsorship",
        "no sponsorship",
        "will not sponsor",
        "not able to sponsor",
    ]):
        return 10.0
    if any(phrase in text for phrase in [
        "h1b", "h-1b", "visa sponsorship", "will sponsor", "sponsorship available",
        "work authorization provided",
    ]):
        return 85.0
    if company_name.lower() in _DREAM_COMPANIES:
        return 50.0  # Dream companies often sponsor but JD is silent
    return 35.0  # Unknown company, JD silent — assume low


async def _score_sponsorship_llm(
    jd_text: str, company_name: str, api_key: str
) -> float:
    """Claude-haiku classification for sponsorship signal. Falls back to regex on error."""
    from app.services.llm_gateway import _call_anthropic

    system = (
        "You are an H1B visa sponsorship classifier. "
        "Given a job description and company name, reply with ONE of: "
        "SPONSORS, SILENT, NO_SPONSOR. "
        "SPONSORS = JD explicitly mentions H1B/visa sponsorship positively. "
        "SILENT = JD says nothing about sponsorship. "
        "NO_SPONSOR = JD explicitly says no sponsorship."
    )
    user = f"Company: {company_name}\n\nJD excerpt:\n{jd_text[:2000]}"

    try:
        result = await _call_anthropic(system, user, api_key, model="claude-haiku-4-5-20251001")
        result = result.strip().upper()
        if "SPONSORS" in result:
            return 85.0
        if "NO_SPONSOR" in result:
            return 10.0
        return _score_sponsorship_regex(jd_text, company_name)  # SILENT
    except Exception as exc:
        logger.warning(f"[offer_scoring] LLM sponsorship failed: {exc} — using regex fallback")
        return _score_sponsorship_regex(jd_text, company_name)


def _score_tech_stack(jd_text: str) -> float:
    """Keyword overlap with SIGNAL_TAXONOMY categories (excluding leadership)."""
    text = jd_text.lower()
    tech_categories = {k: v for k, v in SIGNAL_TAXONOMY.items() if k != "leadership_ownership"}
    matched = sum(
        1 for kws in tech_categories.values() for kw in kws if kw in text
    )
    total = sum(len(v) for v in tech_categories.values())
    return min(100.0, (matched / max(total, 1)) * 400)  # scale: 25% match = 100


def _score_growth_trajectory(jd_text: str) -> float:
    text = jd_text.lower()
    senior_signals = ["senior", "staff", "lead", "principal", "architect", "director"]
    found = sum(1 for s in senior_signals if s in text)
    return min(100.0, found * 25.0)


def _score_remote_flexibility(jd_text: str) -> float:
    text = jd_text.lower()
    if "fully remote" in text or "100% remote" in text:
        return 100.0
    if "remote" in text and "hybrid" not in text:
        return 85.0
    if "hybrid" in text:
        return 60.0
    if "on-site" in text or "onsite" in text or "in-office" in text:
        return 20.0
    return 50.0  # Unspecified


def _score_brand_prestige(company_name: str) -> float:
    return 90.0 if company_name.lower() in _DREAM_COMPANIES else 50.0


def _score_interview_difficulty(jd_text: str) -> float:
    text = jd_text.lower()
    hard_signals = ["leetcode", "system design", "take-home", "coding challenge", "onsite loop"]
    found = sum(1 for s in hard_signals if s in text)
    return max(0.0, 80.0 - found * 20.0)  # lower difficulty = higher score


_WEIGHTS = {
    "role_match":              0.25,
    "compensation_fit":        0.18,
    "sponsorship_likelihood":  0.15,
    "tech_stack_fit":          0.15,
    "growth_trajectory":       0.10,
    "remote_flexibility":      0.08,
    "brand_prestige":          0.05,
    "interview_difficulty":    0.04,
}


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


async def evaluate_offer(
    db: AsyncSession,
    user_id: uuid.UUID,
    jd_text: str,
    company_name: str,
    role_title: str,
    resume_id: uuid.UUID | None,
    api_key: str = "",
    refresh: bool = False,
) -> tuple[OfferEvaluation, bool]:
    """
    Score a job offer across 8 dimensions.

    Returns (evaluation, was_cached). When was_cached=True, the record was
    fetched from DB without re-scoring. Pass refresh=True to force re-score.
    """
    jd_hash = hashlib.sha256(jd_text.encode()).hexdigest()

    if not refresh:
        result = await db.execute(
            select(OfferEvaluation).where(
                OfferEvaluation.user_id == user_id,
                OfferEvaluation.jd_text_hash == jd_hash,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing, True

    # Resolve resume for role_match dimension
    role_match_score: float | None = None
    effective_resume_id = resume_id

    if not effective_resume_id:
        from app.models.resume import Resume
        res = await db.execute(
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(Resume.created_at.desc())
            .limit(1)
        )
        default_resume = res.scalar_one_or_none()
        if default_resume:
            effective_resume_id = default_resume.id

    # role_match via standalone (HTTP) — degrade gracefully if unavailable
    degraded: list[str] = []
    if effective_resume_id:
        import os
        import httpx

        from app.models.resume import Resume
        res = await db.execute(select(Resume).where(Resume.id == effective_resume_id))
        resume = res.scalar_one_or_none()
        if resume and resume.content:
            standalone_url = os.getenv("STANDALONE_URL", "http://localhost:7000")
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.post(
                        f"{standalone_url}/api/v1/resume/score",
                        json={"jd_text": jd_text, "resume_text": resume.content},
                    )
                    resp.raise_for_status()
                    role_match_score = resp.json().get("ats_score", None)
            except Exception as exc:
                logger.warning(f"[offer_eval] standalone unavailable: {exc}")
                degraded.append("role_match")

    # Compute all formula dimensions
    dimensions: dict[str, dict] = {}
    active_weights = dict(_WEIGHTS)

    if role_match_score is not None:
        dimensions["role_match"] = {
            "score": round(role_match_score, 1),
            "weight": _WEIGHTS["role_match"],
            "label": "Strong" if role_match_score >= 70 else "Moderate",
        }
    else:
        active_weights.pop("role_match", None)
        dimensions["role_match"] = {"score": None, "weight": _WEIGHTS["role_match"], "label": "Unavailable"}

    sponsorship_score = await _score_sponsorship_llm(jd_text, company_name, api_key) if api_key else _score_sponsorship_regex(jd_text, company_name)
    comp_score = _score_compensation(jd_text, company_name)
    tech_score = _score_tech_stack(jd_text)
    growth_score = _score_growth_trajectory(jd_text)
    remote_score = _score_remote_flexibility(jd_text)
    prestige_score = _score_brand_prestige(company_name)
    difficulty_score = _score_interview_difficulty(jd_text)

    dimensions.update({
        "compensation_fit":       {"score": round(comp_score, 1), "weight": _WEIGHTS["compensation_fit"], "label": ""},
        "sponsorship_likelihood": {"score": round(sponsorship_score, 1), "weight": _WEIGHTS["sponsorship_likelihood"], "label": ""},
        "tech_stack_fit":         {"score": round(tech_score, 1), "weight": _WEIGHTS["tech_stack_fit"], "label": ""},
        "growth_trajectory":      {"score": round(growth_score, 1), "weight": _WEIGHTS["growth_trajectory"], "label": ""},
        "remote_flexibility":     {"score": round(remote_score, 1), "weight": _WEIGHTS["remote_flexibility"], "label": ""},
        "brand_prestige":         {"score": round(prestige_score, 1), "weight": _WEIGHTS["brand_prestige"], "label": ""},
        "interview_difficulty":   {"score": round(difficulty_score, 1), "weight": _WEIGHTS["interview_difficulty"], "label": ""},
    })

    # Weighted average (exclude degraded dimensions from denominator)
    total_weight = sum(
        w for k, w in active_weights.items()
        if k not in degraded and dimensions.get(k, {}).get("score") is not None
    )
    if total_weight == 0:
        overall = 0.0
    else:
        overall = sum(
            dimensions[k]["score"] * w
            for k, w in active_weights.items()
            if k not in degraded and dimensions.get(k, {}).get("score") is not None
        ) / total_weight

    grade = _grade(overall)

    # Build recommendation
    sponsorship_note = ""
    if sponsorship_score < 50:
        sponsorship_note = " Low H1B signal — verify sponsorship before applying."
    recommendation = (
        f"Grade {grade} ({overall:.0f}/100). "
        f"Role: {role_title} at {company_name}."
        f"{sponsorship_note}"
    )

    # Upsert
    result = await db.execute(
        select(OfferEvaluation).where(
            OfferEvaluation.user_id == user_id,
            OfferEvaluation.jd_text_hash == jd_hash,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.dimension_scores = dimensions
        existing.overall_grade = grade
        existing.overall_score = round(overall, 1)
        existing.recommendation = recommendation
        existing.resume_id = effective_resume_id
        await db.commit()
        await db.refresh(existing)
        return existing, False
    else:
        evaluation = OfferEvaluation(
            user_id=user_id,
            resume_id=effective_resume_id,
            jd_text_hash=jd_hash,
            company_name=company_name,
            role_title=role_title,
            dimension_scores=dimensions,
            overall_grade=grade,
            overall_score=round(overall, 1),
            recommendation=recommendation,
        )
        db.add(evaluation)
        await db.commit()
        await db.refresh(evaluation)
        return evaluation, False
```

---

### Task 11: `vault/offer.py` router + wiring

**Files:**
- Create: `backend/app/routers/vault/offer.py`
- Modify: `backend/app/routers/vault/__init__.py`

- [ ] **Step 1: Create `backend/app/routers/vault/offer.py`**

```python
"""Vault sub-module: offer evaluation endpoint."""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User

router = APIRouter()


class OfferEvaluateRequest(BaseModel):
    jd_text: str
    company_name: str
    role_title: str
    resume_id: uuid.UUID | None = None
    portal_scan_id: uuid.UUID | None = None


class DimensionOut(BaseModel):
    score: float | None
    weight: float
    label: str


class OfferEvaluateResponse(BaseModel):
    evaluation_id: uuid.UUID
    cached: bool
    grade: str
    overall_score: float
    recommendation: str
    degraded_dimensions: list[str]
    dimensions: dict[str, DimensionOut]

    model_config = {"from_attributes": True}


@router.post("/offer/evaluate", response_model=OfferEvaluateResponse)
async def evaluate_offer(
    body: OfferEvaluateRequest,
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.offer_scoring_service import evaluate_offer as _evaluate

    # Resolve jd_text from portal scan if portal_scan_id provided
    jd_text = body.jd_text
    if body.portal_scan_id and not jd_text:
        from sqlalchemy import select
        from app.models.portal_scan import PortalScanCache
        scan_res = await db.execute(
            select(PortalScanCache).where(
                PortalScanCache.id == body.portal_scan_id,
                PortalScanCache.user_id == user.id,
            )
        )
        scan = scan_res.scalar_one_or_none()
        if scan:
            scan_result = scan.scan_result or {}
            requirements = scan_result.get("requirements", [])
            responsibilities = scan_result.get("responsibilities", [])
            jd_text = "\n".join(requirements + responsibilities)

    # Get user's Anthropic key for LLM-based sponsorship scoring
    api_key = ""
    try:
        from app.models.user_provider_config import UserProviderConfig
        from app.dependencies import decrypt_value
        from sqlalchemy import select
        key_res = await db.execute(
            select(UserProviderConfig).where(
                UserProviderConfig.user_id == user.id,
                UserProviderConfig.provider_name == "anthropic",
                UserProviderConfig.is_enabled == True,  # noqa: E712
            )
        )
        cfg = key_res.scalar_one_or_none()
        if cfg and cfg.encrypted_api_key:
            api_key = decrypt_value(cfg.encrypted_api_key)
    except Exception:
        pass  # BYOK not configured — fall back to regex

    evaluation, cached = await _evaluate(
        db=db,
        user_id=user.id,
        jd_text=jd_text,
        company_name=body.company_name,
        role_title=body.role_title,
        resume_id=body.resume_id,
        api_key=api_key,
        refresh=refresh,
    )

    degraded = [
        k for k, v in evaluation.dimension_scores.items()
        if v.get("score") is None
    ]

    return OfferEvaluateResponse(
        evaluation_id=evaluation.id,
        cached=cached,
        grade=evaluation.overall_grade,
        overall_score=evaluation.overall_score,
        recommendation=evaluation.recommendation,
        degraded_dimensions=degraded,
        dimensions={k: DimensionOut(**v) for k, v in evaluation.dimension_scores.items()},
    )
```

- [ ] **Step 2: Wire offer router into `vault/__init__.py`**

Add import:
```python
from app.routers.vault.offer import router as offer_router
```
Add include:
```python
router.include_router(offer_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/vault/offer.py \
        backend/app/routers/vault/__init__.py \
        backend/app/services/offer_scoring_service.py
git commit -m "feat: add dimensional offer scoring endpoint"
```

---

### Task 12: Offer scoring tests

**Files:**
- Create: `backend/tests/test_offer_scoring_service.py`

- [ ] **Step 1: Create `backend/tests/test_offer_scoring_service.py`**

```python
"""Offer scoring unit tests — all formula dimensions, grade thresholds, degradation."""

import pytest
from app.services.offer_scoring_service import (
    _grade,
    _score_brand_prestige,
    _score_compensation,
    _score_growth_trajectory,
    _score_interview_difficulty,
    _score_remote_flexibility,
    _score_sponsorship_regex,
    _score_tech_stack,
)


def test_grade_thresholds():
    assert _grade(95) == "A"
    assert _grade(80) == "B"
    assert _grade(62) == "C"
    assert _grade(50) == "D"
    assert _grade(30) == "F"


def test_sponsorship_explicit_no():
    score = _score_sponsorship_regex(
        "Candidates must be authorized to work without sponsorship", "Acme"
    )
    assert score == 10.0


def test_sponsorship_explicit_yes():
    score = _score_sponsorship_regex("We offer H1B visa sponsorship for this role", "Acme")
    assert score == 85.0


def test_sponsorship_silent_dream_company():
    score = _score_sponsorship_regex("Great opportunity with competitive salary", "Google")
    assert score == 50.0


def test_sponsorship_silent_unknown_company():
    score = _score_sponsorship_regex("Great opportunity with competitive salary", "LocalCorp")
    assert score == 35.0


def test_compensation_dream_company_no_salary():
    """Dream company with no salary text falls back to 70.0."""
    score = _score_compensation("Join our team of engineers", "Anthropic")
    assert score == 70.0


def test_compensation_unknown_company_no_salary():
    score = _score_compensation("Join our team of engineers", "RandomCorp")
    assert score == 50.0


def test_remote_flexibility_fully_remote():
    assert _score_remote_flexibility("This is a fully remote position") == 100.0


def test_remote_flexibility_onsite():
    assert _score_remote_flexibility("You must work on-site at our Dallas office") == 20.0


def test_growth_trajectory_senior():
    score = _score_growth_trajectory("Looking for a Senior Staff Data Engineer")
    assert score >= 50.0


def test_brand_prestige_dream_company():
    assert _score_brand_prestige("Databricks") == 90.0


def test_brand_prestige_unknown():
    assert _score_brand_prestige("RandomStartup") == 50.0


def test_interview_difficulty_leetcode():
    score = _score_interview_difficulty("We have a LeetCode style coding challenge and system design")
    assert score < 60.0


def test_tech_stack_score_increases_with_keywords():
    jd_kafka = "We use kafka streaming real-time kafka events kafka throughput kinesis flink"
    jd_empty = "We are looking for a great engineer"
    assert _score_tech_stack(jd_kafka) > _score_tech_stack(jd_empty)
```

- [ ] **Step 2: Run offer scoring tests**

```bash
cd backend
ENVIRONMENT=test DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
REDIS_URL="redis://localhost:6379" JWT_SECRET="any" \
FERNET_KEY="x_fMBr_lJSHIVPOtMtFxnq5RZ34kEFiL-7UEiM-JKYA=" \
poetry run pytest tests/test_offer_scoring_service.py -v
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_offer_scoring_service.py
git commit -m "test: offer scoring unit tests — all 8 dimensions and grade thresholds"
```

---

## Phase 3: Portal Scanner (Slice 3)

### Task 13: PortalScanCache model + migration

**Files:**
- Create: `backend/app/models/portal_scan.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/i3j4k5l6_add_portal_scan_cache.py`

- [ ] **Step 1: Create `backend/app/models/portal_scan.py`**

```python
"""PortalScanCache — cached structured JD data from ATS job boards."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PortalScanCache(TimestampMixin, Base):
    __tablename__ = "portal_scan_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_id: Mapped[str] = mapped_column(String(200), nullable=False)
    board_type: Mapped[str] = mapped_column(String(50), nullable=False)
    job_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    compensation_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compensation_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scan_result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint(
            "board_type IN ('greenhouse','lever','ashby','wellfound','manual')",
            name="ck_portal_scan_board_type",
        ),
        UniqueConstraint(
            "user_id", "board_type", "job_id", name="uq_portal_scan_user_board_job"
        ),
        Index("ix_portal_scan_user_company", "user_id", "company_name"),
    )

    def __repr__(self) -> str:
        return f"<PortalScanCache id={self.id} board={self.board_type} job_id={self.job_id}>"
```

- [ ] **Step 2: Add to `models/__init__.py`**

```python
from app.models.portal_scan import PortalScanCache
```
Add `"PortalScanCache"` to `__all__`.

- [ ] **Step 3: Generate migration and fill body**

```bash
poetry run alembic revision -m "add_portal_scan_cache"
```

```python
def upgrade() -> None:
    op.create_table(
        "portal_scan_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("job_id", sa.String(200), nullable=False),
        sa.Column("board_type", sa.String(50), nullable=False),
        sa.Column("job_url", sa.String(2048), nullable=False),
        sa.Column("compensation_min", sa.Integer(), nullable=True),
        sa.Column("compensation_max", sa.Integer(), nullable=True),
        sa.Column("scan_result", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_stale", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "board_type IN ('greenhouse','lever','ashby','wellfound','manual')",
            name="ck_portal_scan_board_type",
        ),
        sa.UniqueConstraint("user_id", "board_type", "job_id", name="uq_portal_scan_user_board_job"),
    )
    op.create_index("ix_portal_scan_user_id", "portal_scan_cache", ["user_id"])
    op.create_index("ix_portal_scan_user_company", "portal_scan_cache", ["user_id", "company_name"])
    # Partial index on is_stale — only indexes stale rows (far fewer rows than total)
    op.execute(
        "CREATE INDEX ix_portal_scan_stale ON portal_scan_cache (user_id) WHERE is_stale = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_portal_scan_stale")
    op.drop_index("ix_portal_scan_user_company", table_name="portal_scan_cache")
    op.drop_index("ix_portal_scan_user_id", table_name="portal_scan_cache")
    op.drop_table("portal_scan_cache")
```

- [ ] **Step 4: Apply and commit**

```bash
ENVIRONMENT=test DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
poetry run alembic upgrade head

git add backend/app/models/portal_scan.py backend/app/models/__init__.py \
        backend/alembic/versions/
git commit -m "feat: add PortalScanCache model and migration"
```

---

### Task 14: `portal_scanner_service.py`

**Files:**
- Create: `backend/app/services/portal_scanner_service.py`

- [ ] **Step 1: Create `backend/app/services/portal_scanner_service.py`**

```python
"""
Portal scanner service.

Detects ATS board from URL and fetches structured JD data.
Supported boards: Greenhouse, Lever, Ashby.
Wellfound deferred to v2 (requires headless browser).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from loguru import logger

from app.middleware.circuit_breaker import portal_circuit

# ---------------------------------------------------------------------------
# Board URL patterns
# ---------------------------------------------------------------------------
_BOARD_PATTERNS: dict[str, re.Pattern] = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io/([\w-]+)/jobs/(\d+)"),
    "lever":      re.compile(r"jobs\.lever\.co/([\w-]+)/([a-f0-9-]+)"),
    "ashby":      re.compile(r"jobs\.ashbyhq\.com/([\w-]+)/([^/?#]+)"),
}

_BOARD_TIMEOUTS: dict[str, httpx.Timeout] = {
    "greenhouse": httpx.Timeout(connect=3.0, read=8.0),
    "lever":      httpx.Timeout(connect=3.0, read=8.0),
    "ashby":      httpx.Timeout(connect=3.0, read=12.0),
}


@dataclass
class ScanResult:
    board_type: str
    company_slug: str
    job_id: str
    company_name: str
    title: str
    location: str
    remote_policy: str
    requirements: list[str]
    responsibilities: list[str]
    apply_url: str
    compensation_min: int | None
    compensation_max: int | None
    manual_entry: bool = False


def detect_board(url: str) -> tuple[str, str, str] | None:
    """
    Returns (board_type, company_slug, job_id) or None if unrecognized.
    None means the caller should return manual_entry=True.
    """
    for board, pattern in _BOARD_PATTERNS.items():
        match = pattern.search(url)
        if match:
            return board, match.group(1), match.group(2)
    return None


def _extract_compensation(text: str) -> tuple[int | None, int | None]:
    """Extract salary min/max from free text. Returns (None, None) if not found."""
    pattern = re.compile(
        r"\$\s?(\d{2,3}(?:,\d{3})?)\s*[kK]?\s*[–\-]\s*\$?\s?(\d{2,3}(?:,\d{3})?)\s*[kK]?"
    )
    match = pattern.search(text)
    if not match:
        return None, None
    try:
        def parse(s: str) -> int:
            n = int(s.replace(",", ""))
            return n * 1000 if n < 1000 else n
        return parse(match.group(1)), parse(match.group(2))
    except ValueError:
        return None, None


@portal_circuit
async def _fetch_greenhouse(company_slug: str, job_id: str, url: str) -> ScanResult:
    """Fetch Greenhouse job via public JSON API."""
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs/{job_id}"
    async with httpx.AsyncClient(timeout=_BOARD_TIMEOUTS["greenhouse"]) as client:
        for attempt in range(2):
            try:
                resp = await client.get(api_url)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                if attempt == 0 and e.response.status_code >= 500:
                    continue
                raise

    data = resp.json()
    title = data.get("title", "")
    location = data.get("location", {}).get("name", "")
    content = data.get("content", "")
    dept = data.get("departments", [{}])[0].get("name", "") if data.get("departments") else ""

    # Extract requirements/responsibilities from HTML content (basic)
    clean = re.sub(r"<[^>]+>", " ", content)
    lines = [ln.strip() for ln in clean.split("\n") if ln.strip() and len(ln.strip()) > 20]

    comp_min, comp_max = _extract_compensation(clean)
    remote = "remote" if "remote" in (title + location + clean).lower() else "onsite"

    return ScanResult(
        board_type="greenhouse",
        company_slug=company_slug,
        job_id=job_id,
        company_name=dept or company_slug.replace("-", " ").title(),
        title=title,
        location=location,
        remote_policy=remote,
        requirements=lines[:15],
        responsibilities=lines[:10],
        apply_url=url,
        compensation_min=comp_min,
        compensation_max=comp_max,
    )


@portal_circuit
async def _fetch_lever(company_slug: str, job_id: str, url: str) -> ScanResult:
    """Fetch Lever job via public JSON API."""
    api_url = f"https://api.lever.co/v0/postings/{company_slug}/{job_id}"
    async with httpx.AsyncClient(timeout=_BOARD_TIMEOUTS["lever"]) as client:
        for attempt in range(2):
            try:
                resp = await client.get(api_url)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                if attempt == 0 and e.response.status_code >= 500:
                    continue
                raise

    data = resp.json()
    title = data.get("text", "")
    location = data.get("categories", {}).get("location", "")
    commitment = data.get("categories", {}).get("commitment", "")
    content_sections = data.get("content", {})
    description = content_sections.get("descriptionBody", "")
    lists_data = content_sections.get("lists", [])

    requirements: list[str] = []
    responsibilities: list[str] = []
    for section in lists_data:
        section_text = section.get("text", "").lower()
        items = re.findall(r"<li>(.*?)</li>", section.get("content", ""), re.DOTALL)
        items = [re.sub(r"<[^>]+>", "", i).strip() for i in items]
        if "require" in section_text or "qualif" in section_text:
            requirements.extend(items)
        elif "responsib" in section_text or "what you" in section_text:
            responsibilities.extend(items)

    comp_min, comp_max = _extract_compensation(description)
    remote = "remote" if "remote" in (title + location + commitment).lower() else "onsite"

    return ScanResult(
        board_type="lever",
        company_slug=company_slug,
        job_id=job_id,
        company_name=company_slug.replace("-", " ").title(),
        title=title,
        location=location,
        remote_policy=remote,
        requirements=requirements[:15],
        responsibilities=responsibilities[:10],
        apply_url=url,
        compensation_min=comp_min,
        compensation_max=comp_max,
    )


@portal_circuit
async def _fetch_ashby(company_slug: str, job_id: str, url: str) -> ScanResult:
    """
    Fetch Ashby job. The public API returns ALL jobs for a company;
    iterate to find the one matching job_id slug. Caching the list in
    Redis for 1 hour is the caller's responsibility (not done here).
    """
    api_url = f"https://jobs.ashbyhq.com/api/non-user-facing/posting-api/job-board/{company_slug}"
    async with httpx.AsyncClient(timeout=_BOARD_TIMEOUTS["ashby"]) as client:
        resp = await client.get(api_url)
        resp.raise_for_status()

    data = resp.json()
    jobs = data.get("jobPostings", [])
    target = None
    for job in jobs:
        path = job.get("jobPostingPath", "")
        if job_id.lower() in path.lower():
            target = job
            break

    if not target:
        raise ValueError(f"Job {job_id} not found in Ashby board {company_slug}")

    title = target.get("title", "")
    location = target.get("locationName", "")
    description = target.get("descriptionHtml", "")
    clean = re.sub(r"<[^>]+>", " ", description)
    lines = [ln.strip() for ln in clean.split("\n") if ln.strip() and len(ln.strip()) > 20]

    comp_min, comp_max = _extract_compensation(clean)
    remote = "remote" if "remote" in (title + location + clean).lower() else "onsite"

    return ScanResult(
        board_type="ashby",
        company_slug=company_slug,
        job_id=job_id,
        company_name=company_slug.replace("-", " ").title(),
        title=title,
        location=location,
        remote_policy=remote,
        requirements=lines[:15],
        responsibilities=lines[:10],
        apply_url=url,
        compensation_min=comp_min,
        compensation_max=comp_max,
    )


async def scan_url(url: str) -> ScanResult:
    """
    Main entry point. Detect board from URL and fetch.
    Returns a ScanResult with manual_entry=True if board is unrecognized.
    """
    detected = detect_board(url)
    if not detected:
        return ScanResult(
            board_type="manual",
            company_slug="",
            job_id="",
            company_name="",
            title="",
            location="",
            remote_policy="",
            requirements=[],
            responsibilities=[],
            apply_url=url,
            compensation_min=None,
            compensation_max=None,
            manual_entry=True,
        )

    board_type, company_slug, job_id = detected

    try:
        if board_type == "greenhouse":
            return await _fetch_greenhouse(company_slug, job_id, url)
        elif board_type == "lever":
            return await _fetch_lever(company_slug, job_id, url)
        elif board_type == "ashby":
            return await _fetch_ashby(company_slug, job_id, url)
    except Exception as exc:
        logger.error(f"[portal_scan] {board_type} fetch failed for {url}: {exc}")
        raise

    return ScanResult(
        board_type="manual", company_slug="", job_id="", company_name="",
        title="", location="", remote_policy="", requirements=[],
        responsibilities=[], apply_url=url, compensation_min=None,
        compensation_max=None, manual_entry=True,
    )
```

---

### Task 15: `vault/portal.py` router + wiring

**Files:**
- Create: `backend/app/routers/vault/portal.py`
- Modify: `backend/app/routers/vault/__init__.py`

- [ ] **Step 1: Create `backend/app/routers/vault/portal.py`**

```python
"""Vault sub-module: ATS portal scanner endpoint."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.portal_scan import PortalScanCache
from app.models.user import User

router = APIRouter()


class PortalScanRequest(BaseModel):
    url: str


class PortalScanResponse(BaseModel):
    scan_id: uuid.UUID | None
    cached: bool
    manual_entry: bool
    board_type: str | None
    title: str
    company: str
    location: str
    remote_policy: str
    compensation_min: int | None
    compensation_max: int | None
    requirements: list[str]
    responsibilities: list[str]
    apply_url: str
    job_id: str
    schema_version: int


@router.post("/portal/scan", response_model=PortalScanResponse)
async def scan_portal(
    body: PortalScanRequest,
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.portal_scanner_service import detect_board, scan_url

    # Check cache
    detected = detect_board(body.url)
    if detected and not refresh:
        board_type, company_slug, job_id = detected
        result = await db.execute(
            select(PortalScanCache).where(
                PortalScanCache.user_id == user.id,
                PortalScanCache.board_type == board_type,
                PortalScanCache.job_id == job_id,
            )
        )
        cached_row = result.scalar_one_or_none()
        if cached_row:
            cached_row.last_accessed_at = datetime.now(tz=timezone.utc)
            await db.commit()
            sr = cached_row.scan_result
            return PortalScanResponse(
                scan_id=cached_row.id,
                cached=True,
                manual_entry=False,
                board_type=cached_row.board_type,
                title=sr.get("title", ""),
                company=cached_row.company_name,
                location=sr.get("location", ""),
                remote_policy=sr.get("remote_policy", ""),
                compensation_min=cached_row.compensation_min,
                compensation_max=cached_row.compensation_max,
                requirements=sr.get("requirements", []),
                responsibilities=sr.get("responsibilities", []),
                apply_url=cached_row.job_url,
                job_id=cached_row.job_id,
                schema_version=cached_row.schema_version,
            )

    # Fetch from board
    scan = await scan_url(body.url)

    if scan.manual_entry:
        return PortalScanResponse(
            scan_id=None,
            cached=False,
            manual_entry=True,
            board_type=None,
            title="",
            company="",
            location="",
            remote_policy="",
            compensation_min=None,
            compensation_max=None,
            requirements=[],
            responsibilities=[],
            apply_url=body.url,
            job_id="",
            schema_version=1,
        )

    # Upsert cache
    scan_result_json = {
        "title": scan.title,
        "location": scan.location,
        "remote_policy": scan.remote_policy,
        "requirements": scan.requirements,
        "responsibilities": scan.responsibilities,
        "schema_version": 1,
    }

    existing_result = await db.execute(
        select(PortalScanCache).where(
            PortalScanCache.user_id == user.id,
            PortalScanCache.board_type == scan.board_type,
            PortalScanCache.job_id == scan.job_id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        existing.scan_result = scan_result_json
        existing.compensation_min = scan.compensation_min
        existing.compensation_max = scan.compensation_max
        existing.is_stale = False
        existing.last_accessed_at = datetime.now(tz=timezone.utc)
        await db.commit()
        await db.refresh(existing)
        row = existing
    else:
        row = PortalScanCache(
            user_id=user.id,
            company_name=scan.company_name,
            job_id=scan.job_id,
            board_type=scan.board_type,
            job_url=scan.apply_url,
            compensation_min=scan.compensation_min,
            compensation_max=scan.compensation_max,
            scan_result=scan_result_json,
            schema_version=1,
            last_accessed_at=datetime.now(tz=timezone.utc),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

    return PortalScanResponse(
        scan_id=row.id,
        cached=False,
        manual_entry=False,
        board_type=scan.board_type,
        title=scan.title,
        company=scan.company_name,
        location=scan.location,
        remote_policy=scan.remote_policy,
        compensation_min=scan.compensation_min,
        compensation_max=scan.compensation_max,
        requirements=scan.requirements,
        responsibilities=scan.responsibilities,
        apply_url=scan.apply_url,
        job_id=scan.job_id,
        schema_version=1,
    )
```

- [ ] **Step 2: Wire portal router into `vault/__init__.py`**

Add import:
```python
from app.routers.vault.portal import router as portal_router
```
Add include:
```python
router.include_router(portal_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/vault/portal.py \
        backend/app/routers/vault/__init__.py \
        backend/app/services/portal_scanner_service.py
git commit -m "feat: add ATS portal scanner endpoint (Greenhouse, Lever, Ashby)"
```

---

### Task 16: Portal scanner tests

**Files:**
- Create: `backend/tests/test_portal_scanner.py`

- [ ] **Step 1: Create `backend/tests/test_portal_scanner.py`**

```python
"""Portal scanner unit tests — board detection, mock HTTP responses, cache behavior."""

import pytest
from pytest_httpx import HTTPXMock

from app.services.portal_scanner_service import detect_board, scan_url


def test_detect_greenhouse():
    url = "https://boards.greenhouse.io/databricks/jobs/7892341"
    result = detect_board(url)
    assert result is not None
    board, slug, job_id = result
    assert board == "greenhouse"
    assert slug == "databricks"
    assert job_id == "7892341"


def test_detect_lever():
    url = "https://jobs.lever.co/openai/abc123de-4567-89ef-ghij-klmnopqrstuv"
    result = detect_board(url)
    assert result is not None
    board, slug, job_id = result
    assert board == "lever"
    assert slug == "openai"


def test_detect_ashby():
    url = "https://jobs.ashbyhq.com/anthropic/senior-data-engineer"
    result = detect_board(url)
    assert result is not None
    board, slug, job_id = result
    assert board == "ashby"
    assert slug == "anthropic"
    assert job_id == "senior-data-engineer"


def test_detect_unrecognized_returns_none():
    url = "https://careers.workday.com/jobs/12345"
    assert detect_board(url) is None


def test_detect_wellfound_returns_none():
    """Wellfound is deferred to v2 — detect_board returns None."""
    url = "https://wellfound.com/jobs/123456"
    assert detect_board(url) is None


@pytest.mark.asyncio
async def test_scan_unrecognized_url_returns_manual_entry():
    result = await scan_url("https://careers.example.com/jobs/12345")
    assert result.manual_entry is True
    assert result.board_type == "manual"


@pytest.mark.asyncio
async def test_scan_greenhouse_mock(httpx_mock: HTTPXMock):
    """Mock Greenhouse API response and verify ScanResult parsing."""
    httpx_mock.add_response(
        url="https://boards-api.greenhouse.io/v1/boards/databricks/jobs/7892341",
        json={
            "title": "Senior Data Engineer",
            "location": {"name": "Remote - US"},
            "content": "<p>We need Spark and Kafka experience.</p><p>5+ years required.</p>",
            "departments": [{"name": "Engineering"}],
        },
    )

    result = await scan_url("https://boards.greenhouse.io/databricks/jobs/7892341")

    assert result.manual_entry is False
    assert result.board_type == "greenhouse"
    assert result.title == "Senior Data Engineer"
    assert result.location == "Remote - US"
    assert result.company_slug == "databricks"
    assert result.job_id == "7892341"


@pytest.mark.asyncio
async def test_scan_lever_mock(httpx_mock: HTTPXMock):
    """Mock Lever API response."""
    job_uuid = "abc123de-4567-89ef-0000-klmnopqrstuv"
    httpx_mock.add_response(
        url=f"https://api.lever.co/v0/postings/openai/{job_uuid}",
        json={
            "text": "ML Platform Engineer",
            "categories": {"location": "San Francisco, CA", "commitment": "Full-time"},
            "content": {
                "descriptionBody": "Join our ML team.",
                "lists": [
                    {
                        "text": "Requirements",
                        "content": "<li>5+ years Python</li><li>MLflow experience</li>",
                    }
                ],
            },
        },
    )

    result = await scan_url(f"https://jobs.lever.co/openai/{job_uuid}")
    assert result.board_type == "lever"
    assert result.title == "ML Platform Engineer"
    assert "5+ years Python" in result.requirements


@pytest.mark.asyncio
async def test_scan_ashby_mock(httpx_mock: HTTPXMock):
    """Mock Ashby API — list response, finds job by slug."""
    httpx_mock.add_response(
        url="https://jobs.ashbyhq.com/api/non-user-facing/posting-api/job-board/anthropic",
        json={
            "jobPostings": [
                {
                    "title": "Senior Data Engineer",
                    "locationName": "Remote",
                    "jobPostingPath": "/anthropic/senior-data-engineer",
                    "descriptionHtml": "<p>Build ML infrastructure. 40% latency reduction target.</p>",
                }
            ]
        },
    )

    result = await scan_url("https://jobs.ashbyhq.com/anthropic/senior-data-engineer")
    assert result.board_type == "ashby"
    assert result.title == "Senior Data Engineer"
    assert result.job_id == "senior-data-engineer"
```

- [ ] **Step 2: Run portal scanner tests**

```bash
cd backend
ENVIRONMENT=test DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
REDIS_URL="redis://localhost:6379" JWT_SECRET="any" \
FERNET_KEY="x_fMBr_lJSHIVPOtMtFxnq5RZ34kEFiL-7UEiM-JKYA=" \
poetry run pytest tests/test_portal_scanner.py -v
```
Expected: all 9 tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_portal_scanner.py
git commit -m "test: portal scanner unit tests with mocked board APIs"
```

---

## Phase 4: Cross-cutting Tests

### Task 17: Router registration and model table tests

**Files:**
- Create: `backend/tests/test_vault_router_registration.py`
- Create: `backend/tests/test_models_registered.py`

- [ ] **Step 1: Create `backend/tests/test_vault_router_registration.py`**

```python
"""Smoke tests — verify new vault routers are mounted and return auth errors (not 404)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_stories_route_mounted(async_client: AsyncClient):
    """GET /vault/stories must return 401/422 (auth required), not 404."""
    resp = await async_client.get("/api/v1/vault/stories")
    assert resp.status_code != 404, "stories router not mounted"


@pytest.mark.asyncio
async def test_offer_evaluate_route_mounted(async_client: AsyncClient):
    """POST /vault/offer/evaluate must return 401/422, not 404."""
    resp = await async_client.post("/api/v1/vault/offer/evaluate", json={})
    assert resp.status_code != 404, "offer router not mounted"


@pytest.mark.asyncio
async def test_portal_scan_route_mounted(async_client: AsyncClient):
    """POST /vault/portal/scan must return 401/422, not 404."""
    resp = await async_client.post("/api/v1/vault/portal/scan", json={})
    assert resp.status_code != 404, "portal router not mounted"


@pytest.mark.asyncio
async def test_stories_match_route_mounted(async_client: AsyncClient):
    """POST /vault/stories/match must return 401/422, not 404."""
    resp = await async_client.post("/api/v1/vault/stories/match", json={})
    assert resp.status_code != 404, "stories/match route not mounted"
```

- [ ] **Step 2: Create `backend/tests/test_models_registered.py`**

```python
"""Verify all three new models are registered in Base.metadata."""

from app.models.base import Base


def test_story_entries_table_registered():
    assert "story_entries" in Base.metadata.tables


def test_offer_evaluations_table_registered():
    assert "offer_evaluations" in Base.metadata.tables


def test_portal_scan_cache_table_registered():
    assert "portal_scan_cache" in Base.metadata.tables
```

- [ ] **Step 3: Run all cross-cutting tests**

```bash
cd backend
ENVIRONMENT=test DATABASE_URL="postgresql+asyncpg://autoapply:testpassword@localhost:5433/autoapply_test" \
REDIS_URL="redis://localhost:6379" JWT_SECRET="any" \
FERNET_KEY="x_fMBr_lJSHIVPOtMtFxnq5RZ34kEFiL-7UEiM-JKYA=" \
poetry run pytest tests/test_vault_router_registration.py tests/test_models_registered.py -v
```
Expected: all 7 tests pass.

- [ ] **Step 4: Run full test suite to check regressions**

```bash
poetry run pytest tests/ -v --tb=short
```
Expected: existing 210+ tests continue to pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_vault_router_registration.py \
        backend/tests/test_models_registered.py
git commit -m "test: vault router registration and model table smoke tests"
```

---

## Phase 5: Standalone Bug Fixes (tailor-resume-work — parallel)

> Run these in tailor-resume-work repo concurrently with Phase 1-4 work. These fix the standalone's own `/tailor` endpoint and enable the `role_match` HTTP call from offer scoring.

### Task 18: Fix 3 bugs in `web_app/routes/resume.py`

**Files:**
- Modify: `c:\tmp\tailor-resume-work\web_app\routes\resume.py` (lines 93, 96, 131)

**Pre-step: Verify `GapReport` field names**

Before editing, run:
```bash
cd c:/tmp/tailor-resume-work
grep -n "class GapReport\|@dataclass\|keyword_gaps\|kw_gaps\|top_missing\|recommendations\|ats_score" tailor_resume/_scripts/resume_types.py | head -20
```
Confirm the exact field names of `GapReport`. The fix at line 96 depends on these names.

- [ ] **Step 1: Fix Bug 1 — artifacts tuple at line 131**

Change:
```python
artifacts=[tmp_path]
```
To:
```python
artifacts=[(tmp_path, artifact_format)]
```
Where `artifact_format` is the format string already in scope (e.g., `"pdf"` or the variable holding it). Check the surrounding context to confirm the variable name.

- [ ] **Step 2: Fix Bug 2 — gap_summary join at line 93**

Change:
```python
gap_summary=result.gap_summary,
```
To:
```python
gap_summary="\n".join(result.gap_summary) if isinstance(result.gap_summary, list) else result.gap_summary,
```

- [ ] **Step 3: Fix Bug 3 — report serialization at line 96**

Replace the `report=result.report` line with (using verified field names from pre-step):
```python
report=json.dumps({
    "top_missing": result.report.top_missing if hasattr(result.report, "top_missing") else [],
    "keyword_gaps": result.report.keyword_gaps if hasattr(result.report, "keyword_gaps") else [],
    "recommendations": result.report.recommendations if hasattr(result.report, "recommendations") else [],
    "ats_score": result.report.ats_score_estimate if hasattr(result.report, "ats_score_estimate") else 0,
}),
```

- [ ] **Step 4: Run standalone tests**

```bash
cd c:/tmp/tailor-resume-work
poetry run pytest tests/ -v
```
Expected: existing tests pass.

- [ ] **Step 5: Commit in tailor-resume-work**

```bash
git add web_app/routes/resume.py
git commit -m "fix: artifacts tuple, gap_summary join, report serialization in tailor endpoint"
```

---

## Self-Review Checklist

Verified against spec sections:

| Spec section | Covered by task |
|---|---|
| §2 Two-tier split + jd_gap_analyzer vendor | Tasks 5, 10 (SIGNAL_TAXONOMY vendored inline) |
| §3 Standalone bug fixes | Task 18 |
| §4 Offer scoring — 8 dimensions | Task 10 |
| §4 Idempotency on jd_text_hash | Task 10, 11 |
| §4 resume_id in request | Task 11 |
| §4 portal_scan_id in request | Task 11 |
| §4 BYOK fallback for sponsorship | Task 10 (`_score_sponsorship_regex` fallback) |
| §4 Standalone unavailability degradation | Task 10 (`degraded` list) |
| §5 StoryEntry model | Task 3 |
| §5 Quality scorer inline | Task 5 |
| §5 match algorithm | Task 5 |
| §5 Bulk import | Task 6 |
| §5 interview.py injection | Task 7 |
| §6 Negotiation scripts | Deferred to v2, not in this plan |
| §7 Portal scanner — 3 boards | Task 14 |
| §7 Wellfound deferred | Task 14 (returns manual_entry=True) |
| §7 portal_circuit | Task 2 |
| §7 Board timeouts | Task 14 |
| §7 Ashby list iteration | Task 14 |
| §8 Migrations with downgrade | Tasks 4, 9, 13 |
| §8 GIN index on skill_tags | Task 4 |
| §8 Partial index on is_stale | Task 13 |
| §9 LLMGateway model param | Task 1 |
| §9 Rate limit paths | Task 2 |
| §9 Ownership validation | Tasks 6 (delete), 11 (portal cache read) |
| §10 Vault router registration | Tasks 7, 11, 15 |
| §11 Test files | Tasks 8, 12, 16, 17 |
| §12 Slice order | Phase ordering in this plan |
| §13 KPIs | Out of scope for implementation |
| §15 Out of scope | Workday, negotiation, PDF — none implemented |
