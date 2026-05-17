"""
Shared helpers and singletons used across vault sub-modules.
"""

import json as _json
import uuid as _uuid

from fastapi import HTTPException, Request, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.models.user_provider_config import UserProviderConfig
from app.services.ats_service import ATSResult
from app.services.github_service import GitHubService
from app.services.resume_parser import ResumeParser
from app.services.retrieval_agent import ResumeWithScore, RetrievalAgent
from app.services.user_provider_configs import (
    ProviderNotConfiguredError,
    resolve_decrypted_key,
    resolve_user_providers,
)

# ── Singletons ─────────────────────────────────────────────────────────────

_retrieval_agent = RetrievalAgent()
_resume_parser = ResumeParser()
_github_service = GitHubService()


# ── Provider resolution (Issue #197 — server-side keys only) ───────────────


_PROVIDERS_JSON_REJECT_MSG = (
    "providers_json is no longer accepted. The client must send "
    "`providers` as a JSON list of {name, model} objects; API keys are "
    "resolved server-side from the user's provider configs (Issue #197)."
)


def _reject_providers_json(
    value: str,
    *,
    field_name: str = "providers_json",
    user_id: _uuid.UUID | None = None,
    request: Request | None = None,
) -> None:
    """Reject or soften the deprecated ``providers_json`` field.

    Issue #197 removed the contract where the client transmits decrypted
    API keys on every request. The default behaviour is hard 422 — no
    backward-compat window — so misconfigured clients fail loudly.

    Observability (P1-F): every rejection logs a structured WARNING with
    the user id and ``User-Agent`` header so operators can identify
    which extension installs are still on the legacy contract during
    the Chrome Web Store rollout.

    Transition window (P0-G): when
    :attr:`Settings.ACCEPT_LEGACY_PROVIDERS_JSON` is ``True``, the field
    is NOT rejected. Instead this function returns silently after
    logging a WARNING. The caller (``_resolve_providers``) is
    responsible for parsing the legacy payload and stripping the
    embedded ``api_key`` so it never reaches downstream — the server
    resolves keys from ``user_provider_configs`` regardless. Operators
    should flip the flag back to ``False`` once the new extension is
    fully rolled out.
    """
    if not value or not value.strip():
        return

    ua = request.headers.get("user-agent", "<unknown>") if request is not None else "<unknown>"
    if settings.ACCEPT_LEGACY_PROVIDERS_JSON:
        # Transition window — log and let the caller strip api_key.
        logger.warning(
            "legacy_providers_json_accepted user={} ua={} reason=ACCEPT_LEGACY_PROVIDERS_JSON",
            user_id,
            ua,
        )
        return

    # Strict mode — log first so operators can see WHICH clients are
    # being rejected (an HTTPException after this point doesn't carry
    # request context into the logs by default).
    logger.warning(
        "legacy_providers_json_rejected user={} ua={}",
        user_id,
        ua,
    )
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"error": "providers_json_removed", "message": _PROVIDERS_JSON_REJECT_MSG},
    )


def _parse_providers(providers: str) -> list[dict]:
    """Parse the new ``providers`` form field — JSON list of ``{name, model}``.

    Returns ``[]`` for empty / whitespace-only input. Raises 422 on
    malformed JSON or a non-list payload so the client gets a clear
    error.
    """
    if not providers or not providers.strip():
        return []
    try:
        parsed = _json.loads(providers)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_providers",
                "message": f"providers field must be JSON: {exc}",
            },
        ) from exc
    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_providers",
                "message": "providers must be a JSON list of {name, model} objects",
            },
        )
    # Strip out any stray api_key keys the client might still send — they
    # are explicitly ignored now.
    return [
        {"name": str(e.get("name", "")), "model": str(e.get("model", ""))}
        for e in parsed
        if isinstance(e, dict)
    ]


def _parse_legacy_providers_json_stripped(value: str) -> list[dict]:
    """Parse the legacy ``providers_json`` form field and strip ``api_key``.

    Issue #197 P0-G — only invoked when
    :attr:`Settings.ACCEPT_LEGACY_PROVIDERS_JSON` is ``True``. The
    embedded ``api_key`` value is dropped on the floor (the server
    resolves keys server-side regardless) so even in the transition
    window a legacy client cannot smuggle a key past us.

    Returns the same shape as ``_parse_providers``. Malformed JSON or a
    non-list payload is treated as "no providers" so a buggy legacy
    client falls through to the empty-list server-fallback rather than
    failing the request — the goal of the flag is to keep old installs
    working during rollout.
    """
    if not value or not value.strip():
        return []
    try:
        parsed = _json.loads(value)
    except Exception:
        logger.warning("legacy_providers_json_unparseable — falling back to server enumeration")
        return []
    if not isinstance(parsed, list):
        return []
    return [
        {"name": str(e.get("name", "")), "model": str(e.get("model", ""))}
        for e in parsed
        if isinstance(e, dict)
    ]


