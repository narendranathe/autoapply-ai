"""
User management endpoints.

PUT    /api/v1/users/github-token              → Store encrypted GitHub PAT
DELETE /api/v1/users/github-token              → Clear stored GitHub PAT
GET    /api/v1/users/provider-configs          → List all provider configs (keys masked)
PUT    /api/v1/users/provider-configs/{name}   → Upsert a provider config (encrypt key)
"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.user_provider_config import UserProviderConfig
from app.schemas.user import (
    _VALID_PROVIDERS,
    GitHubTokenRequest,
    GitHubTokenResponse,
    ProviderConfigResponse,
    ProviderConfigsResponse,
    ProviderConfigUpsert,
)
from app.utils.encryption import decrypt_value, encrypt_value

router = APIRouter()


# ---------------------------------------------------------------------------
# Fingerprint helper  (P0-A migration verification, issue #198 round 2)
# ---------------------------------------------------------------------------


def _key_fingerprint(plaintext_key: str | None) -> str | None:
    """
    Return the first 8 hex chars of ``sha256(plaintext_key)`` or ``None``
    when no key is configured.

    Truncating to 8 chars (32 bits) is a deliberate trade-off: it gives
    the migration client a cheap collision-resistant check ("did the
    server store the same key I PUT?") while leaking less than the full
    hash. The plaintext key itself is high-entropy so even the truncated
    form is not a credible secret.
    """
    if not plaintext_key:
        return None
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()[:8]


def _safe_decrypt(encrypted: str | None) -> str | None:
    """
    Best-effort decrypt for fingerprint computation. Returns ``None`` on
    any failure — fingerprint then reads ``None`` and the migration
    client treats it as "no key", which is the correct safe default.
    """
    if not encrypted:
        return None
    try:
        return decrypt_value(encrypted)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helper — server-side provider resolution  (Feature #21)
# ---------------------------------------------------------------------------


async def get_user_providers(
    db: AsyncSession,
    user: User,
) -> list[dict]:
    """
    Return the ordered list of *enabled* provider dicts for ``user``,
    loaded from the ``user_provider_configs`` table.

    Each entry matches the shape the generation services expect::

        [{"name": "anthropic", "api_key": "<decrypted>", "model": "<override|default>"}]

    Providers are sorted by their name so the order is deterministic.
    A provider is considered enabled iff its ``encrypted_api_key`` is non-empty.
    """
    stmt = (
        select(UserProviderConfig)
        .where(
            UserProviderConfig.user_id == user.id,
            UserProviderConfig.encrypted_api_key != "",
        )
        .order_by(UserProviderConfig.provider_name)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    providers: list[dict] = []
    for row in rows:
        if not row.encrypted_api_key:
            continue
        try:
            api_key = decrypt_value(row.encrypted_api_key)
        except Exception:
            continue  # skip corrupted / key-mismatch rows silently
        entry: dict = {"name": row.provider_name, "api_key": api_key}
        if row.model_override:
            entry["model"] = row.model_override
        providers.append(entry)

    return providers


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


# ---------------------------------------------------------------------------
# Provider config endpoints  (Feature #21)
# ---------------------------------------------------------------------------


@router.get("/provider-configs", response_model=ProviderConfigsResponse)
async def get_provider_configs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProviderConfigsResponse:
    """
    Return all stored provider configs for the authenticated user.

    API keys are **never** returned — only a ``has_key`` boolean.
    """
    stmt = (
        select(UserProviderConfig)
        .where(UserProviderConfig.user_id == user.id)
        .order_by(UserProviderConfig.provider_name)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    configs = [
        ProviderConfigResponse(
            provider_name=row.provider_name,
            has_key=bool(row.encrypted_api_key),
            key_fingerprint=_key_fingerprint(_safe_decrypt(row.encrypted_api_key)),
            model_override=row.model_override,
            is_enabled=bool(row.encrypted_api_key),
        )
        for row in rows
    ]
    return ProviderConfigsResponse(configs=configs)


@router.put("/provider-configs/{provider_name}", response_model=ProviderConfigResponse)
async def upsert_provider_config(
    provider_name: str,
    payload: ProviderConfigUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProviderConfigResponse:
    """
    Create or update the provider config for ``provider_name``.

    - Encrypts the plaintext ``api_key`` with Fernet before persisting.
    - Pass ``api_key=""`` to clear an existing key (row is kept, ``has_key``
      becomes ``False``).
    - Idempotent: calling PUT twice with the same payload is safe.
    """
    if provider_name not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unknown provider '{provider_name}'. " f"Valid options: {sorted(_VALID_PROVIDERS)}"
            ),
        )

    # Encrypt the key (empty string stored as-is so the row can represent "no key")
    encrypted_key = encrypt_value(payload.api_key) if payload.api_key else ""

    # Upsert: look for existing row
    stmt = select(UserProviderConfig).where(
        UserProviderConfig.user_id == user.id,
        UserProviderConfig.provider_name == provider_name,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        row = UserProviderConfig(
            user_id=user.id,
            provider_name=provider_name,
            encrypted_api_key=encrypted_key,
            model_override=payload.model_override,
        )
        db.add(row)
    else:
        row.encrypted_api_key = encrypted_key
        row.model_override = payload.model_override

    await db.commit()
    await db.refresh(row)

    # P0-A: fingerprint is computed from the *plaintext* the caller just
    # PUT — we have it in scope (``payload.api_key``) so there is no need
    # to round-trip through the encrypted column. The migration client
    # compares this against the value GET returns to detect a stale row
    # that some other client wrote behind our back.
    return ProviderConfigResponse(
        provider_name=row.provider_name,
        has_key=bool(row.encrypted_api_key),
        key_fingerprint=_key_fingerprint(payload.api_key),
        model_override=row.model_override,
        is_enabled=bool(row.encrypted_api_key),
    )
