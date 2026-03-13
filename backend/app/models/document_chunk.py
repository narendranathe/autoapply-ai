"""
DocumentChunk — stores chunked markdown documents (resume.md / work-history.md)
for RAG-grounded answer and cover letter generation.

Each chunk is a paragraph/section of the user's markdown document with:
- raw chunk_text for LLM prompting
- tfidf_vector (JSON) for free-tier cosine similarity
- dense_embedding (JSON list[float]) for paid/local dense retrieval
"""

import uuid

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DocumentChunk(Base, TimestampMixin):
    """
    A single chunk of an uploaded markdown document.

    doc_type: "resume" | "work_history" | "cover_letter_sample" | "other"
    source_filename: original filename (e.g. "resume.md")
    chunk_index: 0-based position in document (for ordering context)
    section_header: nearest ## heading above this chunk (empty string if none)
    chunk_text: the raw text of this chunk (used in LLM prompts)
    tfidf_vector: TF-IDF sparse vector (JSON dict str→float) for free similarity
    dense_embedding: dense float vector from OpenAI/Ollama (JSON list[float])
    embedding_model: which model produced the dense embedding (or empty)
    token_count: estimated token count for context budget management
    """

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    # ── Source info ──────────────────────────────────────────────────────────
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_header: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    # ── Content ──────────────────────────────────────────────────────────────
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Vectors ──────────────────────────────────────────────────────────────
    tfidf_vector: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dense_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    __table_args__ = (
        Index("ix_document_chunks_user_doc_type", "user_id", "doc_type"),
        Index("ix_document_chunks_user_filename", "user_id", "source_filename"),
    )
