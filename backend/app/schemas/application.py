"""
Application tracking schemas.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApplicationResponse(BaseModel):
    """Schema for returning application data."""

    id: uuid.UUID
    company_name: str
    role_title: str
    job_url: str | None
    platform: str | None
    git_path: str
    status: str
    rewrite_strategy: str | None
    similarity_score: float | None
    changes_summary: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplicationStatusUpdate(BaseModel):
    """Schema for updating application status."""

    status: str = Field(..., pattern=r"^(draft|tailored|applied|rejected|interview|offer)$")


class ApplicationListResponse(BaseModel):
    """Paginated list of applications."""

    items: list[ApplicationResponse]
    total: int
    page: int
    per_page: int
    has_next: bool
