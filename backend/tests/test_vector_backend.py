"""
Tests for VectorBackend abstraction (pgvector | Pinecone).

These tests are unit-level — no database or network required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import app.services.vector_backend as vb_module
from app.services.vector_backend import PgVectorBackend, VectorBackend, get_vector_backend

# ── Helpers ────────────────────────────────────────────────────────────────


def _reset_singleton() -> None:
    """Reset the module-level singleton so factory tests are independent."""
    vb_module._backend_singleton = None


# ── Test 1: pgvector backend returns PgVectorBackend ──────────────────────


def test_pgvector_backend_returns_pgvector_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """When VECTOR_BACKEND=pgvector, get_vector_backend() returns a PgVectorBackend."""
    _reset_singleton()

    monkeypatch.setattr("app.config.settings.VECTOR_BACKEND", "pgvector")

    backend = get_vector_backend()

    assert isinstance(backend, PgVectorBackend)
    assert isinstance(backend, VectorBackend)

    _reset_singleton()


# ── Test 2: Pinecone backend raises RuntimeError when package missing ──────


def test_pinecone_backend_requires_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When VECTOR_BACKEND=pinecone and pinecone-client is not installed,
    get_vector_backend() raises RuntimeError with a helpful install message.
    """
    _reset_singleton()

    monkeypatch.setattr("app.config.settings.VECTOR_BACKEND", "pinecone")
    # Simulate pinecone not being installed
    monkeypatch.setattr(vb_module, "HAS_PINECONE", False)

    with pytest.raises(RuntimeError, match="pinecone-client not installed"):
        get_vector_backend()

    _reset_singleton()


# ── Test 3: singleton — same instance returned on second call ──────────────


def test_pgvector_backend_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling get_vector_backend() twice returns the exact same object."""
    _reset_singleton()

    monkeypatch.setattr("app.config.settings.VECTOR_BACKEND", "pgvector")

    first = get_vector_backend()
    second = get_vector_backend()

    assert first is second

    _reset_singleton()


# ── Test 4: PineconeBackend.query() passes correct args to index ───────────


def test_pinecone_backend_query_delegates_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    PineconeBackend.query() should call index.query() with vector, top_k,
    filter, and include_metadata=True, then return formatted results.
    """
    _reset_singleton()

    # Build a mock Pinecone module
    mock_pinecone_module = MagicMock()
    mock_index = MagicMock()

    # Simulate a Pinecone query response
    mock_match = MagicMock()
    mock_match.id = "chunk-abc"
    mock_match.score = 0.87
    mock_match.metadata = {"text": "senior software engineer", "user_id": "u1"}
    mock_response = MagicMock()
    mock_response.matches = [mock_match]
    mock_index.query.return_value = mock_response

    mock_pc_instance = MagicMock()
    mock_pc_instance.Index.return_value = mock_index
    mock_pinecone_module.Pinecone.return_value = mock_pc_instance

    # Patch the module-level pinecone reference and HAS_PINECONE flag
    monkeypatch.setattr(vb_module, "pinecone", mock_pinecone_module, raising=False)
    monkeypatch.setattr(vb_module, "HAS_PINECONE", True)
    monkeypatch.setattr("app.config.settings.PINECONE_API_KEY", "test-key-123")
    monkeypatch.setattr("app.config.settings.PINECONE_INDEX_NAME", "autoapply-answers")

    from app.services.vector_backend import PineconeBackend

    backend = PineconeBackend()

    query_vector = [0.1, 0.2, 0.3]
    filter_dict = {"user_id": "u1"}
    results = backend.query(vector=query_vector, top_k=3, filter=filter_dict)

    # Verify index.query called with correct args
    mock_index.query.assert_called_once_with(
        vector=query_vector,
        top_k=3,
        filter=filter_dict,
        include_metadata=True,
    )

    # Verify result format
    assert len(results) == 1
    assert results[0]["id"] == "chunk-abc"
    assert results[0]["score"] == pytest.approx(0.87)
    assert results[0]["metadata"]["text"] == "senior software engineer"

    _reset_singleton()


# ── Test 5: PineconeBackend.upsert() passes correct args ──────────────────


def test_pinecone_backend_upsert_delegates_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    PineconeBackend.upsert() should call index.upsert() with a correctly
    structured vectors list.
    """
    _reset_singleton()

    mock_pinecone_module = MagicMock()
    mock_index = MagicMock()
    mock_pc_instance = MagicMock()
    mock_pc_instance.Index.return_value = mock_index
    mock_pinecone_module.Pinecone.return_value = mock_pc_instance

    monkeypatch.setattr(vb_module, "pinecone", mock_pinecone_module, raising=False)
    monkeypatch.setattr(vb_module, "HAS_PINECONE", True)
    monkeypatch.setattr("app.config.settings.PINECONE_API_KEY", "test-key-123")
    monkeypatch.setattr("app.config.settings.PINECONE_INDEX_NAME", "autoapply-answers")

    from app.services.vector_backend import PineconeBackend

    backend = PineconeBackend()
    vec = [0.5, 0.6, 0.7]
    meta = {"chunk_text": "hello world", "user_id": "u2"}

    backend.upsert(id="chunk-42", vector=vec, metadata=meta)

    mock_index.upsert.assert_called_once_with(
        vectors=[{"id": "chunk-42", "values": vec, "metadata": meta}]
    )

    _reset_singleton()


# ── Test 6: PgVectorBackend.query() returns empty list ────────────────────


def test_pgvector_backend_query_returns_empty_list() -> None:
    """
    PgVectorBackend.query() returns [] — callers use rag_service.retrieve_chunks()
    for the full async DB-backed pipeline.
    """
    backend = PgVectorBackend()
    result = backend.query(vector=[0.1, 0.2, 0.3], top_k=5)
    assert result == []


# ── Test 7: unknown backend raises ValueError ──────────────────────────────


def test_unknown_backend_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised VECTOR_BACKEND value raises ValueError."""
    _reset_singleton()

    monkeypatch.setattr("app.config.settings.VECTOR_BACKEND", "weaviate")

    with pytest.raises(ValueError, match="Unknown VECTOR_BACKEND"):
        get_vector_backend()

    _reset_singleton()
