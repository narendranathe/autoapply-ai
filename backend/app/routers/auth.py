"""
Auth endpoints.

POST /api/v1/auth/register   → Create/upsert user from Clerk webhook or first-time setup
GET  /api/v1/auth/me         → Return current authenticated user profile
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    clerk_id: str,
    email_hash: str,
    github_username: str = "",
    db: AsyncSession = Depends(get_db),
):
    """
    Create or upsert a user record from a Clerk user ID.

    Called by the Clerk webhook (user.created event) or manually on first login.
    Idempotent — safe to call multiple times for the same clerk_id.
    """
    existing = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = existing.scalar_one_or_none()

    if user:
        # Update mutable fields
        if github_username:
            user.github_username = github_username
        await db.commit()
        await db.refresh(user)
        return {"user_id": str(user.id), "created": False}

    user = User(
        id=uuid.uuid4(),
        clerk_id=clerk_id,
        email_hash=email_hash,
        github_username=github_username or None,
        resume_repo_name="resume-vault",
        is_active=True,
        total_resumes_generated=0,
        total_applications_tracked=0,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"user_id": str(user.id), "created": True}


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return {
        "user_id": str(user.id),
        "clerk_id": user.clerk_id,
        "github_username": user.github_username,
        "resume_repo_name": user.resume_repo_name,
        "is_active": user.is_active,
        "total_resumes_generated": user.total_resumes_generated,
        "total_applications_tracked": user.total_applications_tracked,
        "has_github_token": bool(user.encrypted_github_token),
        "has_llm_key": bool(user.encrypted_llm_api_key),
        "llm_provider": user.llm_provider,
    }
