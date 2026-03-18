"""Pydantic schemas for the /reflect endpoint."""

from typing import Literal

from pydantic import BaseModel


class ReflectRequest(BaseModel):
    context_type: Literal["profile", "application", "jd"]
    application_id: str | None = None
    jd_text: str | None = None
    profile_summary: str | None = None
