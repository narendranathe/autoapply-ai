"""
Vault sub-module: GitHub integration endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User

from ._shared import _github_service

router = APIRouter()


# ── GitHub versions directory ───────────────────────────────────────────────


@router.get("/github/versions")
async def list_github_versions(
    company: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    List all named resume versions from the GitHub resume-vault versions/ dir.

    Returns [{version_tag, path, sha, download_url}] for each .tex file.
    Requires user to have a GitHub token stored.
    """

    if not user.encrypted_github_token:
        raise HTTPException(
            status_code=400,
            detail="No GitHub token configured. Add your token via /api/v1/users/github-token.",
        )

    repo_full_name = f"{user.github_username}/{user.resume_repo_name}"
    try:
        versions = await _github_service.list_versions(
            encrypted_token=user.encrypted_github_token,
            repo_full_name=repo_full_name,
            company_filter=company,
        )
    except Exception as exc:
        logger.warning(f"GitHub list_versions failed: {exc}")
        raise HTTPException(status_code=502, detail=f"GitHub API error: {exc}") from exc

    return {"versions": versions, "total": len(versions)}
