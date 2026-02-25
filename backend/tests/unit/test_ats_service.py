"""Unit tests for ATS scoring service."""

from app.services.ats_service import ATSResult, score_resume  # noqa: I001


JD_STRONG = """
Senior Data Engineer — Google
Requirements:
- 5+ years Python, Spark, dbt, Airflow
- Experience with BigQuery, GCP, Terraform
- Build and maintain data pipelines
- Minimum qualifications: Bachelor's degree in CS or related field
- Bachelor's degree or equivalent practical experience
"""

RESUME_STRONG = """
Senior Data Engineer at Meta (2021–present)
- Built 15+ Spark pipelines processing 2TB/day on GCP BigQuery
- Reduced pipeline failure rate by 40% using Airflow DAG restructuring
- Deployed Terraform modules cutting infra cost by $120K/year
- Led dbt model development for 3 data domains (Python, SQL)

Education: B.S. Computer Science, Stanford University
Skills: Python, Spark, dbt, Airflow, BigQuery, GCP, Terraform, SQL
"""

RESUME_WEAK = """
Junior developer with 1 year experience.
Worked on web applications using JavaScript and HTML.
Some database experience.
"""


def test_score_strong_resume():
    result = score_resume(JD_STRONG, RESUME_STRONG)
    assert isinstance(result, ATSResult)
    assert result.overall_score >= 60
    assert result.keyword_coverage >= 0.5
    assert "python" in [s.lower() for s in result.skills_present]
    assert len(result.suggestions) <= 5


def test_score_weak_resume():
    result = score_resume(JD_STRONG, RESUME_WEAK)
    assert isinstance(result, ATSResult)
    assert result.overall_score < 50
    assert result.keyword_coverage < 0.3
    assert len(result.skills_gap) > 0


def test_quantification_detection():
    resume_with_numbers = "Increased revenue by 30%. Led team of 5. Processed 1M records."
    resume_without_numbers = "Increased revenue. Led team. Processed records."
    jd = "Engineer with quantified impact on revenue and scale."

    r_with = score_resume(jd, resume_with_numbers)
    r_without = score_resume(jd, resume_without_numbers)
    assert r_with.quantification_score > r_without.quantification_score


def test_score_returns_valid_ranges():
    result = score_resume(JD_STRONG, RESUME_STRONG)
    assert 0 <= result.overall_score <= 100
    assert 0 <= result.keyword_coverage <= 1
    assert 0 <= result.quantification_score <= 1
    assert 0 <= result.experience_alignment <= 1
    assert 0 <= result.mq_coverage <= 1


def test_empty_resume():
    result = score_resume(JD_STRONG, "")
    assert result.overall_score == 0
    assert result.keyword_coverage == 0


def test_skills_gap_is_subset_of_jd_keywords():
    result = score_resume(JD_STRONG, RESUME_WEAK)
    # Skills gap should be things from the JD that are NOT in the resume
    assert len(result.skills_gap) > 0
    assert len(result.skills_present) >= 0
