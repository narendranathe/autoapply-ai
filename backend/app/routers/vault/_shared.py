"""
Shared helpers and singletons used across vault sub-modules.
"""

import json as _json

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.ats_service import ATSResult
from app.services.github_service import GitHubService
from app.services.resume_parser import ResumeParser
from app.services.retrieval_agent import ResumeWithScore, RetrievalAgent

# ── Singletons ─────────────────────────────────────────────────────────────

_retrieval_agent = RetrievalAgent()
_resume_parser = ResumeParser()
_github_service = GitHubService()


# ── Provider resolution ────────────────────────────────────────────────────


# Sentinel error message shown to clients still sending the legacy
# ``providers_json`` form field (with embedded ``api_key``). Issue #197:
# we MUST NOT accept client-supplied keys anymore — the backend looks up
# decrypted keys from ``user_provider_configs`` instead.
_LEGACY_PROVIDERS_JSON_ERROR = (
    "The 'providers_json' field is no longer accepted. Upgrade your client "
    "to send 'providers' with only {name, model} entries — API keys are "
    "now resolved server-side from your saved provider configurations."
)


def _reject_legacy_providers_json(providers_json: str | None) -> None:
    """Reject any non-empty ``providers_json`` form field with HTTP 422.

    Issue #197 (P0): clients used to embed plaintext ``api_key`` values in
    the ``providers_json`` body. That contract is now retired. Silent
    acceptance would be a security regression so we fail fast.
    """
    if providers_json and providers_json.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_LEGACY_PROVIDERS_JSON_ERROR,
        )


async def _get_provider_key(
    db: "AsyncSession",
    user: "User",
    provider_name: str,
) -> str:
    """Resolve the decrypted API key for ``provider_name`` from server storage.

    Returns the plaintext key. Never logs it. Raises 400 when the user has
    not configured this provider via ``PUT /users/provider-config`` (Issue
    #197 — no more client-supplied keys).
    """
    from sqlalchemy import select

    from app.models.user_provider_config import UserProviderConfig
    from app.utils.encryption import decrypt_value

    if not provider_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider name is required.",
        )

    result = await db.execute(
        select(UserProviderConfig).where(
            UserProviderConfig.user_id == user.id,
            UserProviderConfig.provider_name == provider_name,
        )
    )
    row = result.scalar_one_or_none()
    if row is None or not row.encrypted_api_key:
        # Do NOT log the user_id+provider+key triple together; safe to log
        # just "provider not configured" since the key is absent.
        logger.info(
            "Provider '{}' not configured for user {} — rejecting request",
            provider_name,
            user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Provider '{provider_name}' is not configured. "
                "Add the API key in Options before generating."
            ),
        )

    try:
        api_key = decrypt_value(row.encrypted_api_key)
    except Exception:
        # Never include the encrypted blob or any partial key material.
        logger.error("Failed to decrypt key for provider '{}'", provider_name)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Stored key for provider '{provider_name}' could not be "
                "decrypted. Re-save it in Options."
            ),
        ) from None

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Provider '{provider_name}' has no API key configured. "
                "Add it in Options before generating."
            ),
        )

    return api_key


async def _resolve_providers(
    providers_form: str,
    db: "AsyncSession",
    user: "User",
    *,
    legacy_providers_json: str | None = None,
) -> list[dict]:
    """
    Resolve the provider list for a generation endpoint (Issue #197).

    Client contract (NEW):
        providers = JSON array of ``{"name": str, "model": str}`` entries.
        NO ``api_key`` is accepted from the client.

    Resolution:
      * If the client sends ``providers`` with one or more entries → look up
        the decrypted key for each provider name and return enriched dicts
        ``{"name", "api_key", "model"}``.
      * If the client sends an empty ``providers`` (or nothing) → fall back
        to ALL of the user's configured providers from
        ``user_provider_configs``.

    Legacy field handling: ``legacy_providers_json`` is the value of any
    ``providers_json`` form field still being submitted by an outdated
    client. We reject it outright with HTTP 422 — no silent acceptance.

    The returned dicts include the decrypted ``api_key``. Callers MUST NOT
    log them and SHOULD pass them straight to ``LLMGateway.generate``.
    """
    _reject_legacy_providers_json(legacy_providers_json)

    requested: list[dict] = []
    if providers_form and providers_form.strip():
        try:
            requested = _json.loads(providers_form)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid 'providers' JSON payload.",
            ) from exc
        if not isinstance(requested, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'providers' must be a JSON array.",
            )
        # Guard against any client that still sends an api_key field. We
        # don't trust it and we don't want it on the wire.
        for entry in requested:
            if not isinstance(entry, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Each 'providers' entry must be an object.",
                )
            if "api_key" in entry:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=_LEGACY_PROVIDERS_JSON_ERROR,
                )

    if requested:
        resolved: list[dict] = []
        for entry in requested:
            name = str(entry.get("name", "")).strip()
            if not name:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Each 'providers' entry requires a non-empty 'name'.",
                )
            model = str(entry.get("model", "") or "").strip()
            api_key = await _get_provider_key(db, user, name)
            resolved.append({"name": name, "api_key": api_key, "model": model})
        return resolved

    # ── No client list → read everything from server-side storage ─────────
    from sqlalchemy import select

    from app.models.user_provider_config import UserProviderConfig
    from app.utils.encryption import decrypt_value

    result = await db.execute(
        select(UserProviderConfig)
        .where(
            UserProviderConfig.user_id == user.id,
            UserProviderConfig.encrypted_api_key != "",
        )
        .order_by(UserProviderConfig.provider_name)
    )
    rows = result.scalars().all()
    providers: list[dict] = []
    for row in rows:
        try:
            api_key = decrypt_value(row.encrypted_api_key) if row.encrypted_api_key else ""
        except Exception:
            # Never log the encrypted blob.
            logger.warning(
                "Skipping provider '{}' — stored key failed to decrypt",
                row.provider_name,
            )
            api_key = ""
        if api_key:
            providers.append(
                {
                    "name": row.provider_name,
                    "api_key": api_key,
                    "model": row.model_override or "",
                }
            )
    return providers


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
