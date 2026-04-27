"""
vault/ router package.

This package decomposes the vault god-module into focused sub-modules.
The aggregated `router` is the only public symbol consumed by app/main.py:

    from app.routers import vault
    app.include_router(vault.router, prefix="/api/v1/vault", tags=["Vault"])

Sub-modules (route order matters — FastAPI first-match wins):
  resumes   — upload, list, get, delete, update, download, sync-markdown
  retrieve  — retrieve, retrieve/batch, ats-score
  generate  — generate, generate/tailored, generate/summary, generate/bullets, generate/cover-letter
  answers   — generate/answers, generate/answers/trim, answers/save, answers/bulk-save,
              answers/{id}, answers/{id}/feedback, answers/similar, answers/search,
              answers/{company}, cover-letters
  history   — history/{company}, analytics
  github    — github/versions
  documents — documents/upload-md, documents, documents/{filename}, documents/retrieve
  interview — interview-prep
  stories   — stories, stories/match, stories/import, stories/{story_id}
"""

from fastapi import APIRouter

from .answers import router as answers_router
from .documents import router as documents_router
from .generate import router as generate_router
from .github import router as github_router
from .history import router as history_router
from .interview import router as interview_router
from .resumes import router as resumes_router
from .retrieve import router as retrieve_router
from .stories import router as stories_router

router = APIRouter()
router.include_router(resumes_router)
router.include_router(retrieve_router)
router.include_router(generate_router)
router.include_router(answers_router)
router.include_router(history_router)
router.include_router(github_router)
router.include_router(documents_router)
router.include_router(interview_router)
router.include_router(stories_router)

__all__ = ["router"]
