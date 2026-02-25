"""
Resume Parser — Converts DOCX/PDF into a structured Abstract Syntax Tree (AST).

WHY THIS EXISTS:
The LLM is only allowed to REPHRASE existing bullet points. To enforce this,
we need a structured representation of the original resume that we can compare
against the LLM output. This parser creates that structure.

DESIGN DECISIONS:
1. Uses pattern matching (regex), NOT LLM, for parsing — deterministic and fast
2. Preserves original text exactly — the "ground truth" for validation
3. Extracts entities (dates, companies, skills) for cross-referencing
4. Works with both DOCX and PDF input formats

USAGE:
    parser = ResumeParser()
    ast = parser.parse_docx(file_bytes)
    print(ast.bullets)       # All bullet points with context
    print(ast.skills)        # Extracted skill keywords
    print(ast.to_prompt())   # Formatted for LLM consumption
"""

import io
import re
from dataclasses import dataclass, field
from enum import Enum

import docx
import pdfplumber
from loguru import logger

# ══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════


class ResumeSection(str, Enum):
    """Standard resume sections we detect."""

    EXPERIENCE = "experience"
    EDUCATION = "education"
    SKILLS = "skills"
    PROJECTS = "projects"
    SUMMARY = "summary"
    CERTIFICATIONS = "certifications"
    AWARDS = "awards"
    GENERAL = "general"


@dataclass
class ResumeBullet:
    """
    A single bullet point from a resume, with full context.

    The LLM operates on these individually — it can rephrase the text
    but cannot change the section, company, dates, or add new bullets.
    """

    text: str  # The actual bullet text
    section: ResumeSection  # Which section this belongs to
    company: str | None = None  # Company/school this belongs to
    role: str | None = None  # Job title if detected
    dates: str | None = None  # Date range (e.g., "Jan 2023 - Present")
    original_index: int = 0  # Position in original resume
    char_count: int = 0  # Length of original text

    def __post_init__(self):
        self.char_count = len(self.text)


@dataclass
class ResumeAST:
    """
    Abstract Syntax Tree of a parsed resume.

    This is the structured representation that enables:
    1. Anti-hallucination validation (compare LLM output against this)
    2. Smart reuse (compare ASTs across applications)
    3. Skill gap analysis (compare skills against JD requirements)
    """

    bullets: list[ResumeBullet] = field(default_factory=list)
    skills: set[str] = field(default_factory=set)
    companies: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)
    dates: set[str] = field(default_factory=set)
    education: list[dict] = field(default_factory=list)
    raw_text: str = ""
    source_format: str = ""  # "docx" or "pdf"
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def bullet_count(self) -> int:
        return len(self.bullets)

    @property
    def sections(self) -> dict[str, int]:
        """Count of bullets per section."""
        counts: dict[str, int] = {}
        for bullet in self.bullets:
            section_name = bullet.section.value
            counts[section_name] = counts.get(section_name, 0) + 1
        return counts

    def bullets_by_section(self, section: ResumeSection) -> list[ResumeBullet]:
        """Get all bullets in a specific section."""
        return [b for b in self.bullets if b.section == section]

    def to_prompt_context(self) -> str:
        """
        Format the resume for LLM consumption.

        Groups bullets by section and company, with clear labels.
        The LLM receives this structured format, NOT raw text.
        """
        output_lines: list[str] = []
        current_section = None
        current_company = None

        for bullet in self.bullets:
            # Section header
            if bullet.section != current_section:
                current_section = bullet.section
                output_lines.append(f"\n=== {current_section.value.upper()} ===")
                current_company = None

            # Company/role header
            if bullet.company and bullet.company != current_company:
                current_company = bullet.company
                role_str = f" | {bullet.role}" if bullet.role else ""
                date_str = f" | {bullet.dates}" if bullet.dates else ""
                output_lines.append(f"\n[{current_company}{role_str}{date_str}]")

            # Bullet with index (LLM must return same count)
            output_lines.append(f"  BULLET_{bullet.original_index}: {bullet.text}")

        return "\n".join(output_lines)

    def to_dict(self) -> dict:
        """Serialize for API response / metadata storage."""
        return {
            "bullet_count": self.bullet_count,
            "sections": self.sections,
            "skills": sorted(self.skills),
            "companies": sorted(self.companies),
            "roles": sorted(self.roles),
            "dates": sorted(self.dates),
            "education": self.education,
            "source_format": self.source_format,
            "warnings": self.parse_warnings,
        }


# ══════════════════════════════════════════════════════════════
# PARSER
# ══════════════════════════════════════════════════════════════


