"""
User management endpoints.

PUT    /api/v1/users/github-token  → Store encrypted GitHub PAT
DELETE /api/v1/users/github-token  → Clear stored GitHub PAT
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import GitHubTokenRequest, GitHubTokenResponse
from app.utils.encryption import encrypt_value

router = APIRouter()


@router.put("/github-token", response_model=GitHubTokenResponse)
async def put_github_token(
    payload: GitHubTokenRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GitHubTokenResponse:
    """
    Store an encrypted GitHub Personal Access Token for the authenticated user.

    The raw token is never stored or returned — only the Fernet-encrypted form
    is persisted. Subsequent calls overwrite the previous token.
    """
    user.encrypted_github_token = encrypt_value(payload.github_token)
    user.github_username = payload.github_username
    user.resume_repo_name = payload.resume_repo_name
    await db.commit()
    await db.refresh(user)

    return GitHubTokenResponse(
        configured=True,
        github_username=user.github_username,
        resume_repo_name=user.resume_repo_name,
    )


@router.delete("/github-token", response_model=GitHubTokenResponse)
async def delete_github_token(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GitHubTokenResponse:
    """
    Clear the stored GitHub Personal Access Token for the authenticated user.
    """
    user.encrypted_github_token = None
    await db.commit()
    await db.refresh(user)

    return GitHubTokenResponse(
        configured=False,
        github_username=user.github_username,
        resume_repo_name=user.resume_repo_name,
    )
