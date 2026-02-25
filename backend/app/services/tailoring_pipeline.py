"""
Resume Tailoring Pipeline — The orchestrator.

This is the main service that ties everything together:
1. Parse the resume into an AST
2. Call the LLM to rewrite bullets
3. Validate the rewrite (anti-hallucination)
4. If valid: return rewritten bullets
5. If invalid: REJECT and return original with explanation

This function is what the API endpoint calls.
"""

import time
from dataclasses import dataclass

from loguru import logger

from app.services.llm_service import (
    RewriteStrategy,
)
from app.services.llm_service import (
    tailor_resume as llm_tailor,
)
from app.services.resume_parser import ResumeAST, ResumeParser
from app.services.resume_validator import ResumeValidator, ValidationResult


@dataclass
class TailoringResult:
    """Complete result of the tailoring pipeline."""

    # The final bullets (either rewritten or original if rejected)
    bullets: list[str]
    # Was the LLM rewrite accepted by the validator?
    rewrite_accepted: bool
    # Did we fall back to keyword matching?
    used_fallback: bool
    # Human-readable summary
    summary: str
    # Validation details
    validation: ValidationResult | None
    # The parsed AST (for API response metadata)
    resume_ast: ResumeAST
    # Performance
    total_duration_ms: int
    parse_duration_ms: int
    llm_duration_ms: int
    validation_duration_ms: int

    def to_dict(self) -> dict:
        return {
            "rewrite_accepted": self.rewrite_accepted,
            "used_fallback": self.used_fallback,
            "summary": self.summary,
            "bullet_count": len(self.bullets),
            "validation": self.validation.to_dict() if self.validation else None,
            "resume_metadata": self.resume_ast.to_dict(),
            "performance": {
                "total_ms": self.total_duration_ms,
                "parse_ms": self.parse_duration_ms,
                "llm_ms": self.llm_duration_ms,
                "validation_ms": self.validation_duration_ms,
            },
        }


class TailoringPipeline:
    """
    Orchestrates the full resume tailoring flow.

    Usage:
        pipeline = TailoringPipeline()
        result = await pipeline.run(
            resume_bytes=file_content,
            file_format="docx",
            job_description="...",
            strategy=RewriteStrategy.MODERATE,
            provider="anthropic",
            encrypted_api_key="...",
        )
    """

    def __init__(self):
        self.parser = ResumeParser()
        self.validator = ResumeValidator()

    async def run(
        self,
        resume_bytes: bytes,
        file_format: str,
        job_description: str,
        strategy: RewriteStrategy,
        provider: str,
        encrypted_api_key: str,
        max_retries: int = 1,
    ) -> TailoringResult:
        """
        Execute the full tailoring pipeline.

        Args:
            resume_bytes: Raw file content
            file_format: "docx" or "pdf"
            job_description: JD text to tailor for
            strategy: How aggressively to rewrite
            provider: LLM provider name
            encrypted_api_key: Encrypted API key
            max_retries: How many times to retry on validation failure

        Returns:
            TailoringResult with bullets and metadata
        """
        total_start = time.perf_counter()

        # ── Step 1: Parse ─────────────────────────────────
        parse_start = time.perf_counter()
        resume_ast = self._parse_resume(resume_bytes, file_format)
        parse_ms = int((time.perf_counter() - parse_start) * 1000)

        if resume_ast.bullet_count == 0:
            return TailoringResult(
                bullets=[],
                rewrite_accepted=False,
                used_fallback=False,
                summary="Could not parse any bullet points from the resume. "
                "Please ensure your resume uses bullet points (•, -, *).",
                validation=None,
                resume_ast=resume_ast,
                total_duration_ms=int((time.perf_counter() - total_start) * 1000),
                parse_duration_ms=parse_ms,
                llm_duration_ms=0,
                validation_duration_ms=0,
            )

        logger.info(
            f"Parsed {resume_ast.bullet_count} bullets from {file_format} resume "
            f"in {parse_ms}ms"
        )

        # ── Step 2: LLM Rewrite ──────────────────────────
        llm_start = time.perf_counter()
        rewritten_bullets, used_fallback, llm_summary = await llm_tailor(
            resume_ast=resume_ast,
            job_description=job_description,
            strategy=strategy,
            provider_name=provider,
            encrypted_api_key=encrypted_api_key,
        )
        llm_ms = int((time.perf_counter() - llm_start) * 1000)

        logger.info(
            f"LLM rewrite complete in {llm_ms}ms "
            f"(fallback={used_fallback}, bullets={len(rewritten_bullets)})"
        )

        # ── Step 3: Validate (skip if fallback) ──────────
        validation_start = time.perf_counter()
        validation_result = None

        if not used_fallback:
            validation_result = self.validator.validate(
                original_ast=resume_ast,
                rewritten_bullets=rewritten_bullets,
                job_description=job_description,
            )

            # ── Retry on failure (with stricter strategy) ─
            if not validation_result.is_valid and max_retries > 0:
                logger.info(
                    f"Validation failed, retrying with SLIGHT_TWEAK "
                    f"({max_retries} retries left)"
                )
                rewritten_bullets, used_fallback, llm_summary = await llm_tailor(
                    resume_ast=resume_ast,
                    job_description=job_description,
                    strategy=RewriteStrategy.SLIGHT_TWEAK,
                    provider_name=provider,
                    encrypted_api_key=encrypted_api_key,
                )

                if not used_fallback:
                    validation_result = self.validator.validate(
                        original_ast=resume_ast,
                        rewritten_bullets=rewritten_bullets,
                        job_description=job_description,
                    )

        validation_ms = int((time.perf_counter() - validation_start) * 1000)

        # ── Step 4: Decide final output ───────────────────
        rewrite_accepted = True
        final_bullets = rewritten_bullets

        if validation_result and not validation_result.is_valid:
            # REJECT the rewrite — show original
            rewrite_accepted = False
            final_bullets = [b.text for b in resume_ast.bullets]
            summary = (
                f"Rewrite REJECTED: {len(validation_result.violations)} validation "
                f"violations detected (possible hallucination). Showing original resume. "
                f"Violations: {'; '.join(validation_result.violations[:3])}"
            )
        elif used_fallback:
            rewrite_accepted = False
            summary = llm_summary
        else:
            summary = llm_summary
            if validation_result and validation_result.warnings:
                summary += f" ({len(validation_result.warnings)} minor warnings)"

        total_ms = int((time.perf_counter() - total_start) * 1000)

        logger.info(
            f"Pipeline complete in {total_ms}ms: "
            f"accepted={rewrite_accepted}, fallback={used_fallback}, "
            f"bullets={len(final_bullets)}"
        )

        return TailoringResult(
            bullets=final_bullets,
            rewrite_accepted=rewrite_accepted,
            used_fallback=used_fallback,
            summary=summary,
            validation=validation_result,
            resume_ast=resume_ast,
            total_duration_ms=total_ms,
            parse_duration_ms=parse_ms,
            llm_duration_ms=llm_ms,
            validation_duration_ms=validation_ms,
        )

    def _parse_resume(self, file_bytes: bytes, file_format: str) -> ResumeAST:
        """Route to the correct parser based on file format."""
        if file_format == "docx":
            return self.parser.parse_docx(file_bytes)
        elif file_format == "pdf":
            return self.parser.parse_pdf(file_bytes)
        elif file_format == "txt":
            return self.parser.parse_text(file_bytes.decode("utf-8"))
        else:
            logger.error(f"Unsupported file format: {file_format}")
            ast = ResumeAST()
            ast.parse_warnings.append(f"Unsupported format: {file_format}")
            return ast
