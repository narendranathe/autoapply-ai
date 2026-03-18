"""
Vault sub-module: RAG document upload, listing, deletion, and retrieval.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.services.rag_service import (
    list_user_documents,
    upload_document,
)

router = APIRouter()


# ── RAG Document Upload + Retrieval ────────────────────────────────────────


@router.post("/documents/upload-md", status_code=status.HTTP_201_CREATED)
async def upload_markdown_document(
    content: str = Form(..., description="Full markdown text of the document"),
    doc_type: str = Form(
        ..., description="Document type: resume | work_history | cover_letter_sample | other"
    ),
    source_filename: str = Form(..., description='e.g. "resume.md" or "work_history.md"'),
    embedding_provider: str = Form("", description="openai | kimi | ollama | (blank=TF-IDF only)"),
    embedding_api_key: str = Form("", description="API key for the embedding provider"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Upload a markdown document (resume.md / work-history.md) to the RAG pipeline.

    Chunks the document, builds TF-IDF vectors, and optionally generates dense
    embeddings. Replaces any previously uploaded document with the same filename.

    After upload, this document's content will automatically ground:
    - Cover letter generation (POST /vault/generate/cover-letter)
    - Answer generation (POST /vault/generate/answers)
    - Summary/bullets generation
    """
    if doc_type not in {"resume", "work_history", "cover_letter_sample", "other"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="doc_type must be one of: resume, work_history, cover_letter_sample, other",
        )

    if not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document content is empty",
        )

    chunks = await upload_document(
        db=db,
        user_id=user.id,
        doc_type=doc_type,
        source_filename=source_filename,
        markdown_text=content,
        embedding_provider=embedding_provider,
        embedding_api_key=embedding_api_key,
    )
    await db.commit()

    has_dense = any(c.dense_embedding for c in chunks)
    return {
        "source_filename": source_filename,
        "doc_type": doc_type,
        "chunks_stored": len(chunks),
        "has_dense_embeddings": has_dense,
        "embedding_model": chunks[0].embedding_model if has_dense and chunks else "",
        "message": f"Uploaded and chunked {source_filename} into {len(chunks)} RAG segments",
    }


@router.get("/documents")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all uploaded RAG documents for the current user."""
    docs = await list_user_documents(db=db, user_id=user.id)
    return {"documents": docs, "total": len(docs)}


@router.delete("/documents/{source_filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    source_filename: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete all chunks for a specific uploaded document."""
    from sqlalchemy import delete as sql_delete

    await db.execute(
        sql_delete(DocumentChunk).where(
            DocumentChunk.user_id == user.id,
            DocumentChunk.source_filename == source_filename,
        )
    )
    await db.commit()


@router.post("/documents/retrieve")
async def retrieve_rag_chunks(
    query: str = Form(..., description="Query text to retrieve relevant chunks"),
    doc_types: str = Form("", description="Comma-separated doc_types to filter (blank=all)"),
    top_k: int = Form(6, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Debug endpoint: retrieve top-k RAG chunks for a query.
    Useful for testing retrieval quality before using in generation.
    """
    from app.services.rag_service import retrieve_chunks

    doc_type_list = [d.strip() for d in doc_types.split(",") if d.strip()] or None

    chunks = await retrieve_chunks(
        db=db,
        user_id=user.id,
        query=query,
        doc_types=doc_type_list,
        top_k=top_k,
    )

    return {
        "query": query,
        "doc_types": doc_type_list,
        "results": [
            {
                "source_filename": c.source_filename,
                "section_header": c.section_header,
                "doc_type": c.doc_type,
                "score": c.score,
                "chunk_text": c.chunk_text[:500],  # truncate for response size
            }
            for c in chunks
        ],
    }
