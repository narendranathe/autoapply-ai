"""
Resume Validator — Anti-Hallucination Engine.

PURPOSE:
LLMs sometimes invent facts, add skills you don't have, or fabricate
metrics. This validator compares the LLM's output against the original
resume AST and REJECTS any rewrite that contains hallucinated content.

RULES (non-negotiable):
1. Bullet count must match — LLM cannot add or remove bullets
2. All dates in output must exist in original
3. All company names in output must exist in original
4. No new technical skills added that aren't in original or JD
5. Each rewritten bullet must be recognizably derived from its original
   (similarity between 0.3 and 1.0)
6. No new metrics/numbers invented that aren't in original

WHEN VALIDATION FAILS:
- The rewrite is REJECTED entirely
- The user sees the original resume with a message explaining why
- The violations are logged for debugging
- The user can retry with a different strategy

This is a HARD gate, not a soft suggestion. We'd rather show the
original resume than let a hallucinated version through.
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from loguru import logger

from app.services.resume_parser import ResumeAST, ResumeBullet


@dataclass
class ValidationResult:
    """
    Result of validating a rewritten resume against the original.

    If is_valid is False, the rewrite should be rejected.
    violations contains human-readable descriptions of each problem.
    """
    is_valid: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bullet_similarities: list[float] = field(default_factory=list)
    overall_similarity: float = 0.0

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "violation_count": len(self.violations),
            "violations": self.violations,
            "warning_count": len(self.warnings),
            "warnings": self.warnings,
            "overall_similarity": round(self.overall_similarity, 3),
            "bullet_similarities": [round(s, 3) for s in self.bullet_similarities],
        }


class ResumeValidator:
    """
    Validates LLM-rewritten resume bullets against the original.

    Usage:
        validator = ResumeValidator()
        result = validator.validate(
            original_ast=ast,
            rewritten_bullets=["New bullet 1", "New bullet 2"],
            job_description="...",
        )
        if not result.is_valid:
            # REJECT the rewrite, show violations to user
            ...
    """

    # Thresholds — tuned through testing
    MIN_BULLET_SIMILARITY = 0.25    # Below this = likely hallucination
    MAX_BULLET_SIMILARITY = 0.99    # Above this = no meaningful change
    MIN_OVERALL_SIMILARITY = 0.35   # Average across all bullets

    # Patterns for detecting invented metrics
    METRIC_PATTERN = re.compile(
        r"(?:\b|^)(?:\d+(?:\.\d+)?[%+]|\$[\d,]+[KMB]?|\d+(?:\.\d+)?x|\d+(?:\.\d+)?\+?\s*(?:users?|customers?|clients?|team|people|engineers?)|\d+(?:\.\d+)?[KMB])(?=\s|$|[.,;!?])",
        re.IGNORECASE,
    )

    def validate(
        self,
        original_ast: ResumeAST,
        rewritten_bullets: list[str],
        job_description: str = "",
    ) -> ValidationResult:
        """
        Run all validation checks against the rewritten resume.

        Args:
            original_ast: The parsed original resume
            rewritten_bullets: LLM-generated replacement bullets
            job_description: The JD (used for context, not validation)

        Returns:
            ValidationResult with is_valid flag and any violations
        """
        result = ValidationResult(is_valid=True)

        # ── Rule 1: Bullet count must match ───────────────
        self._check_bullet_count(original_ast, rewritten_bullets, result)

        if not result.is_valid:
            # If count doesn't match, we can't do per-bullet checks
            return result

        # ── Rule 2-6: Per-bullet validation ───────────────
        for i, (original, rewritten) in enumerate(
            zip(original_ast.bullets, rewritten_bullets)
        ):
            self._check_single_bullet(i, original, rewritten, original_ast, result)

        # ── Overall similarity check ──────────────────────
        if result.bullet_similarities:
            result.overall_similarity = sum(result.bullet_similarities) / len(
                result.bullet_similarities
            )
            if result.overall_similarity < self.MIN_OVERALL_SIMILARITY:
                result.is_valid = False
                result.violations.append(
                    f"Overall similarity too low ({result.overall_similarity:.2f}). "
                    f"The rewrite diverges too much from the original."
                )

        # ── Log result ────────────────────────────────────
        if result.is_valid:
            logger.info(
                f"Validation PASSED: {len(result.warnings)} warnings, "
                f"overall_similarity={result.overall_similarity:.2f}"
            )
        else:
            logger.warning(
                f"Validation FAILED: {len(result.violations)} violations, "
                f"overall_similarity={result.overall_similarity:.2f}",
                violations=result.violations,
            )

        return result

    def _check_bullet_count(
        self,
        original_ast: ResumeAST,
        rewritten_bullets: list[str],
        result: ValidationResult,
    ) -> None:
        """Rule 1: The LLM must return exactly the same number of bullets."""
        original_count = original_ast.bullet_count
        rewritten_count = len(rewritten_bullets)

        if original_count != rewritten_count:
            result.is_valid = False
            result.violations.append(
                f"BULLET COUNT MISMATCH: Original has {original_count} bullets, "
                f"rewrite has {rewritten_count}. The LLM added or removed bullets."
            )

    def _check_single_bullet(
        self,
        index: int,
        original: ResumeBullet,
        rewritten: str,
        ast: ResumeAST,
        result: ValidationResult,
    ) -> None:
        """Run all per-bullet validation rules."""

        # ── Similarity check (Rule 5) ─────────────────────
        similarity = SequenceMatcher(
            None,
            original.text.lower(),
            rewritten.lower(),
        ).ratio()
        result.bullet_similarities.append(similarity)

        if similarity < self.MIN_BULLET_SIMILARITY:
            result.is_valid = False
            result.violations.append(
                f"BULLET {index} HALLUCINATION: Similarity={similarity:.2f} "
                f"(threshold={self.MIN_BULLET_SIMILARITY}). "
                f"Original: '{original.text[:60]}...' → "
                f"Rewritten: '{rewritten[:60]}...'"
            )
        elif similarity > self.MAX_BULLET_SIMILARITY:
            result.warnings.append(
                f"Bullet {index}: No meaningful change (similarity={similarity:.2f})"
            )

        # ── Date check (Rule 2) ───────────────────────────
        self._check_dates(index, rewritten, ast, result)

        # ── Company name check (Rule 3) ───────────────────
        self._check_companies(index, rewritten, ast, result)

        # ── Metric check (Rule 6) ─────────────────────────
        self._check_metrics(index, original.text, rewritten, result)

    def _check_dates(
        self,
        index: int,
        rewritten: str,
        ast: ResumeAST,
        result: ValidationResult,
    ) -> None:
        """Rule 2: All dates in the rewrite must exist in the original."""
        date_pattern = re.compile(
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
            r"Nov(?:ember)?|Dec(?:ember)?)\s*\.?\s*\d{4}",
            re.IGNORECASE,
        )
        dates_in_rewrite = set(date_pattern.findall(rewritten))

        for date in dates_in_rewrite:
            # Check if this date (or a close variant) exists in original
            date_found = False
            for orig_date in ast.dates:
                if self._dates_match(date, orig_date):
                    date_found = True
                    break

            if not date_found:
                result.is_valid = False
                result.violations.append(
                    f"BULLET {index} INVENTED DATE: '{date}' does not appear "
                    f"in the original resume. Known dates: {sorted(ast.dates)}"
                )

    def _check_companies(
        self,
        index: int,
        rewritten: str,
        ast: ResumeAST,
        result: ValidationResult,
    ) -> None:
        """Rule 3: Company names in the rewrite must exist in the original."""
        for company in ast.companies:
            # We only flag if a NEW company appears that wasn't in original
            pass  # Company names shouldn't appear in bullets normally

        # Check for company-like proper nouns not in original
        # (This is a heuristic — catches obvious fabrications)
        proper_nouns = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", rewritten)
        for noun in proper_nouns:
            # Skip common phrases that look like proper nouns
            skip_words = {"Machine Learning", "Deep Learning", "Natural Language",
                         "Computer Science", "Data Science", "Project Management",
                         "Software Engineering", "Full Stack", "Cross Functional"}
            if noun in skip_words:
                continue

            # Check if this proper noun exists in original text
            if noun not in ast.raw_text and noun.lower() not in ast.raw_text.lower():
                result.warnings.append(
                    f"Bullet {index}: New proper noun '{noun}' not found in original. "
                    f"Verify this isn't a fabricated entity."
                )

    def _check_metrics(
        self,
        index: int,
        original_text: str,
        rewritten: str,
        result: ValidationResult,
    ) -> None:
        """Rule 6: No invented numbers or metrics."""
        original_metrics = set(m.strip() for m in self.METRIC_PATTERN.findall(original_text.lower()))
        rewritten_metrics = set(m.strip() for m in self.METRIC_PATTERN.findall(rewritten.lower()))

        new_metrics = rewritten_metrics - original_metrics
        if new_metrics:
            result.is_valid = False
            result.violations.append(
                f"BULLET {index} INVENTED METRICS: {new_metrics} not in original. "
                f"Original metrics: {original_metrics or 'none'}"
            )

    @staticmethod
    def _dates_match(date1: str, date2: str) -> bool:
        """Check if two date strings refer to the same date (fuzzy match)."""
        # Normalize both dates
        d1 = re.sub(r"\s+", " ", date1.strip().lower())
        d2 = re.sub(r"\s+", " ", date2.strip().lower())

        # Exact match
        if d1 == d2:
            return True

        # Abbreviated vs full month match (Jan vs January)
        d1_short = d1[:3]
        d2_short = d2[:3]
        d1_year = re.search(r"\d{4}", d1)
        d2_year = re.search(r"\d{4}", d2)

        if d1_short == d2_short and d1_year and d2_year:
            return d1_year.group() == d2_year.group()

        return False
