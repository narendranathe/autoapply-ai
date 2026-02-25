"""Unit tests for the semantic retrieval agent (pure-logic helpers)."""

from app.services.ats_service import ATSResult  # noqa: I001
from app.services.retrieval_agent import (
    ResumeWithScore,
    _company_matches,
    _levenshtein,
    _reuse_recommendation,
)


# ── Levenshtein ────────────────────────────────────────────────────────────


def test_levenshtein_identical():
    assert _levenshtein("google", "google") == 0


def test_levenshtein_one_insert():
    assert _levenshtein("gogle", "google") == 1


def test_levenshtein_completely_different():
    d = _levenshtein("abc", "xyz")
    assert d == 3


def test_levenshtein_empty():
    assert _levenshtein("", "abc") == 3
    assert _levenshtein("abc", "") == 3
    assert _levenshtein("", "") == 0


# ── Company matching ───────────────────────────────────────────────────────


def test_company_exact_match():
    assert _company_matches("Google", "Google") is True


def test_company_case_insensitive():
    assert _company_matches("GOOGLE", "google") is True


def test_company_substring_match():
    assert _company_matches("Goldman Sachs", "goldman") is True


def test_company_abbreviation_match():
    # Initials are first letter of each whitespace-token
    # "Goldman Sachs" → ["goldman","sachs"] → "gs" ✓
    assert _company_matches("Goldman Sachs", "gs") is True
    # "JP Morgan Chase" → ["jp","morgan","chase"] → "jmc" (JP is one token)
    assert _company_matches("JP Morgan Chase", "jmc") is True


def test_company_typo_match():
    assert _company_matches("Google", "Gooogle") is True  # 1 extra char


def test_company_no_match():
    assert _company_matches("Apple", "Microsoft") is False


def test_company_partial_name_match():
    assert _company_matches("Amazon Web Services", "amazon") is True


# ── Reuse recommendation ───────────────────────────────────────────────────


def _make_ats(score: float) -> ATSResult:
    return ATSResult(
        overall_score=score,
        keyword_coverage=0.5,
        skills_present=[],
        skills_gap=[],
        quantification_score=0.5,
        experience_alignment=0.5,
        mq_coverage=0.5,
        suggestions=[],
        total_jd_keywords=10,
        matched_keywords=5,
    )


def test_reuse_recommendation_no_resume():
    assert _reuse_recommendation(None, None) == "generate_new"


def test_reuse_recommendation_no_ats():
    resume = ResumeWithScore(
        resume_id=__import__("uuid").uuid4(),
        version_tag="v1",
        filename="test.tex",
        file_type="tex",
        target_company="Google",
        target_role="SWE",
        ats_score=80.0,
        similarity_score=1.0,
        last_used=None,
    )
    assert _reuse_recommendation(resume, None) == "tweak"


def test_reuse_recommendation_high_score():
    resume = ResumeWithScore(
        resume_id=__import__("uuid").uuid4(),
        version_tag="v1",
        filename="test.tex",
        file_type="tex",
        target_company="Google",
        target_role="SWE",
        ats_score=90.0,
        similarity_score=1.0,
        last_used=None,
    )
    assert _reuse_recommendation(resume, _make_ats(90)) == "reuse"


def test_reuse_recommendation_medium_score():
    resume = ResumeWithScore(
        resume_id=__import__("uuid").uuid4(),
        version_tag="v1",
        filename="test.tex",
        file_type="tex",
        target_company="Google",
        target_role="SWE",
        ats_score=70.0,
        similarity_score=0.8,
        last_used=None,
    )
    assert _reuse_recommendation(resume, _make_ats(70)) == "tweak"


def test_reuse_recommendation_low_score():
    resume = ResumeWithScore(
        resume_id=__import__("uuid").uuid4(),
        version_tag="v1",
        filename="test.tex",
        file_type="tex",
        target_company="Google",
        target_role="SWE",
        ats_score=40.0,
        similarity_score=0.4,
        last_used=None,
    )
    assert _reuse_recommendation(resume, _make_ats(40)) == "generate_new"
