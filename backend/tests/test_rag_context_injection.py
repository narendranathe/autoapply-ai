"""
TDD tests for rag_context injection into generate_full_latex_resume.
Red-green cycle: these tests fail before the param is added, pass after.
"""

import inspect
from unittest.mock import patch

import pytest

from app.services.resume_generator import PersonalProfile, generate_full_latex_resume


def _make_profile() -> PersonalProfile:
    return PersonalProfile(
        name="Jane Doe",
        email="jane@example.com",
        phone="555-0100",
        linkedin_url="https://linkedin.com/in/jane",
        linkedin_label="linkedin.com/in/jane",
        portfolio_url="https://jane.dev",
        portfolio_label="jane.dev",
        work_history_text="Worked at Acme Corp as SWE.",
        education_text="B.S. Computer Science, State University.",
    )


def test_generate_full_latex_resume_has_rag_context_param():
    """AC-1: function must accept rag_context with default ''."""
    sig = inspect.signature(generate_full_latex_resume)
    assert (
        "rag_context" in sig.parameters
    ), "generate_full_latex_resume is missing rag_context param"
    default = sig.parameters["rag_context"].default
    assert default == "", f"rag_context default should be '' but got {default!r}"


@pytest.mark.asyncio
async def test_rag_context_nonempty_included_in_prompt():
    """AC-3: non-empty rag_context must appear in the string sent to the LLM."""
    captured_prompts: list[str] = []

    async def mock_llm(system_prompt, user_prompt, provider, api_key, ollama_model):
        captured_prompts.append(user_prompt)
        return "\\documentclass{article}\\begin{document}RESUME\\end{document}", "mock"

    with patch(
        "app.services.resume_generator._llm_generate",
        side_effect=mock_llm,
    ):
        await generate_full_latex_resume(
            profile=_make_profile(),
            jd_text="Software engineer role at TestCo.",
            company_name="TestCo",
            role_title="Software Engineer",
            job_id=None,
            ats_result=None,
            provider="mock",
            api_key="test",
            rag_context="UNIQUE_RAG_SENTINEL_XYZ",
        )

    assert captured_prompts, "LLM was never called"
    assert (
        "UNIQUE_RAG_SENTINEL_XYZ" in captured_prompts[0]
    ), "rag_context content not found in LLM prompt"


@pytest.mark.asyncio
async def test_rag_context_empty_string_not_injected():
    """AC-2: empty rag_context must not add a RAG section to the prompt."""
    captured_prompts: list[str] = []

    async def mock_llm(system_prompt, user_prompt, provider, api_key, ollama_model):
        captured_prompts.append(user_prompt)
        return "\\documentclass{article}\\begin{document}RESUME\\end{document}", "mock"

    with patch(
        "app.services.resume_generator._llm_generate",
        side_effect=mock_llm,
    ):
        await generate_full_latex_resume(
            profile=_make_profile(),
            jd_text="Software engineer role at TestCo.",
            company_name="TestCo",
            role_title="Software Engineer",
            job_id=None,
            ats_result=None,
            provider="mock",
            api_key="test",
            rag_context="",
        )

    assert captured_prompts, "LLM was never called"
    assert (
        "CANDIDATE BACKGROUND" not in captured_prompts[0]
    ), "RAG section should not appear in prompt when rag_context is empty"
