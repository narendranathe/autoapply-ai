"""
Integration tests for RAG injection in /vault/generate endpoint.

AC-5: assert that the generate_resume handler:
  - calls get_rag_context_for_query() (with correct args)
  - forwards the returned context to generate_full_latex_resume as rag_context=

These tests use unittest.mock to isolate DB/LLM calls and verify wiring only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

RAG_SENTINEL = "RAG_SENTINEL_FROM_UPLOADED_DOCS_XYZ"


def _make_generate_result():
    """Return a minimal GeneratedResume-like object."""
    result = MagicMock()
    result.version_tag = "v1_TestCo_SWE"
    result.recruiter_filename = "Naren_Nathe_TestCo_SWE.pdf"
    result.latex_content = "\\documentclass{article}\\begin{document}RESUME\\end{document}"
    result.markdown_preview = "# Resume"
    result.ats_score_estimate = 85
    result.skills_gap = []
    result.changes_summary = "Tailored to JD."
    result.llm_provider_used = "mock"
    result.generation_warnings = []
    return result


# ---------------------------------------------------------------------------
# Test: handler calls get_rag_context_for_query and passes result through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_resume_calls_rag_and_passes_context():
    """
    AC-5: generate_resume handler must:
      1. await get_rag_context_for_query(...)
      2. pass the returned string as rag_context= to generate_full_latex_resume
    """
    captured_rag_ctx: list[str] = []

    async def mock_generate_full_latex_resume(**kwargs):
        captured_rag_ctx.append(kwargs.get("rag_context", "__MISSING__"))
        return _make_generate_result()

    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-123"
    mock_user.encrypted_llm_api_key = ""

    # Patch at the router module level
    with (
        patch(
            "app.routers.vault.get_rag_context_for_query",
            new_callable=AsyncMock,
            return_value=RAG_SENTINEL,
        ) as mock_rag,
        patch(
            "app.routers.vault.generate_full_latex_resume",
            side_effect=mock_generate_full_latex_resume,
        ),
        patch("app.routers.vault.score_resume", return_value=None),
        patch("app.routers.vault.build_tfidf_vector", return_value=[]),
        # Prevent actual DB insert
        patch.object(mock_db, "add"),
        patch.object(mock_db, "commit", new_callable=AsyncMock),
        patch.object(mock_db, "refresh", new_callable=AsyncMock),
    ):
        # Import here to avoid circular import at module load
        from app.routers.vault import generate_resume

        await generate_resume(
            company_name="TestCo",
            role_title="Software Engineer",
            jd_text="We need a Python engineer.",
            job_id=None,
            name="Jane Doe",
            phone="555-0100",
            email="jane@example.com",
            linkedin_url="https://linkedin.com/in/jane",
            linkedin_label="linkedin.com/in/jane",
            portfolio_url="",
            portfolio_label="",
            work_history_text="Worked at Acme.",
            education_text="B.S. CS",
            llm_provider="mock",
            llm_api_key="test-key",
            ollama_model="llama3.1:8b",
            base_resume_id=None,
            db=mock_db,
            user=mock_user,
        )

    # Assert rag service was called
    mock_rag.assert_awaited_once()
    call_kwargs = mock_rag.call_args.kwargs
    assert call_kwargs["user_id"] == mock_user.id
    assert "Software Engineer" in call_kwargs["query"]
    assert "TestCo" in call_kwargs["query"]
    assert call_kwargs["doc_types"] == ["resume", "work_history"]

    # Assert rag_context was forwarded
    assert captured_rag_ctx, "generate_full_latex_resume was never called"
    assert (
        captured_rag_ctx[0] == RAG_SENTINEL
    ), f"Expected rag_context={RAG_SENTINEL!r}, got {captured_rag_ctx[0]!r}"


@pytest.mark.asyncio
async def test_generate_resume_empty_rag_context_forwarded():
    """
    AC-2: When get_rag_context_for_query returns '', it is still forwarded
    (generate_full_latex_resume handles '' gracefully — no RAG section in prompt).
    """
    captured_rag_ctx: list[str] = []

    async def mock_generate_full_latex_resume(**kwargs):
        captured_rag_ctx.append(kwargs.get("rag_context", "__MISSING__"))
        return _make_generate_result()

    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = "user-uuid-456"
    mock_user.encrypted_llm_api_key = ""

    with (
        patch(
            "app.routers.vault.get_rag_context_for_query",
            new_callable=AsyncMock,
            return_value="",  # no documents uploaded
        ),
        patch(
            "app.routers.vault.generate_full_latex_resume",
            side_effect=mock_generate_full_latex_resume,
        ),
        patch("app.routers.vault.score_resume", return_value=None),
        patch("app.routers.vault.build_tfidf_vector", return_value=[]),
        patch.object(mock_db, "add"),
        patch.object(mock_db, "commit", new_callable=AsyncMock),
        patch.object(mock_db, "refresh", new_callable=AsyncMock),
    ):
        from app.routers.vault import generate_resume

        await generate_resume(
            company_name="NoDocsCo",
            role_title="Backend Dev",
            jd_text="Backend engineering role.",
            job_id=None,
            name="Jane Doe",
            phone="555-0100",
            email="jane@example.com",
            linkedin_url="https://linkedin.com/in/jane",
            linkedin_label="linkedin.com/in/jane",
            portfolio_url="",
            portfolio_label="",
            work_history_text="Worked at Beta Corp.",
            education_text="M.S. CS",
            llm_provider="mock",
            llm_api_key="test-key",
            ollama_model="llama3.1:8b",
            base_resume_id=None,
            db=mock_db,
            user=mock_user,
        )

    assert captured_rag_ctx, "generate_full_latex_resume was never called"
    assert (
        captured_rag_ctx[0] == ""
    ), f"Expected rag_context='' (empty), got {captured_rag_ctx[0]!r}"
