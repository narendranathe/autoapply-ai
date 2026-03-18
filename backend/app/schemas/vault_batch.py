"""
Schemas for POST /vault/retrieve/batch — Issue #16.

Allows Job Scout to retrieve ATS scoring data for N job cards
in a single network round-trip instead of N serial calls to /vault/retrieve.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BatchRetrieveItem(BaseModel):
    """A single job card to retrieve resume/ATS data for."""

    company: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="", max_length=255)
    jd_snippet: str = Field(default="", max_length=5000)


class BatchRetrieveRequest(BaseModel):
    """Request body for POST /vault/retrieve/batch."""

    jobs: list[BatchRetrieveItem] = Field(..., max_length=50)


class BatchRetrieveResult(BaseModel):
    """Result for a single job in the batch."""

    company: str
    role: str
    ats_score: float | None
    history_count: int
    best_resume_id: str | None


class BatchRetrieveResponse(BaseModel):
    """Response for POST /vault/retrieve/batch — one result per input job, order preserved."""

    results: list[BatchRetrieveResult]
