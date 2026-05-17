"""
Auth endpoints.

POST  /api/v1/auth/register   → Create/upsert user from Clerk webhook or first-time setup
GET   /api/v1/auth/me         → Return current authenticated user profile
PATCH /api/v1/auth/me         → Update the authenticated user's profile
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_authenticated_clerk_id, get_current_user, get_db
from app.models.user import User
from app.schemas.user import ProfileResponse, ProfileUpdate, RegisterRequest

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_user(
    body: RegisterRequest,
    clerk_id: str = Depends(get_authenticated_clerk_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Create or upsert a user record for the authenticated caller.

    SECURITY: ``clerk_id`` is derived server-side from the validated Clerk
    JWT (or ``X-Clerk-User-Id`` header in dev / extension mode) — never
    from the request body. Unauthenticated callers are rejected with 401
    by the ``get_authenticated_clerk_id`` dependency, which blocks the
    account-takeover vector where any caller could create or overwrite
    any user record by supplying an arbitrary ``clerk_id``.

    Called by the Clerk webhook proxy (user.created event) or by the
    client on first login. Idempotent — safe to call multiple times for
    the same authenticated identity.
    """
    existing = await db.execute(select(User).where(User.clerk_id == clerk_id))
    user = existing.scalar_one_or_none()

    if user:
        # Update mutable fields
        if body.github_username:
            user.github_username = body.github_username
        await db.commit()
        await db.refresh(user)
        return {"user_id": str(user.id), "created": False}

    user = User(
        id=uuid.uuid4(),
        clerk_id=clerk_id,
        email_hash=body.email_hash,
        github_username=body.github_username or None,
        resume_repo_name="resume-vault",
        is_active=True,
        total_resumes_generated=0,
        total_applications_tracked=0,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"user_id": str(user.id), "created": True}


@router.get("/me", response_model=ProfileResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return ProfileResponse(
        user_id=str(user.id),
        clerk_id=user.clerk_id,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        city=user.city,
        state=user.state,
        zip_code=user.zip_code,
        country=user.country,
        linkedin_url=user.linkedin_url,
        github_url=user.github_url,
        portfolio_url=user.portfolio_url,
        degree=user.degree,
        years_experience=user.years_experience,
        salary=user.salary,
        sponsorship=user.sponsorship,
        github_username=user.github_username,
        resume_repo_name=user.resume_repo_name,
        is_active=user.is_active,
        total_resumes_generated=user.total_resumes_generated,
        total_applications_tracked=user.total_applications_tracked,
        has_github_token=bool(user.encrypted_github_token),
        has_llm_key=bool(user.encrypted_llm_api_key),
        llm_provider=user.llm_provider,
    )


@router.patch("/me", response_model=ProfileResponse)
async def update_me(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's profile. Only provided (non-None) fields are updated."""
    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return ProfileResponse(
        user_id=str(user.id),
        clerk_id=user.clerk_id,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone,
        city=user.city,
        state=user.state,
        zip_code=user.zip_code,
        country=user.country,
        linkedin_url=user.linkedin_url,
        github_url=user.github_url,
        portfolio_url=user.portfolio_url,
        degree=user.degree,
        years_experience=user.years_experience,
        salary=user.salary,
        sponsorship=user.sponsorship,
        github_username=user.github_username,
        resume_repo_name=user.resume_repo_name,
        is_active=user.is_active,
        total_resumes_generated=user.total_resumes_generated,
        total_applications_tracked=user.total_applications_tracked,
        has_github_token=bool(user.encrypted_github_token),
        has_llm_key=bool(user.encrypted_llm_api_key),
        llm_provider=user.llm_provider,
    )