async def _resolve_providers(
    providers: str,
    db: "AsyncSession",
    user: "User",
    *,
    providers_json: str | None = None,
    request: Request | None = None,
) -> list[dict]:
    """Resolve the provider list for a generation endpoint.

    Issue #197 — the request body now carries only ``providers`` as a
    JSON list of ``{name, model}``. API keys live in the
    ``user_provider_configs`` table and are decrypted in-memory via
    :func:`resolve_decrypted_key`.

    The legacy ``providers_json`` parameter (which used to carry decrypted
    API keys from the client) is rejected with 422 — no backward-compat
    window. Callers must pass it to this helper so we get a single,
    consistent rejection path.

    Returned entries::

        [{"name": "anthropic", "model": "...", "api_key": DecryptedKey}, ...]

    ``api_key`` is a :class:`DecryptedKey` instance — call ``.expose()``
    only at the boundary that hands it to the LLM provider.

    When ``providers`` is empty, fall back to *every* server-side config
    the user has stored (legacy behaviour for clients that just send
    ``providers=""``). Each row goes through ``resolve_decrypted_key`` so
    a corrupt row is skipped rather than crashing the request.
    """
    if providers_json is not None:
        _reject_providers_json(providers_json, user_id=user.id, request=request)

    requested = _parse_providers(providers)
    # P0-G transition window — when the flag is on and the legacy field
    # carried provider entries, fall back to them so the request still
    # works. The ``api_key`` inside is stripped by the parser; the
    # server resolves keys from ``user_provider_configs`` regardless.
    if (
        not requested
        and providers_json
        and providers_json.strip()
        and settings.ACCEPT_LEGACY_PROVIDERS_JSON
    ):
        requested = _parse_legacy_providers_json_stripped(providers_json)

    if requested:
        # Strict mode — the client explicitly named providers. If any of
        # them lacks a server-side key, surface HTTP 400 with the missing
        # provider name so the extension can prompt the user to add the
        # key in Options instead of silently falling back to keyword-only
        # generation (which would look like a quality regression).
        try:
            return await resolve_user_providers(user.id, requested, db, strict=True)
        except ProviderNotConfiguredError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "provider_not_configured",
                    "provider": exc.provider_name,
                    "message": str(exc),
                },
            ) from exc

    # No client-supplied list — server-side fallback: pull every
    # configured provider from the DB. This is the documented
    # backward-compatible path for clients that send ``providers=""`` and
    # let the server enumerate user configs. Drops (corrupt rows, decrypt
    # failures) are logged at INFO so operators can spot them; the empty
    # final list flows through to the keyword fallback in the endpoint.
    result = await db.execute(
        select(UserProviderConfig)
        .where(
            UserProviderConfig.user_id == user.id,
            UserProviderConfig.encrypted_api_key != "",
        )
        .order_by(UserProviderConfig.provider_name)
    )
    rows = result.scalars().all()

    enriched: list[dict] = []
    for row in rows:
        key = await resolve_decrypted_key(user.id, row.provider_name, db)
        if key is None:
            # Promoted from DEBUG → INFO so the silent drop is visible at
            # the default log level (Issue #197 P1-F observability gap).
            logger.info(
                "provider_skipped user={} provider={} reason=decrypt_failed_or_empty",
                user.id,
                row.provider_name,
            )
            continue
        enriched.append(
            {
                "name": row.provider_name,
                "model": row.model_override or "",
                "api_key": key,
            }
        )
    return enriched


def _expose_providers_for_gateway(providers: list[dict]) -> list[dict]:
    """Convert ``DecryptedKey``-wrapped entries to plaintext-key entries.

    The downstream ``resume_generator`` helpers still expect
    ``{"name", "api_key": str, "model"}`` because they pass ``api_key``
    straight to ``LLMGateway.generate(api_key=...)``. We unwrap exactly
    here so ``.expose()`` is invoked at a single, auditable boundary.

    Ollama entries have ``api_key=None`` and are emitted as ``""`` for
    the gateway call.
    """
    out: list[dict] = []
    for p in providers:
        raw = p.get("api_key")
        if raw is None:
            plaintext = ""
        elif isinstance(raw, str):
            # Defensive — shouldn't happen after resolve_user_providers,
            # but the cascade helpers occasionally re-enter with already
            # plain entries (tests).
            plaintext = raw
        else:
            plaintext = raw.expose()
        out.append(
            {
                "name": p.get("name", ""),
                "model": p.get("model", ""),
                "api_key": plaintext,
            }
        )
    return out


# ── Serialisation helpers ──────────────────────────────────────────────────


def _resume_to_dict(r: ResumeWithScore | None) -> dict | None:
    if r is None:
        return None
    return {
        "resume_id": str(r.resume_id),
        "version_tag": r.version_tag,
        "filename": r.filename,
        "file_type": r.file_type,
        "target_company": r.target_company,
        "target_role": r.target_role,
        "ats_score": r.ats_score,
        "similarity_score": r.similarity_score,
        "last_used": r.last_used,
        "outcomes": r.usage_outcomes,
        "github_path": r.github_path,
    }


def _ats_to_dict(r: ATSResult) -> dict:
    return {
        "overall_score": r.overall_score,
        "keyword_coverage": round(r.keyword_coverage * 100, 1),
        "skills_present": r.skills_present,
        "skills_gap": r.skills_gap,
        "quantification_score": round(r.quantification_score * 100, 1),
        "experience_alignment": round(r.experience_alignment * 100, 1),
        "mq_coverage": round(r.mq_coverage * 100, 1),
        "suggestions": r.suggestions,
        "total_jd_keywords": r.total_jd_keywords,
        "matched_keywords": r.matched_keywords,
    }
