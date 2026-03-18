"""
User management endpoints.

PUT    /api/v1/users/github-token              → Store encrypted GitHub PAT
DELETE /api/v1/users/github-token              → Clear stored GitHub PAT
GET    /api/v1/users/provider-configs          → List all provider configs (keys masked)
PUT    /api/v1/users/provider-configs/{name}   → Upsert a provider config (encrypt key)
"""

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
    Only enabled rows with a non-empty encrypted key are included.
    """
    stmt = (
        select(UserProviderConfig)
        .where(
            UserProviderConfig.user_id == user.id,
            UserProviderConfig.is_enabled.is_(True),
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
            model_override=row.model_override,
            is_enabled=row.is_enabled,
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
            is_enabled=payload.is_enabled,
        )
        db.add(row)
    else:
        row.encrypted_api_key = encrypted_key
        row.model_override = payload.model_override
        row.is_enabled = payload.is_enabled

    await db.commit()
    await db.refresh(row)

    return ProviderConfigResponse(
        provider_name=row.provider_name,
        has_key=bool(row.encrypted_api_key),
        model_override=row.model_override,
        is_enabled=row.is_enabled,
    )
