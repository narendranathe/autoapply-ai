"""
vault/ router package.

This package decomposes the vault god-module into focused sub-modules.
The aggregated `router` is the only public symbol consumed by app/main.py:

    from app.routers import vault
    app.include_router(vault.router, prefix="/api/v1/vault", tags=["Vault"])

All routes are currently served through vault_flat.py (the original monolith,
renamed) while decomposition into sub-modules is in progress.

NOTE: Internal singletons (_retrieval_agent, etc.) are re-exported from
vault_flat so that tests patching "app.routers.vault._retrieval_agent" work.
However, since vault_flat functions reference their own module globals, tests
must patch "app.routers.vault_flat._retrieval_agent" for the patch to take
effect on the running code.
"""

import sys

import app.routers.vault_flat as _flat

# Make vault_flat's module globals accessible as vault package attributes.
# This ensures "from app.routers.vault import X" works for all public names.
_this_module = sys.modules[__name__]

for _name in dir(_flat):
    if not _name.startswith("__"):
        setattr(_this_module, _name, getattr(_flat, _name))

# Explicit re-exports for IDE / type checker awareness
router = _flat.router
_compute_reward = _flat._compute_reward
_levenshtein = _flat._levenshtein
_resolve_providers = _flat._resolve_providers
_retrieval_agent = _flat._retrieval_agent
_resume_parser = _flat._resume_parser
_ats_to_dict = _flat._ats_to_dict
_resume_to_dict = _flat._resume_to_dict
_single_retrieve = _flat._single_retrieve
_github_service = _flat._github_service

del _flat, _this_module, _name, sys

__all__ = ["router"]
