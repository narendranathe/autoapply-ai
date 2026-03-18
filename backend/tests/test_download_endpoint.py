"""TDD tests for Issue #15 — download endpoint Content-Disposition fix.

Verifies that GET /vault/download/{resume_id}:
  1. Returns a Content-Disposition header
  2. Content-Disposition includes a filename ending in .tex
  3. media_type is application/x-tex (not application/octet-stream)
  4. Filename is derived from resume version_tag (or falls back to resume.id)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import Response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resume(
    *,
    latex_content: str = "\\documentclass{article}\\begin{document}RESUME\\end{document}",
    version_tag: str | None = "Narendranath_Google_SWE",
    recruiter_filename: str | None = None,
    resume_id: uuid.UUID | None = None,
) -> MagicMock:
    """Return a minimal Resume-like mock."""
    r = MagicMock()
    r.id = resume_id or uuid.uuid4()
    r.latex_content = latex_content
    r.raw_text = "raw text fallback"
    r.markdown_content = "# Resume"
    r.version_tag = version_tag
    r.recruiter_filename = recruiter_filename
    return r


async def _call_download(resume_mock: MagicMock, fmt: str = "tex") -> Response:
    """
    Call download_resume_file() with a mocked DB and user,
    returning the FastAPI Response object directly.
    """
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()

    # db.execute(...).scalar_one_or_none() → resume_mock
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = resume_mock
    mock_db.execute = AsyncMock(return_value=execute_result)

    from app.routers.vault import download_resume_file

    return await download_resume_file(
        resume_id=resume_mock.id,
        fmt=fmt,
        db=mock_db,
        user=mock_user,
    )


# ---------------------------------------------------------------------------
# Test 1: Response has a Content-Disposition header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_has_content_disposition_header():
    """Content-Disposition must be present so the browser triggers a Save dialog."""
    resume = _make_resume()
    response = await _call_download(resume)

    assert "content-disposition" in {
        k.lower() for k in response.headers
    }, "Response is missing Content-Disposition header — browser will show unnamed binary blob"


# ---------------------------------------------------------------------------
# Test 2: filename ends in .tex
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_filename_ends_with_tex():
    """Content-Disposition filename must end in .tex for the default fmt=tex."""
    resume = _make_resume(version_tag="Narendranath_Stripe_Backend")
    response = await _call_download(resume, fmt="tex")

    cd = response.headers.get("content-disposition") or response.headers.get(
        "Content-Disposition", ""
    )
    assert cd, "Content-Disposition header missing"
    assert ".tex" in cd, f"Expected .tex in Content-Disposition, got: {cd!r}"


# ---------------------------------------------------------------------------
# Test 3: media_type is application/x-tex, NOT application/octet-stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_media_type_is_application_x_tex():
    """media_type must be application/x-tex, not the generic octet-stream."""
    resume = _make_resume()
    response = await _call_download(resume, fmt="tex")

    assert (
        "application/x-tex" in response.media_type
    ), f"Expected media_type=application/x-tex, got {response.media_type!r}"


# ---------------------------------------------------------------------------
# Test 4a: Filename is derived from version_tag when available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_filename_uses_version_tag():
    """When version_tag is set, the download filename should include it."""
    resume = _make_resume(version_tag="Narendranath_Amazon_SDE2", recruiter_filename=None)
    response = await _call_download(resume, fmt="tex")

    cd = response.headers.get("content-disposition") or response.headers.get(
        "Content-Disposition", ""
    )
    assert "Narendranath_Amazon_SDE2" in cd, f"Expected version_tag in filename, got: {cd!r}"


# ---------------------------------------------------------------------------
# Test 4b: Filename falls back to resume.id when version_tag is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_filename_falls_back_to_resume_id():
    """When version_tag is None and recruiter_filename is None, fallback is resume.id."""
    rid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    resume = _make_resume(version_tag=None, recruiter_filename=None, resume_id=rid)
    response = await _call_download(resume, fmt="tex")

    cd = response.headers.get("content-disposition") or response.headers.get(
        "Content-Disposition", ""
    )
    assert str(rid) in cd, f"Expected resume UUID in fallback filename, got: {cd!r}"


# ---------------------------------------------------------------------------
# Test 5: markdown fmt returns text/markdown and .md extension
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_markdown_fmt():
    """fmt=markdown should return text/markdown with .md filename."""
    resume = _make_resume(version_tag="Narendranath_Meta_PM")
    response = await _call_download(resume, fmt="markdown")

    assert (
        "text/markdown" in response.media_type
    ), f"Expected text/markdown for fmt=markdown, got {response.media_type!r}"
    cd = response.headers.get("content-disposition") or response.headers.get(
        "Content-Disposition", ""
    )
    assert ".md" in cd, f"Expected .md extension for markdown download, got: {cd!r}"
