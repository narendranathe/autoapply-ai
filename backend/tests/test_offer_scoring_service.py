"""Offer scoring unit tests — all formula dimensions, grade thresholds."""

from app.services.offer_scoring_service import (
    _grade,
    _score_brand_prestige,
    _score_compensation,
    _score_growth_trajectory,
    _score_interview_difficulty,
    _score_remote_flexibility,
    _score_sponsorship_regex,
    _score_tech_stack,
)

# ── Grade thresholds ──────────────────────────────────────────────────────────


def test_grade_A():
    assert _grade(95) == "A"


def test_grade_B():
    assert _grade(80) == "B"


def test_grade_C():
    assert _grade(62) == "C"


def test_grade_D():
    assert _grade(50) == "D"


def test_grade_F():
    assert _grade(30) == "F"


def test_grade_boundary_A():
    assert _grade(90) == "A"


def test_grade_boundary_B():
    assert _grade(75) == "B"


# ── Sponsorship ───────────────────────────────────────────────────────────────


def test_sponsorship_explicit_no():
    score = _score_sponsorship_regex(
        "Candidates must be authorized to work without sponsorship", "Acme"
    )
    assert score == 10.0


def test_sponsorship_explicit_yes():
    score = _score_sponsorship_regex("We offer H1B visa sponsorship for this role", "Acme")
    assert score == 85.0


def test_sponsorship_silent_dream_company():
    score = _score_sponsorship_regex("Great opportunity with competitive salary", "Google")
    assert score == 50.0


def test_sponsorship_silent_unknown():
    score = _score_sponsorship_regex("Great opportunity with competitive salary", "RandomCorp")
    assert score == 35.0


# ── Compensation ──────────────────────────────────────────────────────────────


def test_compensation_dream_company_no_salary():
    score = _score_compensation("Join our team of engineers", "Anthropic")
    assert score == 70.0


def test_compensation_unknown_no_salary():
    score = _score_compensation("Join our team of engineers", "RandomCorp")
    assert score == 50.0


# ── Remote flexibility ────────────────────────────────────────────────────────


def test_remote_fully_remote():
    assert _score_remote_flexibility("This is a fully remote position") == 100.0


def test_remote_onsite():
    assert _score_remote_flexibility("You must work on-site at our Dallas office") == 20.0


def test_remote_hybrid():
    assert _score_remote_flexibility("We offer a hybrid work arrangement") == 60.0


def test_remote_unspecified():
    assert _score_remote_flexibility("We are looking for a great engineer") == 50.0


# ── Growth trajectory ─────────────────────────────────────────────────────────


def test_growth_senior_staff():
    score = _score_growth_trajectory("Looking for a Senior Staff Data Engineer")
    assert score >= 50.0


def test_growth_no_signals():
    score = _score_growth_trajectory("Looking for a Data Engineer")
    assert score == 0.0


# ── Brand prestige ────────────────────────────────────────────────────────────


def test_brand_dream():
    assert _score_brand_prestige("Databricks") == 90.0


def test_brand_unknown():
    assert _score_brand_prestige("RandomStartup") == 50.0


def test_brand_case_insensitive():
    assert _score_brand_prestige("GOOGLE") == 90.0


# ── Interview difficulty ──────────────────────────────────────────────────────


def test_interview_no_signals():
    assert _score_interview_difficulty("Great team, work on interesting problems") == 80.0


def test_interview_leetcode():
    score = _score_interview_difficulty("We have a LeetCode style coding challenge")
    assert score < 80.0


# ── Tech stack ────────────────────────────────────────────────────────────────


def test_tech_stack_kafka_heavy():
    jd = "kafka streaming real-time kafka event kafka latency throughput flink kinesis"
    empty = "great team culture wonderful people"
    assert _score_tech_stack(jd) > _score_tech_stack(empty)


def test_tech_stack_empty_jd():
    assert _score_tech_stack("") == 0.0
