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
"""

from fastapi import APIRouter

# Re-export service functions that tests patch at the vault namespace level
from app.services.ats_service import score_resume  # noqa: F401
from app.services.embedding_service import build_tfidf_vector  # noqa: F401
from app.services.rag_service import get_rag_context_for_query  # noqa: F401
from app.services.resume_generator import (  # noqa: F401
    generate_cover_letter,
    generate_full_latex_resume,
    generate_professional_summary,
    generate_role_bullets,
)

# Re-export singletons so tests patching "app.routers.vault._retrieval_agent" still work.
from ._shared import (  # noqa: F401
    _ats_to_dict,
    _github_service,
    _resolve_providers,
    _resume_parser,
    _resume_to_dict,
    _retrieval_agent,
)
from .answers import _compute_reward, _levenshtein  # noqa: F401
from .answers import router as answers_router
from .documents import router as documents_router
from .generate import (  # noqa: F401
    generate_bullets_endpoint,
    generate_cover_letter_endpoint,
    generate_resume,
    generate_summary_endpoint,
    generate_tailored_resume,
)
from .generate import router as generate_router
from .github import router as github_router
from .history import router as history_router
from .interview import router as interview_router
from .resumes import (  # noqa: F401
    delete_resume,
    download_resume_file,
    get_resume,
    list_resumes,
    sync_markdown,
    update_resume_metadata,
    upload_resume,
)
from .resumes import router as resumes_router

# Re-export endpoint functions so tests can import them directly from app.routers.vault
from .retrieve import _single_retrieve, ats_score, batch_retrieve, retrieve_resumes  # noqa: F401
from .retrieve import router as retrieve_router

router = APIRouter()
router.include_router(resumes_router)
router.include_router(retrieve_router)
router.include_router(generate_router)
router.include_router(answers_router)
router.include_router(history_router)
router.include_router(github_router)
router.include_router(documents_router)
router.include_router(interview_router)

__all__ = ["router"]
