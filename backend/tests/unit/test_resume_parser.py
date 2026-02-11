"""
Tests for Resume Parser.

We test with known resume formats to ensure deterministic parsing.
These are the ground-truth tests — if the parser breaks, the
entire anti-hallucination system breaks.
"""
import pytest

from app.services.resume_parser import ResumeParser, ResumeSection


@pytest.fixture
def parser():
    return ResumeParser()


@pytest.fixture
def sample_resume_text():
    return """John Doe
john@email.com | (555) 123-4567

Experience

Google | Senior Software Engineer | Jan 2022 - Present
- Led development of distributed caching system serving 10M requests/day
- Reduced API latency by 40% through query optimization and connection pooling
- Mentored 3 junior engineers on system design best practices

Amazon | Software Engineer | Jun 2019 - Dec 2021
- Built real-time inventory tracking pipeline processing 500K events/hour
- Designed and implemented RESTful API consumed by 12 internal teams
- Wrote comprehensive test suite achieving 95% code coverage

Education

MIT | Bachelor of Science in Computer Science | May 2019

Skills

Python, Java, Go, SQL, PostgreSQL, Redis, Docker, Kubernetes, AWS, Terraform, CI/CD
"""


class TestResumeParser:

    def test_parses_bullet_points(self, parser, sample_resume_text):
        """Parser should find all bullet points."""
        ast = parser.parse_text(sample_resume_text)
        assert ast.bullet_count == 6  # 3 from Google + 3 from Amazon

    def test_detects_experience_section(self, parser, sample_resume_text):
        """Parser should identify the experience section."""
        ast = parser.parse_text(sample_resume_text)
        exp_bullets = ast.bullets_by_section(ResumeSection.EXPERIENCE)
        assert len(exp_bullets) == 6

    def test_extracts_dates(self, parser, sample_resume_text):
        """Parser should find all date references."""
        ast = parser.parse_text(sample_resume_text)
        assert len(ast.dates) > 0
        # Should find at least these dates
        date_strings = " ".join(ast.dates).lower()
        assert "2022" in date_strings or "jan" in date_strings

    def test_extracts_skills(self, parser, sample_resume_text):
        """Parser should detect skills from the skills section."""
        ast = parser.parse_text(sample_resume_text)
        assert "python" in ast.skills
        assert "docker" in ast.skills
        assert "aws" in ast.skills

    def test_generates_prompt_context(self, parser, sample_resume_text):
        """Prompt context should be formatted for LLM consumption."""
        ast = parser.parse_text(sample_resume_text)
        context = ast.to_prompt_context()
        assert "BULLET_0:" in context
        assert "EXPERIENCE" in context.upper()

    def test_empty_input(self, parser):
        """Parser should handle empty input gracefully."""
        ast = parser.parse_text("")
        assert ast.bullet_count == 0
        assert len(ast.parse_warnings) > 0

    def test_no_bullets_input(self, parser):
        """Parser should warn if no bullets found."""
        ast = parser.parse_text("Just some plain text with no bullet points at all.")
        assert ast.bullet_count == 0
        assert any("No bullet" in w for w in ast.parse_warnings)

    def test_to_dict_serialization(self, parser, sample_resume_text):
        """AST should serialize to a clean dictionary."""
        ast = parser.parse_text(sample_resume_text)
        d = ast.to_dict()
        assert "bullet_count" in d
        assert "skills" in d
        assert isinstance(d["skills"], list)
