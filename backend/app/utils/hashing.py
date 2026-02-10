"""
Hashing utilities for privacy-preserving logging.
"""

import hashlib


def hash_pii(value: str) -> str:
    """Create a one-way SHA-256 hash of a PII value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_jd(job_description: str) -> str:
    """Create a content hash of a job description for deduplication."""
    normalized = " ".join(job_description.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
