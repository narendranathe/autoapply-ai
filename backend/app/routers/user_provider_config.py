"""
User Provider Config router — Issue #25: server-side provider authority.

Endpoints:
  PUT    /api/v1/users/provider-config          → Upsert a provider config (encrypt api_key)
  GET    /api/v1/users/provider-config          → List configs (NEVER return api_key)
  DELETE /api/v1/users/provider-config/{name}   → Delete by provider name
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.user_provider_config import UserProviderConfig
from app.utils.encryption import encrypt_value

router = APIRouter()

_VALID_PROVIDERS = frozenset(
    {"anthropic", "openai", "groq", "kimi", "gemini", "perplexity", "ollama"}
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ProviderConfigIn(BaseModel):
    """Body for PUT /api/v1/users/provider-config."""

    name: str = Field(..., description="Provider name, e.g. 'anthropic'")
    model: str = Field("", description="Optional model override, e.g. 'gpt-4o-mini'")
    api_key: str = Field(
        ..., description="Plaintext API key (encrypted at rest). Empty string to clear."
    )
    enabled: bool = Field(True, description="Whether this provider is active.")


class ProviderConfigOut(BaseModel):
    """Safe representation — api_key is NEVER returned."""

    id: str
    name: str
    model: str | None
    enabled: bool

    model_config = {"from_attributes": False}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.put("/provider-config", status_code=status.HTTP_200_OK)
async def upsert_provider_config(
    payload: ProviderConfigIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProviderConfigOut:
    """
    Upsert (create or update) a provider config for the authenticated user.

    - Encrypts the plaintext api_key with Fernet before persisting.
    - Pass api_key="" to clear an existing key (row is kept with has_key=False).
    - Idempotent: calling PUT twice with the same payload is safe.
    """
    if payload.name not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider '{payload.name}'. Valid: {sorted(_VALID_PROVIDERS)}",
        )

    encrypted_key = encrypt_value(payload.api_key) if payload.api_key else ""

    stmt = select(UserProviderConfig).where(
        UserProviderConfig.user_id == user.id,
        UserProviderConfig.provider_name == payload.name,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        row = UserProviderConfig(
            user_id=user.id,
            provider_name=payload.name,
            encrypted_api_key=encrypted_key,
            model_override=payload.model or None,
            is_enabled=payload.enabled,
        )
        db.add(row)
    else:
        row.encrypted_api_key = encrypted_key
        row.model_override = payload.model or None
        row.is_enabled = payload.enabled

    await db.commit()
    await db.refresh(row)

    return ProviderConfigOut(
        id=str(row.id),
        name=row.provider_name,
        model=row.model_override,
        enabled=row.is_enabled,
    )


@router.get("/provider-config", status_code=status.HTTP_200_OK)
async def list_provider_configs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    Return all stored provider configs for the authenticated user.

    API keys are NEVER returned — only id, name, model, and enabled status.
    """
    stmt = (
        select(UserProviderConfig)
        .where(UserProviderConfig.user_id == user.id)
        .order_by(UserProviderConfig.provider_name)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    return {
        "configs": [
            ProviderConfigOut(
                id=str(r.id),
                name=r.provider_name,
                model=r.model_override,
                enabled=r.is_enabled,
            )
            for r in rows
        ],
        "total": len(rows),
    }


@router.delete("/provider-config/{provider_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_config(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a provider config row by provider name."""
    stmt = select(UserProviderConfig).where(
        UserProviderConfig.user_id == user.id,
        UserProviderConfig.provider_name == provider_name,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No config found for provider '{provider_name}'",
        )

    await db.delete(row)
    await db.commit()
