"""
ATS Scoring Service — scores a resume against a job description.

Outputs:
  - overall_score (0-100)
  - keyword_coverage
  - skills_gap (JD skills not in resume)
  - skills_present (JD skills found in resume)
  - quantification_score (% of bullets with numbers)
  - experience_alignment
  - mq_coverage (minimum qualifications)
  - suggestions (top 5 actionable, based on resume_instructions.md rules)

Design principle: scores are diagnostic, not manipulative.
The system will NOT suggest adding skills the user doesn't have just to
raise the score — only reframing genuine experience using JD vocabulary.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# ── Seed skill vocabulary ───────────────────────────────────────────
# Common tech skills used for keyword extraction from JDs.
# Matched case-insensitively against both JD and resume text.

TECH_SKILLS = {
    # Languages
    "python",
    "sql",
    "scala",
    "java",
    "javascript",
    "typescript",
    "bash",
    "r",
    "go",
    "rust",
    "c++",
    "c#",
    # Data & ML
    "spark",
    "pyspark",
    "kafka",
    "airflow",
    "dagster",
    "dbt",
    "flink",
    "tensorflow",
    "pytorch",
    "scikit-learn",
    "mlflow",
    "ray",
    "feast",
    "langchain",
    "llamaindex",
    "rag",
    "llm",
    "transformers",
    "xgboost",
    "lightgbm",
    # Cloud
    "aws",
    "azure",
    "gcp",
    "google cloud",
    "s3",
    "ec2",
    "lambda",
    "glue",
    "redshift",
    "bigquery",
    "snowflake",
    "databricks",
    "fabric",
    "synapse",
    "dataflow",
    "azure devops",
    "github actions",
    "aks",
    "eks",
    "gke",
    # Data platforms
    "delta lake",
    "iceberg",
    "hudi",
    "parquet",
    "avro",
    "orc",
    "postgresql",
    "mysql",
    "oracle",
    "sql server",
    "mongodb",
    "cassandra",
    "elasticsearch",
    "redis",
    "dynamodb",
    # Infrastructure
    "docker",
    "kubernetes",
    "terraform",
    "helm",
    "ansible",
    "ci/cd",
    "jenkins",
    "bitbucket",
    "github",
    # Analytics & BI
    "power bi",
    "tableau",
    "looker",
    "superset",
    "streamlit",
    "dax",
    "ssrs",
    "ssas",
    # Concepts
    "etl",
    "elt",
    "data modeling",
    "star schema",
    "data warehouse",
    "data lake",
    "data lakehouse",
    "data mesh",
    "data contracts",
    "cdc",
    "streaming",
    "batch",
    "real-time",
    "olap",
    "oltp",
    "mlops",
    "feature engineering",
    "model serving",
    "a/b testing",
    "data governance",
    "data quality",
    "observability",
    "lineage",
    "vector database",
    "semantic search",
    "embeddings",
    # APIs & tooling
    "fastapi",
    "flask",
    "django",
    "rest",
    "graphql",
    "grpc",
    "openapi",
    "swagger",
    "celery",
}


@dataclass
class ATSResult:
    overall_score: float = 0.0  # 0–100
    keyword_coverage: float = 0.0  # % of JD keywords found in resume
    skills_present: list[str] = field(default_factory=list)
    skills_gap: list[str] = field(default_factory=list)
    quantification_score: float = 0.0  # % of bullets containing a number/metric
    experience_alignment: float = 0.0  # role/title keyword overlap
    mq_coverage: float = 0.0  # minimum qualifications coverage
    suggestions: list[str] = field(default_factory=list)
    total_jd_keywords: int = 0
    matched_keywords: int = 0


def _extract_keywords(text: str) -> set[str]:
    """
    Extract meaningful keywords from text.

    Multi-word skills (e.g. "delta lake") checked before single-word splits.
    """
    text_lower = text.lower()
    found: set[str] = set()

    # Check multi-word skills first
    for skill in sorted(TECH_SKILLS, key=len, reverse=True):
        if skill in text_lower:
            found.add(skill)

    return found


def _extract_jd_keywords(jd_text: str) -> set[str]:
    """
    Extract ALL keywords from a JD — both tech skills and role-specific noun phrases.
    """
    keywords = _extract_keywords(jd_text)

    # Also extract capitalised noun phrases (e.g. "Data Engineer", "Machine Learning")
    phrases = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", jd_text)
    for phrase in phrases:
        if len(phrase) > 3:
            keywords.add(phrase.lower())

    return keywords


def _extract_mqs(jd_text: str) -> list[str]:
    """
    Extract minimum qualification statements from JD.
    Looks for sections labelled 'minimum qualifications', 'required', 'requirements'.
    """
    text_lower = jd_text.lower()
    mq_section = ""

    for marker in [
        "minimum qualifications",
        "minimum requirements",
        "required qualifications",
        "requirements",
        "what you'll need",
        "basic qualifications",
    ]:
        idx = text_lower.find(marker)
        if idx != -1:
            # Extract up to 1500 chars after the marker
            mq_section = jd_text[idx : idx + 1500]
            break

    if not mq_section:
        return []

    # Extract bullet lines
    lines = [
        line.strip().lstrip("-•●▪◦*").strip()
        for line in mq_section.split("\n")
        if line.strip() and len(line.strip()) > 10
    ]
    return lines[:10]  # cap at 10 MQs


def _count_quantified_bullets(resume_text: str) -> tuple[int, int]:
    """
    Count bullets with quantified achievements vs total bullets.

    Returns (quantified_count, total_bullet_count)
    """
    lines = resume_text.split("\n")
    bullet_lines = [
        line
        for line in lines
        if line.strip()
        and (line.strip()[0] in "-•●▪◦" or re.match(r"^\s*[\u2022\u2023\u25E6\u2043\u2219]", line))
    ]

    # Also count lines that look like resume bullets (capitalised, 30+ chars)
    content_lines = [line for line in lines if len(line.strip()) > 30 and line.strip()[0].isupper()]
    all_bullets = list(set(bullet_lines + content_lines))
    total = len(all_bullets)

    # Quantified = contains a number, percentage, dollar, or multiplier
    _num_pat = r"\d+[%$x]?|\d+\.\d+|\$\d|[×x]\d|\d+k\b|\d+\s*hours|\d+\s*days"
    quantified = [line for line in all_bullets if re.search(_num_pat, line, re.I)]

    return len(quantified), max(total, 1)


def _compute_experience_alignment(jd_text: str, resume_text: str) -> float:
    """
    Compute how well the resume's role/level language aligns with the JD.
    Checks title keywords: senior, lead, staff, principal, architect, etc.
    """
    level_words = {
        "senior",
        "lead",
        "principal",
        "staff",
        "director",
        "architect",
        "manager",
        "head of",
        "vp",
        "vice president",
        "junior",
        "mid-level",
    }
    jd_lower = jd_text.lower()
    resume_lower = resume_text.lower()

    jd_levels = {w for w in level_words if w in jd_lower}
    resume_levels = {w for w in level_words if w in resume_lower}

    if not jd_levels:
        return 1.0  # JD doesn't specify level — no penalty

    matched = jd_levels & resume_levels
    return len(matched) / len(jd_levels)


def _load_instructions_snippet() -> str:
    """Load the key rules from resume_instructions.md for suggestion generation."""
    try:
        path = Path(__file__).parent.parent.parent.parent / "docs" / "resume_instructions.md"
        if path.exists():
            text = path.read_text(encoding="utf-8")
            # Return just the checklist section
            idx = text.find("## Resume Checklist")
            if idx != -1:
                return text[idx : idx + 1500]
    except Exception:
        pass
    return ""


def score_resume(jd_text: str, resume_text: str) -> ATSResult:
    """
    Score a resume against a job description.

    Args:
        jd_text:     Full job description text
        resume_text: Full resume text (raw extracted)

    Returns:
        ATSResult with scores and actionable suggestions
    """
    result = ATSResult()

    # 1. Keyword coverage
    jd_keywords = _extract_jd_keywords(jd_text)
    resume_keywords = _extract_keywords(resume_text)
    result.total_jd_keywords = len(jd_keywords)

    if jd_keywords:
        matched = jd_keywords & resume_keywords
        result.matched_keywords = len(matched)
        result.skills_present = sorted(matched)
        result.skills_gap = sorted(jd_keywords - resume_keywords)
        result.keyword_coverage = len(matched) / len(jd_keywords)

    # 2. Quantification score
    quantified, total_bullets = _count_quantified_bullets(resume_text)
    result.quantification_score = quantified / total_bullets

    # 3. Experience alignment
    result.experience_alignment = _compute_experience_alignment(jd_text, resume_text)

    # 4. MQ coverage
    mqs = _extract_mqs(jd_text)
    if mqs:
        resume_lower = resume_text.lower()
        mq_keywords = [_extract_keywords(mq) for mq in mqs]
        covered = sum(1 for kws in mq_keywords if any(k in resume_lower for k in kws))
        result.mq_coverage = covered / len(mqs)
    else:
        result.mq_coverage = 1.0  # Can't check what isn't listed

    # 5. Overall score (weighted composite)
    result.overall_score = round(
        (
            result.keyword_coverage * 0.40
            + result.quantification_score * 0.25
            + result.experience_alignment * 0.15
            + result.mq_coverage * 0.20
        )
        * 100,
        1,
    )

    # 6. Generate suggestions (diagnostic — based on real gaps, not padding)
    result.suggestions = _generate_suggestions(result, jd_text, resume_text)

    return result


def _generate_suggestions(result: ATSResult, jd_text: str, resume_text: str) -> list[str]:
    """
    Generate up to 5 actionable, honest suggestions.

    Follows the integrity rule: reframe genuine experience using JD vocabulary —
    never suggest adding skills the candidate doesn't have.
    """
    suggestions: list[str] = []

    # Quantification
    if result.quantification_score < 0.5:
        suggestions.append(
            "Less than half your bullets include metrics. Add specific numbers "
            "(%, $, time saved, scale) to bullets where outcomes are measurable. "
            "Use the XYZ formula: accomplished [X] as measured by [Y], by doing [Z]."
        )

    # Keyword coverage — only suggest reframing, not fabrication
    if result.keyword_coverage < 0.5 and result.skills_gap:
        top_gaps = result.skills_gap[:3]
        suggestions.append(
            f"JD keywords missing from your resume: {', '.join(top_gaps)}. "
            "If you have genuine experience with these, reframe an existing bullet "
            "using this terminology. Do not add them if you cannot defend them in an interview."
        )

    # MQ coverage
    if result.mq_coverage < 0.8:
        suggestions.append(
            "Some minimum qualifications may not be clearly demonstrated. "
            "Review the 'Requirements' section of the JD and ensure every MQ you meet "
            "is explicitly visible in your experience bullets."
        )

    # Experience alignment
    if result.experience_alignment < 0.6:
        suggestions.append(
            "Your seniority level language doesn't closely match the JD. "
            "If applying for a senior/lead role, make sure scope, team size, and "
            "cross-functional impact are evident in your bullets."
        )

    # Cloud coherence — flag if multiple clouds listed prominently
    cloud_platforms = {"aws", "azure", "gcp", "google cloud"}
    resume_clouds = cloud_platforms & _extract_keywords(resume_text)
    jd_clouds = cloud_platforms & _extract_keywords(jd_text)
    if len(resume_clouds) >= 3 and len(jd_clouds) == 1:
        target_cloud = list(jd_clouds)[0].upper()
        suggestions.append(
            f"Your resume lists {len(resume_clouds)} cloud platforms equally. "
            f"This JD focuses on {target_cloud}. Lead with your {target_cloud} experience "
            "and mention others briefly in supporting context — 'also deployed on AWS' — "
            "to tell a more coherent story."
        )

    return suggestions[:5]
