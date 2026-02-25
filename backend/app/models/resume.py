"""
Resume Vault Models — stores uploaded resumes + usage history.

Two tables:
  resumes      — each uploaded or generated resume file
  resume_usages — which resume was used for which company/application
"""

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Resume(Base, TimestampMixin):
    """
    A single resume stored in the vault.

    Populated either by:
    - User uploading an existing file (PDF/DOCX/TEX)
    - System generating a new tailored resume via LLM

    Personal content (name, contact, work bullets) lives here only as
    extracted text for embedding/retrieval. The canonical source of truth
    for personal data is the user's private GitHub repo (resume-vault/private/).
    """

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- File metadata ---
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf | docx | tex | md

    # --- Content ---
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    latex_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Parsed structure (from resume_parser) ---
    bullet_count: Mapped[int] = mapped_column(Integer, default=0)
    skills_detected: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    companies_found: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sections_found: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # --- Embedding vectors ---
    # Free tier: TF-IDF sparse vector serialised as {term: weight} dict
    tfidf_vector: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Paid/local tier: dense float array (OpenAI 1536-dim, Ollama 768-dim, etc.)
    embedding_vector: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # e.g. "nomic-embed-text", "text-embedding-3-small"

    # --- Version / identity ---
    # Internal git tag name: Narendranath_Google_DE or Narendranath_Google_DE_JOB123
    version_tag: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # Recruiter-facing filename (always FirstName.pdf at download time — stored for reference)
    recruiter_filename: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_base_template: Mapped[bool] = mapped_column(Boolean, default=False)
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False)  # True = LLM-produced

    # --- GitHub storage ---
    # Path inside resume-vault repo, e.g. versions/Narendranath_Google_DE.tex
    github_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # --- ATS metadata (at time of generation) ---
    ats_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_company: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    target_role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_jd_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Relationships ---
    usages: Mapped[list["ResumeUsage"]] = relationship(
        "ResumeUsage", back_populates="resume", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_resumes_user_company", "user_id", "target_company"),
        Index("ix_resumes_version_tag", "version_tag"),
    )

    def __repr__(self) -> str:
        return f"<Resume {self.version_tag or self.filename} user={self.user_id}>"


class ResumeUsage(Base, TimestampMixin):
    """
    Tracks every time a resume was submitted for a job application.

    One Resume can have many ResumeUsages (applied to same role multiple times,
    or used the same base for different companies with slight tweaks).
    """

    __tablename__ = "resume_usages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable — not every usage is tracked to a formal application record
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Job context ---
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    role_title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # ATS job ID (for JobID suffix in git tag)
    job_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # --- Outcome tracking ---
    ats_score_at_use: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(50), default="unknown"
    )  # applied | phone_screen | interview | offer | rejected | unknown

    # --- Git reference ---
    git_tag: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )  # e.g. Narendranath_Google_DE_JOB123

    # --- Relationships ---
    resume: Mapped["Resume"] = relationship("Resume", back_populates="usages")

    __table_args__ = (
        Index("ix_resume_usages_company", "company_name"),
        Index("ix_resume_usages_user_company", "user_id", "company_name"),
    )

    def __repr__(self) -> str:
        return f"<ResumeUsage {self.company_name} / {self.role_title} outcome={self.outcome}>"


class ApplicationAnswer(Base, TimestampMixin):
    """
    Stores LLM-generated and user-accepted answers to open-ended
    application questions.

    Used for:
    1. Auto-filling the same question at the same company in future
    2. Recruiter callback reference (what did I say in the application?)
    3. Answer quality improvement over time

    question_hash: SHA-256 of the normalised question text — used for
    deduplication across applications at the same company.
    """

    __tablename__ = "application_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Question identity ---
    question_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # SHA-256 of normalised question
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # why_company | why_hire | about_yourself | strength | weakness | challenge
    #   | leadership | conflict | motivation | five_years | impact | fit | sponsorship | custom

    # --- Answer ---
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    was_default: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # True = user said "enter default"
    llm_provider_used: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Context ---
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    role_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_answers_user_company", "user_id", "company_name"),
        Index("ix_answers_question_hash", "question_hash"),
    )

    def __repr__(self) -> str:
        return (
            f"<ApplicationAnswer {self.question_category} @ {self.company_name} "
            f"words={self.word_count}>"
        )
