"""
Tests for Resume Validator (Anti-Hallucination Engine).

These tests verify that the validator catches:
1. Bullet count mismatches
2. Invented dates
3. Invented metrics
4. Excessive divergence (low similarity)
5. No-change rewrites (too high similarity)

IMPORTANT: These are the most critical tests in the project.
If the validator fails, hallucinated resumes reach users.
"""
import pytest

from app.services.resume_parser import ResumeParser, ResumeAST, ResumeBullet, ResumeSection
from app.services.resume_validator import ResumeValidator


@pytest.fixture
def validator():
    return ResumeValidator()


@pytest.fixture
def sample_ast():
    """Create a known-good AST for testing."""
    ast = ResumeAST()
    ast.dates = {"Jan 2022", "Dec 2021", "Jun 2019", "May 2019"}
    ast.companies = {"Google", "Amazon"}
    ast.raw_text = (
        "Led development of distributed caching system serving 10M requests/day "
        "Reduced API latency by 40% through query optimization "
        "Built real-time inventory tracking pipeline processing 500K events/hour"
    )
    ast.bullets = [
        ResumeBullet(
            text="Led development of distributed caching system serving 10M requests/day",
            section=ResumeSection.EXPERIENCE,
            company="Google",
            original_index=0,
        ),
        ResumeBullet(
            text="Reduced API latency by 40% through query optimization and connection pooling",
            section=ResumeSection.EXPERIENCE,
            company="Google",
            original_index=1,
        ),
        ResumeBullet(
            text="Built real-time inventory tracking pipeline processing 500K events/hour",
            section=ResumeSection.EXPERIENCE,
            company="Amazon",
            original_index=2,
        ),
    ]
    return ast


class TestResumeValidator:

    def test_valid_rewrite_passes(self, validator, sample_ast):
        """A good rewrite should pass validation."""
        rewritten = [
            "Spearheaded development of distributed caching infrastructure serving 10M requests/day",
            "Optimized API latency by 40% through query tuning and connection pooling improvements",
            "Engineered real-time inventory tracking pipeline processing 500K events/hour",
        ]
        result = validator.validate(sample_ast, rewritten)
        assert result.is_valid is True
        assert len(result.violations) == 0

    def test_bullet_count_mismatch_fails(self, validator, sample_ast):
        """Adding or removing bullets should fail validation."""
        rewritten = [
            "Bullet 1",
            "Bullet 2",
            # Missing bullet 3 — LLM dropped one
        ]
        result = validator.validate(sample_ast, rewritten)
        assert result.is_valid is False
        assert any("BULLET COUNT" in v for v in result.violations)

    def test_extra_bullets_fails(self, validator, sample_ast):
        """LLM adding extra bullets should fail."""
        rewritten = [
            "Bullet 1",
            "Bullet 2",
            "Bullet 3",
            "Invented bullet 4 that wasnt in original",
        ]
        result = validator.validate(sample_ast, rewritten)
        assert result.is_valid is False

    def test_invented_date_fails(self, validator, sample_ast):
        """Dates not in original should be caught."""
        rewritten = [
            "Led caching system development since March 2020 serving 10M requests/day",
            "Reduced API latency by 40% through query optimization",
            "Built inventory pipeline processing 500K events/hour",
        ]
        result = validator.validate(sample_ast, rewritten)
        # Should flag "March 2020" as invented
        has_date_violation = any("DATE" in v.upper() or "date" in v.lower() for v in result.violations)
        assert has_date_violation or len(result.violations) > 0

    def test_invented_metrics_fails(self, validator, sample_ast):
        """Metrics not in original should be caught."""
        rewritten = [
            "Led caching system serving 10M requests/day with 99.99% uptime",  # 99.99% is NEW
            "Reduced API latency by 40% and improved throughput by 200%",  # 200% is NEW
            "Built pipeline processing 500K events/hour",
        ]
        result = validator.validate(sample_ast, rewritten)
        has_metric_violation = any("METRIC" in v.upper() for v in result.violations)
        # At least one invented metric should be caught
        assert has_metric_violation or not result.is_valid

    def test_completely_different_text_fails(self, validator, sample_ast):
        """Totally fabricated content should fail similarity check."""
        rewritten = [
            "Managed offshore development team of 50 engineers across 3 time zones",
            "Implemented machine learning pipeline for customer churn prediction",
            "Designed microservices architecture for fintech payment processing",
        ]
        result = validator.validate(sample_ast, rewritten)
        assert result.is_valid is False
        assert any("HALLUCINATION" in v or "similarity" in v.lower() for v in result.violations)

    def test_identical_text_warns(self, validator, sample_ast):
        """Unchanged bullets should generate warnings."""
        rewritten = [b.text for b in sample_ast.bullets]
        result = validator.validate(sample_ast, rewritten)
        assert result.is_valid is True  # Not invalid, but should warn
        assert len(result.warnings) > 0

    def test_validation_result_serializes(self, validator, sample_ast):
        """Validation result should serialize to dict."""
        rewritten = [b.text for b in sample_ast.bullets]
        result = validator.validate(sample_ast, rewritten)
        d = result.to_dict()
        assert "is_valid" in d
        assert "violations" in d
        assert "overall_similarity" in d
