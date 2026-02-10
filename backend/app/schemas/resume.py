"""
Resume processing schemas.
"""

from pydantic import BaseModel, Field


class ResumeTailorRequest(BaseModel):
    """Request to tailor a resume for a specific job."""

    job_description: str = Field(..., min_length=50, max_length=10000)
    company_name: str = Field(..., min_length=1, max_length=255)
    role_title: str = Field(..., min_length=1, max_length=255)
    job_url: str | None = Field(None, max_length=2048)
    platform: str = Field(default="manual", pattern=r"^(linkedin|greenhouse|workday|lever|manual)$")
    strategy: str = Field(default="moderate", pattern=r"^(slight_tweak|moderate|ground_up)$")


class ResumeTailorResponse(BaseModel):
    """Response after tailoring a resume."""

    application_id: str
    git_path: str
    strategy_used: str
    changes_summary: str
    similarity_to_previous: float | None = None
    previous_application_path: str | None = None
    validation_passed: bool
    validation_warnings: list[str] = Field(default_factory=list)
    used_fallback: bool


class ResumeParseResponse(BaseModel):
    """Response after parsing a resume."""

    bullet_count: int
    skills_detected: list[str]
    companies_found: list[str]
    dates_found: list[str]
    sections: dict[str, int]
