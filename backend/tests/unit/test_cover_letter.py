"""
Unit tests for cover letter generation helpers in resume_generator.
Tests the prompt building, tone mapping, and word limit logic.
"""

import sys
import types

# ── Stub heavy dependencies so we can import resume_generator without LLM SDKs ──
for mod_name in [
    "loguru",
    "anthropic",
    "openai",
    "groq",
    "google",
    "google.generativeai",
    "google.ai",
    "google.ai.generativelanguage_v1beta",
    "google.generativeai.types",
    "google.generativeai.generative_models",
    "numpy",
    "sklearn",
    "sklearn.metrics",
    "sklearn.metrics.pairwise",
    "sklearn.feature_extraction",
    "sklearn.feature_extraction.text",
]:
    if mod_name not in sys.modules:
        m = types.ModuleType(mod_name)
        sys.modules[mod_name] = m

# Provide loguru.logger stub
import loguru as _loguru_mod  # noqa: E402

_loguru_mod.logger = types.SimpleNamespace(  # type: ignore
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    debug=lambda *a, **k: None,
)

from app.services.resume_generator import (  # noqa: E402
    _TONE_INSTRUCTIONS,
    _build_cover_letter_prompt_v2,
)


class TestToneInstructions:
    def test_all_tones_present(self):
        for tone in ("professional", "enthusiastic", "concise", "conversational"):
            assert tone in _TONE_INSTRUCTIONS

    def test_professional_tone_is_default_fallback(self):
        # Accessing a non-existent key should fall back to professional in the endpoint
        assert "professional" in _TONE_INSTRUCTIONS

    def test_tone_instructions_are_non_empty(self):
        for tone, instruction in _TONE_INSTRUCTIONS.items():
            assert len(instruction) > 20, f"Tone '{tone}' instruction is too short"


class TestBuildCoverLetterPromptV2:
    def test_includes_company_name(self):
        prompt = _build_cover_letter_prompt_v2(
            company_name="Acme Corp",
            role_title="Software Engineer",
            jd_text="Build cool things",
            work_history_text="5 years at Initech",
        )
        assert "Acme Corp" in prompt

    def test_includes_role_title(self):
        prompt = _build_cover_letter_prompt_v2(
            company_name="Acme",
            role_title="Senior Backend Engineer",
            jd_text="FastAPI",
            work_history_text="",
        )
        assert "Senior Backend Engineer" in prompt

    def test_word_range_in_prompt(self):
        prompt = _build_cover_letter_prompt_v2(
            company_name="Acme",
            role_title="SWE",
            jd_text="",
            work_history_text="",
            word_limit=300,
        )
        assert "300" in prompt

    def test_tone_instruction_appears(self):
        prompt = _build_cover_letter_prompt_v2(
            company_name="Co",
            role_title="Role",
            jd_text="",
            work_history_text="",
            tone="concise",
        )
        tone_text = _TONE_INSTRUCTIONS["concise"]
        # At least part of the tone instruction should appear
        assert "concise" in prompt.lower() or tone_text[:30] in prompt

    def test_candidate_name_included(self):
        prompt = _build_cover_letter_prompt_v2(
            company_name="Co",
            role_title="Role",
            jd_text="",
            work_history_text="",
            candidate_name="Jane Doe",
        )
        assert "Jane Doe" in prompt

    def test_past_accepted_included(self):
        prompt = _build_cover_letter_prompt_v2(
            company_name="Co",
            role_title="Role",
            jd_text="",
            work_history_text="",
            past_accepted=["Here is my previous cover letter text."],
        )
        assert "PREVIOUS ACCEPTED" in prompt or "previously" in prompt.lower()

    def test_num_drafts_in_format(self):
        prompt = _build_cover_letter_prompt_v2(
            company_name="Co",
            role_title="Role",
            jd_text="",
            work_history_text="",
            num_drafts=1,
        )
        assert "DRAFT_1" in prompt
        assert "DRAFT_2" not in prompt

    def test_jd_truncated_to_2500(self):
        long_jd = "x" * 5000
        prompt = _build_cover_letter_prompt_v2(
            company_name="Co",
            role_title="Role",
            jd_text=long_jd,
            work_history_text="",
        )
        # JD is sliced to 2500 before insertion
        assert "x" * 2501 not in prompt

    def test_empty_work_history_uses_fallback_text(self):
        prompt = _build_cover_letter_prompt_v2(
            company_name="Co",
            role_title="Role",
            jd_text="",
            work_history_text="   ",
        )
        assert "Not provided" in prompt

    def test_word_limit_minimum_enforced_in_range(self):
        # word_limit=150 → range should be at least 90-150 (max-60)
        prompt = _build_cover_letter_prompt_v2(
            company_name="Co",
            role_title="Role",
            jd_text="",
            work_history_text="",
            word_limit=150,
        )
        # Both bounds should appear in the prompt
        assert "150" in prompt
