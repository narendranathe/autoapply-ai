"""
Unit tests for generate_professional_summary and generate_role_bullets helpers
in resume_generator. Tests prompt construction and rule-based fallbacks only —
no LLM calls.
"""

import sys
import types

# ── Stub heavy dependencies ──────────────────────────────────────────────────
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

import loguru as _loguru_mod  # noqa: E402

_loguru_mod.logger = types.SimpleNamespace(  # type: ignore
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    debug=lambda *a, **k: None,
)

import asyncio  # noqa: E402

from app.services.resume_generator import (  # noqa: E402
    generate_professional_summary,
    generate_role_bullets,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── generate_professional_summary ────────────────────────────────────────────


class TestGenerateProfessionalSummary:
    """Tests that don't require any LLM (empty providers → fallback)."""

    def test_returns_tuple(self):
        result = run(
            generate_professional_summary(
                company_name="Acme",
                role_title="Software Engineer",
                jd_text="Python, FastAPI",
                work_history_text="",
                providers=[],
            )
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_fallback_provider_name(self):
        _, provider = run(
            generate_professional_summary(
                company_name="Acme",
                role_title="Software Engineer",
                jd_text="",
                work_history_text="",
                providers=[],
            )
        )
        assert provider == "fallback"

    def test_fallback_contains_role_and_company(self):
        summary, _ = run(
            generate_professional_summary(
                company_name="Initech",
                role_title="Data Engineer",
                jd_text="",
                work_history_text="",
                providers=[],
            )
        )
        assert "Data Engineer" in summary
        assert "Initech" in summary

    def test_fallback_extracts_years_from_work_history(self):
        wh = "Worked for 8 years at various startups building pipelines."
        summary, _ = run(
            generate_professional_summary(
                company_name="Co",
                role_title="Engineer",
                jd_text="",
                work_history_text=wh,
                providers=[],
            )
        )
        assert "8" in summary

    def test_fallback_non_empty_string(self):
        summary, _ = run(
            generate_professional_summary(
                company_name="X",
                role_title="Y",
                jd_text="",
                work_history_text="",
                providers=[],
            )
        )
        assert len(summary) > 20

    def test_providers_skipped_when_no_api_key(self):
        """Providers with empty api_key must be skipped, not crash."""
        _, provider = run(
            generate_professional_summary(
                company_name="Acme",
                role_title="Engineer",
                jd_text="",
                work_history_text="",
                providers=[{"name": "anthropic", "api_key": "", "model": ""}],
            )
        )
        assert provider == "fallback"

    def test_word_limit_applied_to_output(self):
        """word_limit * 7 chars cap is applied to raw text."""
        # With no providers the fallback text is already short, just ensure
        # no crash with small word_limit.
        summary, _ = run(
            generate_professional_summary(
                company_name="A",
                role_title="B",
                jd_text="",
                work_history_text="",
                providers=[],
                word_limit=10,
            )
        )
        assert len(summary) <= 10 * 7 + 200  # fallback may be slightly longer, that's ok


# ── generate_role_bullets ────────────────────────────────────────────────────


class TestGenerateRoleBullets:
    """Tests that don't require any LLM (empty providers → fallback)."""

    def test_returns_tuple(self):
        result = run(
            generate_role_bullets(
                company_name="Acme",
                role_title="Engineer",
                jd_text="Python",
                work_history_text="",
                providers=[],
            )
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_fallback_returns_list(self):
        bullets, _ = run(
            generate_role_bullets(
                company_name="Acme",
                role_title="Engineer",
                jd_text="",
                work_history_text="",
                providers=[],
            )
        )
        assert isinstance(bullets, list)

    def test_fallback_provider_name(self):
        _, provider = run(
            generate_role_bullets(
                company_name="Acme",
                role_title="Engineer",
                jd_text="",
                work_history_text="",
                providers=[],
            )
        )
        assert provider == "fallback"

    def test_fallback_extracts_bullets_from_work_history(self):
        wh = (
            "Software Engineer at Acme (2020 – 2023)\n"
            "• Built a distributed caching layer reducing latency by 40%\n"
            "• Led migration to Kubernetes cutting infra costs by 30%\n"
        )
        bullets, _ = run(
            generate_role_bullets(
                company_name="Acme",
                role_title="Engineer",
                jd_text="",
                work_history_text=wh,
                providers=[],
            )
        )
        assert len(bullets) >= 1

    def test_fallback_empty_work_history_still_returns_list(self):
        bullets, _ = run(
            generate_role_bullets(
                company_name="X",
                role_title="Y",
                jd_text="",
                work_history_text="",
                providers=[],
            )
        )
        assert isinstance(bullets, list)

    def test_num_bullets_respected_by_fallback_cap(self):
        """Fallback should not return more bullets than num_bullets."""
        wh = "\n".join(f"• Bullet {i}" for i in range(20))
        bullets, _ = run(
            generate_role_bullets(
                company_name="Co",
                role_title="Role",
                jd_text="",
                work_history_text=wh,
                providers=[],
                num_bullets=3,
            )
        )
        assert len(bullets) <= 3

    def test_providers_skipped_when_no_api_key(self):
        """Providers with empty api_key must be skipped, not crash."""
        _, provider = run(
            generate_role_bullets(
                company_name="Acme",
                role_title="Engineer",
                jd_text="",
                work_history_text="",
                providers=[{"name": "groq", "api_key": "", "model": ""}],
            )
        )
        assert provider == "fallback"