class ResumeParser:
    """
    Deterministic resume parser. No LLM involved.

    Supports DOCX and PDF. Uses regex patterns to identify:
    - Section headers (Experience, Education, Skills, etc.)
    - Bullet points (various bullet characters and numbered lists)
    - Dates (month-year patterns)
    - Company names (text preceding bullet groups)
    - Skills (comma/pipe separated lists in skills sections)

    IMPORTANT: This parser is intentionally conservative. It's better
    to miss a bullet than to hallucinate one. The LLM can only work
    with what the parser finds.
    """

    # ── Section Detection Patterns ────────────────────────
    SECTION_PATTERNS: dict[ResumeSection, re.Pattern] = {
        ResumeSection.EXPERIENCE: re.compile(
            r"(?i)^(professional\s+)?experience|work\s*history|employment(\s*history)?$"
        ),
        ResumeSection.EDUCATION: re.compile(r"(?i)^education(al\s*background)?|academic|degrees?$"),
        ResumeSection.SKILLS: re.compile(
            r"(?i)^(technical\s+)?skills|technologies|tech\s*stack|competenc(ies|e)|proficienc(ies|y)$"
        ),
        ResumeSection.PROJECTS: re.compile(r"(?i)^(personal\s+|side\s+)?projects|portfolio$"),
        ResumeSection.SUMMARY: re.compile(
            r"(?i)^(professional\s+)?summary|objective|profile|about(\s*me)?$"
        ),
        ResumeSection.CERTIFICATIONS: re.compile(r"(?i)^certifications?|licenses?|credentials?$"),
        ResumeSection.AWARDS: re.compile(r"(?i)^awards?|honors?|achievements?|recognition$"),
    }

    # ── Date Patterns ─────────────────────────────────────
    MONTH_PATTERN = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"  # noqa: E501
    DATE_RANGE_PATTERN = re.compile(
        rf"({MONTH_PATTERN}\s*\.?\s*\d{{4}})\s*[-–—to]+\s*({MONTH_PATTERN}\s*\.?\s*\d{{4}}|Present|Current)",
        re.IGNORECASE,
    )
    SINGLE_DATE_PATTERN = re.compile(
        rf"({MONTH_PATTERN}\s*\.?\s*\d{{4}})",
        re.IGNORECASE,
    )

    # ── Bullet Detection ──────────────────────────────────
    BULLET_CHARS = re.compile(r"^[\s]*[•●○◦▪▸►–—\-\*]\s+")
    NUMBERED_BULLET = re.compile(r"^[\s]*\d+[.)]\s+")

    # ── Common Skills (for extraction from skills sections) ─
    # This is a seed list — extend based on your domain
    COMMON_SKILLS = {
        "python",
        "java",
        "javascript",
        "typescript",
        "c++",
        "c#",
        "go",
        "rust",
        "sql",
        "nosql",
        "react",
        "angular",
        "vue",
        "node.js",
        "express",
        "django",
        "flask",
        "fastapi",
        "spring",
        "docker",
        "kubernetes",
        "aws",
        "azure",
        "gcp",
        "terraform",
        "jenkins",
        "git",
        "ci/cd",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "elasticsearch",
        "machine learning",
        "deep learning",
        "nlp",
        "computer vision",
        "pytorch",
        "tensorflow",
        "scikit-learn",
        "pandas",
        "numpy",
        "agile",
        "scrum",
        "jira",
        "confluence",
        "figma",
        "rest",
        "graphql",
        "grpc",
        "microservices",
        "api",
        "linux",
        "bash",
        "powershell",
        "networking",
        "data engineering",
        "etl",
        "spark",
        "airflow",
        "kafka",
        "dbt",
    }

    def parse_docx(self, file_bytes: bytes) -> ResumeAST:
        """
        Parse a DOCX file into a ResumeAST.

        Args:
            file_bytes: Raw bytes of the .docx file

        Returns:
            ResumeAST with all extracted structure
        """
        ast = ResumeAST(source_format="docx")

        try:
            doc = docx.Document(io.BytesIO(file_bytes))
        except Exception as e:
            logger.error(f"Failed to parse DOCX: {e}")
            ast.parse_warnings.append(f"DOCX parse error: {str(e)}")
            return ast

        # Extract all text with paragraph-level structure
        lines: list[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                lines.append(text)

        ast.raw_text = "\n".join(lines)
        return self._parse_lines(lines, ast)

    def parse_pdf(self, file_bytes: bytes) -> ResumeAST:
        """
        Parse a PDF file into a ResumeAST.

        Args:
            file_bytes: Raw bytes of the .pdf file

        Returns:
            ResumeAST with all extracted structure
        """
        ast = ResumeAST(source_format="pdf")

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                all_text: list[str] = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        all_text.append(page_text)
                full_text = "\n".join(all_text)
        except Exception as e:
            logger.error(f"Failed to parse PDF: {e}")
            ast.parse_warnings.append(f"PDF parse error: {str(e)}")
            return ast

        lines = [line.strip() for line in full_text.split("\n") if line.strip()]
        ast.raw_text = full_text
        return self._parse_lines(lines, ast)

    def parse_text(self, text: str) -> ResumeAST:
        """Parse plain text resume (for testing)."""
        ast = ResumeAST(source_format="text", raw_text=text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return self._parse_lines(lines, ast)

    def _parse_lines(self, lines: list[str], ast: ResumeAST) -> ResumeAST:
        """
        Core parsing logic. Processes lines sequentially, tracking context.

        The parser maintains state as it moves through lines:
        - current_section: Which resume section we're in
        - current_company: Which company/school the bullets belong to
        - current_role: Job title within current company
        - current_dates: Date range for current position
        """
        current_section = ResumeSection.GENERAL
        current_company: str | None = None
        current_role: str | None = None
        current_dates: str | None = None
        bullet_index = 0

        for line in lines:
            # ── Try to detect section header ──────────────
            detected_section = self._detect_section(line)
            if detected_section:
                current_section = detected_section
                current_company = None
                current_role = None
                current_dates = None
                continue

            # ── Extract dates from this line ──────────────
            date_match = self.DATE_RANGE_PATTERN.search(line)
            if date_match:
                current_dates = date_match.group(0)
                ast.dates.add(date_match.group(1))  # Start date
                if date_match.group(2).lower() not in ("present", "current"):
                    ast.dates.add(date_match.group(2))  # End date

            # Also find standalone dates
            for single_date in self.SINGLE_DATE_PATTERN.findall(line):
                ast.dates.add(single_date)

            # ── Detect bullet points ──────────────────────
            is_bullet = bool(self.BULLET_CHARS.match(line) or self.NUMBERED_BULLET.match(line))

            if is_bullet:
                # Clean the bullet character prefix
                clean_text = self.BULLET_CHARS.sub("", line)
                clean_text = self.NUMBERED_BULLET.sub("", clean_text).strip()

                if clean_text and len(clean_text) > 10:  # Skip very short "bullets"
                    bullet = ResumeBullet(
                        text=clean_text,
                        section=current_section,
                        company=current_company,
                        role=current_role,
                        dates=current_dates,
                        original_index=bullet_index,
                    )
                    ast.bullets.append(bullet)
                    bullet_index += 1

            # ── Detect company/role lines (non-bullet, non-header) ─
            elif not is_bullet and current_section == ResumeSection.EXPERIENCE:
                # Lines that look like company names (has date, isn't a bullet)
                if date_match and len(line) < 200:
                    # Line before the date is likely company/role
                    pre_date = line[: date_match.start()].strip().rstrip("|,–—-").strip()
                    if pre_date:
                        parts = [p.strip() for p in re.split(r"[|,]", pre_date) if p.strip()]
                        if len(parts) >= 2:
                            current_company = parts[0]
                            current_role = parts[1]
                        elif parts:
                            # Could be company or role — heuristic: if current_company is set,
                            # this is probably a role; otherwise it's a company
                            if current_company is None:
                                current_company = parts[0]
                            else:
                                current_role = parts[0]

                        if current_company:
                            ast.companies.add(current_company)
                        if current_role:
                            ast.roles.add(current_role)

            # ── Extract skills from skills section ────────
            if current_section == ResumeSection.SKILLS:
                self._extract_skills(line, ast)

        # ── Post-processing ───────────────────────────────
        if ast.bullet_count == 0:
            ast.parse_warnings.append(
                "No bullet points detected. The resume may use an unusual format."
            )

        logger.info(
            f"Parsed resume: {ast.bullet_count} bullets, "
            f"{len(ast.skills)} skills, {len(ast.companies)} companies, "
            f"{len(ast.dates)} dates, {len(ast.parse_warnings)} warnings"
        )

        return ast

    def _detect_section(self, line: str) -> ResumeSection | None:
        """Check if a line is a section header."""
        # Clean the line for matching
        cleaned = re.sub(r"[:\-–—|]", "", line).strip()

        # Skip if too long to be a header (headers are usually short)
        if len(cleaned) > 60:
            return None

        for section, pattern in self.SECTION_PATTERNS.items():
            if pattern.match(cleaned):
                return section

        return None

    def _extract_skills(self, line: str, ast: ResumeAST) -> None:
        """Extract skill keywords from a skills section line."""
        # Split by common delimiters
        tokens = re.split(r"[,|•●·/]", line.lower())

        for token in tokens:
            cleaned = token.strip().strip("-–—").strip()
            if not cleaned or len(cleaned) < 2:
                continue

            # Check against known skills
            if cleaned in self.COMMON_SKILLS:
                ast.skills.add(cleaned)
            else:
                # Also check for partial matches (e.g., "Python 3.12" → "python")
                for skill in self.COMMON_SKILLS:
                    if skill in cleaned and len(skill) >= 3:
                        ast.skills.add(skill)
                        break
