"""Vault sub-module: story bank CRUD, match, and bulk import."""

import uuid
from datetime import datetime

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
        select(StoryEntry).where(StoryEntry.id == story_id, StoryEntry.user_id == user.id)
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
    from app.services.story_service import (
        get_user_stories,
        increment_story_usage,
        match_stories_to_jd,
    )

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
    Calls the standalone /resume/parse endpoint to get canonical Profile JSON,
    then creates StoryEntry candidates from each role's bullets.
    Requires STANDALONE_URL env var (defaults to http://localhost:7000).
    """
    import os

    import httpx

    from app.models.resume import Resume
    from app.services.story_service import SIGNAL_TAXONOMY, auto_score

    standalone_url = os.getenv("STANDALONE_URL", "http://localhost:7000")

    resume_result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = resume_result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{standalone_url}/api/v1/resume/parse",
                json={"resume_text": resume.raw_text or ""},
            )
            resp.raise_for_status()
            profile = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Standalone parse failed: {exc}") from exc

    created: list[StoryEntry] = []
    work_history = profile.get("work_history", [])

    for role in work_history:
        bullets = role.get("bullets", [])
        for bullet in bullets:
            text = bullet if isinstance(bullet, str) else bullet.get("text", "")
            if not text or len(text) < 20:
                continue

            text_lower = text.lower()
            best_domain = "leadership_ownership"
            best_count = 0
            for cat, kws in SIGNAL_TAXONOMY.items():
                count = sum(text_lower.count(kw) for kw in kws)
                if count > best_count:
                    best_count = count
                    best_domain = cat

            words = text.split()
            action = " ".join(words[:10])
            result_part = " ".join(words[10:]) if len(words) > 10 else text

            story = StoryEntry(
                user_id=user.id,
                skill_tags=[best_domain],
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
