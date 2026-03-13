"""
RAG Service — Retrieval Augmented Generation for resume/work-history grounding.

Pipeline:
  1. Upload:  parse markdown → split into semantic chunks → build TF-IDF vectors
              → optionally generate dense embeddings → store in document_chunks
  2. Retrieve: given a query, return top-k chunks by cosine similarity
  3. Format:  build a compact context block for LLM prompts

Chunking strategy:
  - Split on ## headers (semantic sections)
  - If a section > MAX_CHUNK_TOKENS tokens, further split into overlapping paragraphs
  - Preserve section_header on every chunk for context

Free tier: TF-IDF cosine similarity (no API needed)
Paid tier: dense cosine similarity (OpenAI text-embedding-3-small or Ollama nomic-embed-text)
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_chunk import DocumentChunk
from app.services.embedding_service import (
    build_corpus_idf,
    build_tfidf_vector,
    cosine_similarity_dense,
    cosine_similarity_tfidf,
    generate_dense_embedding,
)

# ── Constants ──────────────────────────────────────────────────────────────

MAX_CHUNK_TOKENS = 400  # ~300 words — keeps chunk small enough for prompts
CHUNK_OVERLAP_LINES = 3  # lines of overlap between paragraph sub-chunks
TOP_K_DEFAULT = 6  # default number of chunks to retrieve


# ── Chunking ───────────────────────────────────────────────────────────────


@dataclass
class RawChunk:
    section_header: str
    chunk_text: str
    chunk_index: int


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 characters."""
    return max(1, len(text) // 4)


def _split_into_paragraphs(text: str, overlap: int = CHUNK_OVERLAP_LINES) -> list[str]:
    """Split text into overlapping paragraph windows."""
    lines = text.split("\n")
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return []

    chunks: list[str] = []
    window: list[str] = []
    token_count = 0

    for line in non_empty:
        line_tokens = _estimate_tokens(line)
        if token_count + line_tokens > MAX_CHUNK_TOKENS and window:
            chunks.append("\n".join(window))
            # Keep last `overlap` lines for context continuity
            window = window[-overlap:] if len(window) > overlap else window[:]
            token_count = sum(_estimate_tokens(ln) for ln in window)
        window.append(line)
        token_count += line_tokens

    if window:
        chunks.append("\n".join(window))

    return chunks


def chunk_markdown(markdown_text: str) -> list[RawChunk]:
    """
    Split a markdown document into semantic chunks.

    Strategy:
      1. Split on ## level-2 headers (major sections)
      2. Sub-split each section if it exceeds MAX_CHUNK_TOKENS
    """
    if not markdown_text.strip():
        return []

    # Split on ## or ### headers
    sections = re.split(r"\n(?=#{1,3} )", markdown_text)

    raw_chunks: list[RawChunk] = []
    chunk_index = 0

    for section in sections:
        if not section.strip():
            continue

        # Extract header line
        lines = section.strip().split("\n")
        header = ""
        body_start = 0

        if lines[0].startswith("#"):
            header = lines[0].lstrip("#").strip()
            body_start = 1

        body = "\n".join(lines[body_start:]).strip()
        if not body:
            # Section with only a header and no body — include header as chunk
            body = header

        # Sub-chunk if section is too long
        if _estimate_tokens(body) <= MAX_CHUNK_TOKENS:
            raw_chunks.append(
                RawChunk(
                    section_header=header,
                    chunk_text=f"## {header}\n\n{body}" if header else body,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
        else:
            sub_chunks = _split_into_paragraphs(body)
            for sub in sub_chunks:
                raw_chunks.append(
                    RawChunk(
                        section_header=header,
                        chunk_text=f"## {header}\n\n{sub}" if header else sub,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1

    return raw_chunks


# ── Storage ────────────────────────────────────────────────────────────────


async def upload_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    doc_type: str,
    source_filename: str,
    markdown_text: str,
    embedding_provider: str = "",
    embedding_api_key: str = "",
) -> list[DocumentChunk]:
    """
    Parse, chunk, embed, and store a markdown document.

    Replaces all existing chunks for this user + source_filename.

    Args:
        doc_type: "resume" | "work_history" | "cover_letter_sample" | "other"
        source_filename: e.g. "resume.md" or "work_history.md"
        markdown_text: full markdown content
        embedding_provider: "openai" | "kimi" | "ollama" | "" (TF-IDF only)
        embedding_api_key: API key for the embedding provider

    Returns:
        List of stored DocumentChunk rows
    """
    # Remove existing chunks for this doc
    await db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.user_id == user_id,
            DocumentChunk.source_filename == source_filename,
        )
    )

    raw_chunks = chunk_markdown(markdown_text)
    if not raw_chunks:
        logger.warning(f"No chunks produced from {source_filename} for user {user_id}")
        return []

    # Build corpus IDF from all chunks for better TF-IDF weights
    corpus_texts = [rc.chunk_text for rc in raw_chunks]
    corpus_idf = build_corpus_idf(corpus_texts)

    stored: list[DocumentChunk] = []

    for rc in raw_chunks:
        tfidf_vec = build_tfidf_vector(rc.chunk_text, corpus_idf)
        token_count = _estimate_tokens(rc.chunk_text)

        # Optional dense embedding
        dense_vec: list[float] = []
        model_used = ""
        if embedding_provider:
            try:
                dense_vec, model_used = await generate_dense_embedding(
                    rc.chunk_text,
                    provider=embedding_provider,
                    api_key=embedding_api_key,
                )
            except Exception as e:
                logger.warning(f"Dense embedding skipped for chunk {rc.chunk_index}: {e}")

        chunk = DocumentChunk(
            user_id=user_id,
            doc_type=doc_type,
            source_filename=source_filename,
            chunk_index=rc.chunk_index,
            section_header=rc.section_header,
            chunk_text=rc.chunk_text,
            token_count=token_count,
            tfidf_vector=tfidf_vec if tfidf_vec else None,
            dense_embedding=dense_vec if dense_vec else None,
            embedding_model=model_used,
        )
        db.add(chunk)
        stored.append(chunk)

    await db.flush()
    logger.info(f"Stored {len(stored)} chunks for {source_filename} (user={user_id})")
    return stored


# ── Retrieval ──────────────────────────────────────────────────────────────


@dataclass
class RetrievedChunk:
    chunk_text: str
    section_header: str
    doc_type: str
    source_filename: str
    chunk_index: int
    score: float


async def retrieve_chunks(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    doc_types: list[str] | None = None,
    top_k: int = TOP_K_DEFAULT,
    query_embedding: list[float] | None = None,
) -> list[RetrievedChunk]:
    """
    Retrieve top-k most relevant chunks for a query using cosine similarity.

    Prefers dense similarity if query_embedding provided + chunks have dense_embedding.
    Falls back to TF-IDF similarity otherwise.

    Args:
        doc_types: filter by doc_type (None = all types)
        query_embedding: pre-computed dense embedding of the query (optional)
    """
    stmt = select(DocumentChunk).where(DocumentChunk.user_id == user_id)
    if doc_types:
        stmt = stmt.where(DocumentChunk.doc_type.in_(doc_types))

    result = await db.execute(stmt)
    all_chunks: list[DocumentChunk] = list(result.scalars().all())

    if not all_chunks:
        return []

    query_tfidf = build_tfidf_vector(query)
    scored: list[tuple[float, DocumentChunk]] = []

    for chunk in all_chunks:
        # Dense similarity if available
        if query_embedding and chunk.dense_embedding:
            score = cosine_similarity_dense(query_embedding, chunk.dense_embedding)
        elif chunk.tfidf_vector:
            score = cosine_similarity_tfidf(query_tfidf, chunk.tfidf_vector)
        else:
            # Build TF-IDF on the fly
            chunk_tfidf = build_tfidf_vector(chunk.chunk_text)
            score = cosine_similarity_tfidf(query_tfidf, chunk_tfidf)

        scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    return [
        RetrievedChunk(
            chunk_text=c.chunk_text,
            section_header=c.section_header,
            doc_type=c.doc_type,
            source_filename=c.source_filename,
            chunk_index=c.chunk_index,
            score=round(score, 4),
        )
        for score, c in top
        if score > 0.0  # exclude zero-similarity chunks
    ]


# ── Context formatting ─────────────────────────────────────────────────────


def format_rag_context(
    chunks: list[RetrievedChunk],
    max_tokens: int = 2000,
    label: str = "RELEVANT BACKGROUND",
) -> str:
    """
    Format retrieved chunks into a compact context block for LLM prompts.

    Chunks are ordered by chunk_index within each doc_type to preserve
    narrative flow. Stops adding chunks when max_tokens is reached.
    """
    if not chunks:
        return ""

    # Sort by (doc_type, chunk_index) for narrative order
    ordered = sorted(chunks, key=lambda c: (c.doc_type, c.chunk_index))

    lines: list[str] = [f"--- {label} (from your uploaded documents) ---"]
    token_budget = max_tokens

    for chunk in ordered:
        chunk_tokens = _estimate_tokens(chunk.chunk_text)
        if token_budget <= 0:
            break
        if chunk_tokens > token_budget:
            # Truncate to fit budget
            approx_chars = token_budget * 4
            truncated = chunk.chunk_text[:approx_chars] + "..."
            lines.append(f"\n[{chunk.source_filename} — {chunk.section_header}]\n{truncated}")
            break
        lines.append(f"\n[{chunk.source_filename} — {chunk.section_header}]\n{chunk.chunk_text}")
        token_budget -= chunk_tokens

    lines.append("\n--- END BACKGROUND ---")
    return "\n".join(lines)


async def get_rag_context_for_query(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    doc_types: list[str] | None = None,
    top_k: int = TOP_K_DEFAULT,
    max_context_tokens: int = 2000,
    label: str = "RELEVANT BACKGROUND",
) -> str:
    """
    One-shot helper: retrieve + format a RAG context block.
    Returns empty string if no documents are uploaded.
    """
    chunks = await retrieve_chunks(
        db=db,
        user_id=user_id,
        query=query,
        doc_types=doc_types,
        top_k=top_k,
    )
    return format_rag_context(chunks, max_tokens=max_context_tokens, label=label)


async def list_user_documents(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict]:
    """
    Return a summary of uploaded documents for a user.
    Returns one entry per source_filename with chunk count + doc_type.
    """
    stmt = select(DocumentChunk).where(DocumentChunk.user_id == user_id)
    result = await db.execute(stmt)
    all_chunks: list[DocumentChunk] = list(result.scalars().all())

    seen: dict[str, dict] = {}
    for chunk in all_chunks:
        key = chunk.source_filename
        if key not in seen:
            seen[key] = {
                "source_filename": chunk.source_filename,
                "doc_type": chunk.doc_type,
                "chunk_count": 0,
                "has_dense_embeddings": False,
                "created_at": chunk.created_at.isoformat(),
            }
        seen[key]["chunk_count"] += 1
        if chunk.dense_embedding:
            seen[key]["has_dense_embeddings"] = True

    return list(seen.values())
