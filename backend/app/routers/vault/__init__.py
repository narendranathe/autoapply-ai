"""
vault/ — Router package decomposing the vault.py god module (2239 lines → 7 focused modules).

This __init__.py is the ONLY public interface. All sub-routers are included here and
the aggregated `router` is imported by app/main.py exactly as before:

    from app.routers import vault
    app.include_router(vault.router, prefix="/api/v1/vault", tags=["Vault"])

Sub-module map
--------------
Module              Endpoints                                       Est. lines
──────────────────  ──────────────────────────────────────────────  ──────────
resumes.py          POST   /upload                                    ~215
                    GET    /resumes
                    GET    /resumes/{id}
                    DELETE /resumes/{id}
                    PATCH  /resumes/{id}
                    GET    /download/{id}
                    POST   /sync-markdown
                    helpers: _resume_to_dict, _ats_to_dict

retrieve.py         POST   /retrieve                                  ~140
                    POST   /retrieve/batch
                    POST   /ats-score
                    helper: _single_retrieve (private)

generate.py         POST   /generate                                  ~380
                    POST   /generate/tailored
                    POST   /generate/summary
                    POST   /generate/bullets
                    POST   /generate/cover-letter

answers.py          POST   /generate/answers                          ~520
                    POST   /generate/answers/trim
                    POST   /answers/save
                    POST   /answers/bulk-save
                    DELETE /answers/{id}
                    PATCH  /answers/{id}/feedback
                    PATCH  /answers/{id}
                    GET    /answers/similar
                    GET    /answers/search
                    GET    /answers/{company_name}
                    GET    /cover-letters
                    helpers: _levenshtein, _compute_reward (private)

history.py          GET    /history/{company_name}                    ~60
                    GET    /analytics

github.py           GET    /github/versions                           ~55

documents.py        POST   /documents/upload-md                       ~130
                    GET    /documents
                    DELETE /documents/{source_filename}
                    POST   /documents/retrieve

interview.py        POST   /interview-prep                            ~180
                    helper: _rule_based_interview_questions (private)
                    constant: _INTERVIEW_SYSTEM

Shared utilities
----------------
- _resume_to_dict / _ats_to_dict  →  resumes.py (imported by retrieve.py and history.py)
- _levenshtein / _compute_reward  →  answers.py (private helpers, not re-exported)
- Module-level singletons:
    _retrieval_agent  = RetrievalAgent()   → resumes.py, imported by retrieve.py + answers.py
    _resume_parser    = ResumeParser()     → resumes.py
    _github_service   = GitHubService()    → github.py, imported by generate.py

Implementation notes
--------------------
- NO behavioural changes: all URL paths, HTTP methods, and response shapes are identical.
- Each sub-module defines its own `router = APIRouter()` with NO prefix.
- Route registration ORDER matters — FastAPI matches the first registered path:
    answers.py must register /answers/similar and /answers/search BEFORE /answers/{company}.
- The sub-routers must be included in this file in the order shown above.
- Shared singletons are instantiated once in the owning module and imported elsewhere.

Decomposition status: STUB ONLY — vault.py is unchanged.
Actual implementation is tracked in GitHub Issue #12.
"""

from fastapi import APIRouter

# ---------------------------------------------------------------------------
# Sub-router imports (uncomment each line as the corresponding module is completed)
# ---------------------------------------------------------------------------
# from app.routers.vault.resumes import router as resumes_router
# from app.routers.vault.retrieve import router as retrieve_router
# from app.routers.vault.generate import router as generate_router
# from app.routers.vault.answers import router as answers_router    # NOTE: before history
# from app.routers.vault.history import router as history_router
# from app.routers.vault.github import router as github_router
# from app.routers.vault.documents import router as documents_router
# from app.routers.vault.interview import router as interview_router

# ---------------------------------------------------------------------------
# Aggregated router — the only symbol consumed by app/main.py
# ---------------------------------------------------------------------------
router = APIRouter()

# Sub-routers are included here once their modules are implemented.
# Registration order matters: more-specific paths before parameterised catch-alls.
#
# router.include_router(resumes_router)
# router.include_router(retrieve_router)
# router.include_router(generate_router)
# router.include_router(answers_router)   # /answers/similar, /answers/search BEFORE /answers/{co}
# router.include_router(history_router)
# router.include_router(github_router)
# router.include_router(documents_router)
# router.include_router(interview_router)

# ---------------------------------------------------------------------------
# Migration bridge — while this package is being built out, the flat vault.py
# has been renamed to vault_flat.py so that app/main.py keeps working unchanged.
#
# Migration steps:
#   1. git mv backend/app/routers/vault.py backend/app/routers/vault_flat.py
#   2. Create this vault/ package (done — you are here).
#   3. Implement sub-modules one at a time; move routes out of vault_flat.py.
#   4. When all routes are migrated, remove vault_flat.py and this comment block.
# ---------------------------------------------------------------------------
# TODO(#12): remove the bridge import below once all sub-modules are wired in.
# from app.routers.vault_flat import router as _flat_router
# router.include_router(_flat_router)
