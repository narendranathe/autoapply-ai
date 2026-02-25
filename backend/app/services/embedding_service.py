"""
Embedding Service — three-tier architecture for semantic resume retrieval.

Tier 1 (Free):   TF-IDF cosine similarity via sklearn — always computed, no API needed
Tier 2 (Paid):   Dense embeddings via OpenAI / Anthropic / Kimi BYOK key
Tier 3 (Local):  Ollama nomic-embed-text (768-dim) — best local doc retrieval model

TF-IDF vectors are always stored. Dense vectors are computed additionally
when an embedding-capable provider is configured.
"""

import math
from collections import Counter

import httpx
from loguru import logger

# ── TF-IDF (Free Tier) ────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    import re

    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = text.split()
    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "and",
        "or",
        "but",
        "not",
        "this",
        "that",
        "we",
        "you",
        "they",
        "our",
        "your",
        "their",
        "i",
        "my",
        "as",
        "it",
        "its",
    }
    return [t for t in tokens if t not in stop_words and len(t) > 1]


def build_tfidf_vector(text: str, corpus_idf: dict[str, float] | None = None) -> dict[str, float]:
    """
    Build a TF-IDF vector for a document.

    Args:
        text: Document text
        corpus_idf: Pre-computed IDF scores from a corpus. If None, only TF is used.

    Returns:
        dict mapping term → tf-idf weight
    """
    tokens = _tokenize(text)
    if not tokens:
        return {}

    tf: dict[str, float] = {}
    counts = Counter(tokens)
    max_count = max(counts.values())
    for term, count in counts.items():
        tf[term] = count / max_count  # normalised TF

    vector = {term: tf[term] * corpus_idf.get(term, 1.0) for term in tf} if corpus_idf else tf
    return vector


def build_corpus_idf(documents: list[str]) -> dict[str, float]:
    """
    Compute IDF scores across a corpus of documents.
    Used when the user has multiple resumes — fit IDF on all of them.
    """
    N = len(documents)
    if N == 0:
        return {}

    df: Counter = Counter()
    for doc in documents:
        terms = set(_tokenize(doc))
        for term in terms:
            df[term] += 1

    idf = {}
    for term, count in df.items():
        idf[term] = math.log((N + 1) / (count + 1)) + 1  # smoothed IDF

    return idf


def cosine_similarity_tfidf(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors."""
    if not vec_a or not vec_b:
        return 0.0

    common = set(vec_a.keys()) & set(vec_b.keys())
    dot = sum(vec_a[t] * vec_b[t] for t in common)

    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ── Dense Embeddings (Paid / Local Tier) ──────────────────────────────────


async def generate_embedding_openai(text: str, api_key: str) -> list[float]:
    """OpenAI text-embedding-3-small (1536-dim)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "text-embedding-3-small", "input": text[:8000]},
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]


async def generate_embedding_anthropic(text: str, api_key: str) -> list[float]:
    """
    Anthropic does not yet expose a public embeddings API endpoint.
    Falls back to OpenAI-compatible embedding if Anthropic releases one;
    currently raises NotImplementedError so the caller tries the next tier.
    """
    raise NotImplementedError("Anthropic embeddings API not yet available — use OpenAI or Ollama")


async def generate_embedding_kimi(text: str, api_key: str) -> list[float]:
    """Kimi (Moonshot) embeddings via OpenAI-compatible endpoint."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.moonshot.cn/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "moonshot-v1-embedding", "input": text[:8000]},
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]


async def generate_embedding_ollama(text: str, model: str = "nomic-embed-text") -> list[float]:
    """
    Ollama local embeddings (768-dim with nomic-embed-text).
    Requires Ollama running at http://localhost:11434.
    Recommended local model: nomic-embed-text
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "http://localhost:11434/api/embeddings",
            json={"model": model, "prompt": text[:8000]},
        )
        response.raise_for_status()
        return response.json()["embedding"]


async def generate_dense_embedding(
    text: str,
    provider: str,
    api_key: str = "",
    ollama_model: str = "nomic-embed-text",
) -> tuple[list[float], str]:
    """
    Generate a dense embedding using the configured provider.

    Returns:
        (embedding_vector, model_name_used)

    Falls through provider chain: openai → kimi → ollama → empty (TF-IDF only)
    """
    try:
        if provider == "openai" and api_key:
            vec = await generate_embedding_openai(text, api_key)
            return vec, "text-embedding-3-small"

        if provider == "kimi" and api_key:
            vec = await generate_embedding_kimi(text, api_key)
            return vec, "moonshot-v1-embedding"

        if provider == "ollama":
            vec = await generate_embedding_ollama(text, ollama_model)
            return vec, ollama_model

    except Exception as e:
        logger.warning(f"Dense embedding failed ({provider}): {e} — falling back to TF-IDF only")

    return [], ""


def cosine_similarity_dense(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine similarity between two dense float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))

    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def similarity(
    vec_a_tfidf: dict[str, float],
    vec_b_tfidf: dict[str, float],
    vec_a_dense: list[float] | None = None,
    vec_b_dense: list[float] | None = None,
) -> float:
    """
    Compute the best available similarity score.

    If both dense vectors exist → use cosine similarity on dense (more accurate).
    Otherwise → fall back to TF-IDF cosine similarity.
    """
    if vec_a_dense and vec_b_dense:
        return cosine_similarity_dense(vec_a_dense, vec_b_dense)
    return cosine_similarity_tfidf(vec_a_tfidf, vec_b_tfidf)
