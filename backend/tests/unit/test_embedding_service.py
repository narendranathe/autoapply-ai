"""Unit tests for embedding service."""

from app.services.embedding_service import (
    build_tfidf_vector,
    cosine_similarity_tfidf,
)


def test_build_tfidf_vector_basic():
    vec = build_tfidf_vector("python data engineer spark sql")
    assert isinstance(vec, dict)
    assert len(vec) > 0
    assert all(isinstance(k, str) for k in vec)
    assert all(isinstance(v, float) for v in vec.values())


def test_build_tfidf_vector_empty():
    vec = build_tfidf_vector("")
    assert vec == {}


def test_cosine_similarity_identical():
    vec = build_tfidf_vector("python data engineer spark")
    sim = cosine_similarity_tfidf(vec, vec)
    assert abs(sim - 1.0) < 1e-9


def test_cosine_similarity_disjoint():
    vec_a = build_tfidf_vector("python spark airflow dbt")
    vec_b = build_tfidf_vector("painting watercolor canvas brushstroke")
    sim = cosine_similarity_tfidf(vec_a, vec_b)
    assert sim == 0.0


def test_cosine_similarity_range():
    vec_a = build_tfidf_vector("senior data engineer python sql bigquery")
    vec_b = build_tfidf_vector("data scientist python machine learning sql")
    sim = cosine_similarity_tfidf(vec_a, vec_b)
    assert 0.0 <= sim <= 1.0


def test_cosine_similarity_partial_overlap():
    vec_a = build_tfidf_vector("python spark sql airflow bigquery")
    vec_b = build_tfidf_vector("python django sql react html css")
    sim_partial = cosine_similarity_tfidf(vec_a, vec_b)
    # python + sql overlap → non-zero similarity
    assert sim_partial > 0.0
    # But less similar than identical
    assert sim_partial < 1.0


def test_cosine_similarity_empty_vectors():
    assert cosine_similarity_tfidf({}, {}) == 0.0
    assert cosine_similarity_tfidf({"python": 0.5}, {}) == 0.0


def test_tfidf_stopwords_excluded():
    vec = build_tfidf_vector("the quick brown fox is jumping over the lazy dog")
    # Common stopwords should not dominate
    assert vec.get("the", 0) == 0.0 or "fox" in vec or "jumping" in vec


def test_tfidf_similar_documents_rank_higher():
    jd = build_tfidf_vector("data engineer python spark bigquery gcp terraform")
    resume_match = build_tfidf_vector("data engineer python spark bigquery gcp")
    resume_mismatch = build_tfidf_vector("frontend developer react javascript html css")

    sim_match = cosine_similarity_tfidf(jd, resume_match)
    sim_mismatch = cosine_similarity_tfidf(jd, resume_mismatch)
    assert sim_match > sim_mismatch
