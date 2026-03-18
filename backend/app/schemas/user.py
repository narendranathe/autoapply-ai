"""
User request/response schemas.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Provider config schemas (Feature #21)
# ---------------------------------------------------------------------------

_VALID_PROVIDERS = frozenset(
    {"anthropic", "openai", "groq", "kimi", "gemini", "perplexity", "ollama"}
)


class UserCreate(BaseModel):
    """Schema for creating a new user (from Clerk webhook)."""

    clerk_id: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., description="Used only for hashing, never stored raw")


class UserSetupGitHub(BaseModel):
    """Schema for connecting GitHub account."""

    github_username: str = Field(..., min_length=1, max_length=255)
    github_token: str = Field(..., min_length=10, description="Personal access token")
    repo_name: str = Field(default="resume-vault", min_length=1, max_length=255)


class UserSetupLLM(BaseModel):
    """Schema for configuring LLM API key."""

    provider: str = Field(..., pattern=r"^(openai|anthropic|ollama)$")
    api_key: str = Field(..., min_length=10, description="API key for the LLM provider")


class GitHubTokenRequest(BaseModel):
    """Schema for PUT /api/v1/users/github-token."""

    github_token: str = Field(..., min_length=10, description="GitHub Personal Access Token")
    github_username: str = Field(..., min_length=1, max_length=255)
    resume_repo_name: str = Field(default="resume-vault", min_length=1, max_length=255)


class GitHubTokenResponse(BaseModel):
    """Response for PUT and DELETE /api/v1/users/github-token."""

    configured: bool
    github_username: str | None
    resume_repo_name: str | None


class ProviderConfigUpsert(BaseModel):
    """
    Body for PUT /api/v1/users/provider-configs/{provider}.

    Upserts a single provider entry for the authenticated user.
    The ``api_key`` field accepts the *plaintext* key — the server
    encrypts it with Fernet before persisting.  Pass an empty string
    to clear an existing key while keeping the row (set enabled=False
    instead if you want to temporarily disable the provider).
    """

    api_key: str = Field(
        ...,
        description="Plaintext API key (encrypted at rest). Send empty string to clear.",
    )
    model_override: str | None = Field(
        None,
        max_length=100,
        description="Optional model ID override, e.g. 'gpt-4o-mini'.",
    )
    is_enabled: bool = Field(True, description="Whether this provider is active.")


class ProviderConfigResponse(BaseModel):
    """
    Safe representation of a single UserProviderConfig row.

    The raw API key is never returned; only a ``has_key`` boolean.
    """

    provider_name: str
    has_key: bool
    model_override: str | None
    is_enabled: bool

    model_config = {"from_attributes": True}


class ProviderConfigsResponse(BaseModel):
    """Response for GET /api/v1/users/provider-configs."""

    configs: list[ProviderConfigResponse]


class UserResponse(BaseModel):
    """Schema for returning user data. Note: NO sensitive fields."""

    id: uuid.UUID
    github_username: str | None
    resume_repo_name: str
    llm_provider: str | None
    has_github_token: bool = Field(description="True if GitHub token is configured")
    has_llm_key: bool = Field(description="True if LLM API key is configured")
    is_active: bool
    total_resumes_generated: int
    total_applications_tracked: int
    created_at: datetime

    model_config = {"from_attributes": True}
