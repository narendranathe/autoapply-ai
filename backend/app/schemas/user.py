"""
User request/response schemas.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
