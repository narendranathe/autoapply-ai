"""
Tests for utility functions.
"""

from app.utils.hashing import hash_jd, hash_pii


class TestHashPII:
    def test_consistent_hash(self):
        assert hash_pii("test@email.com") == hash_pii("test@email.com")

    def test_different_inputs_different_hashes(self):
        assert hash_pii("alice@test.com") != hash_pii("bob@test.com")

    def test_hash_length(self):
        result = hash_pii("anything")
        assert len(result) == 64


class TestHashJD:
    def test_whitespace_normalization(self):
        jd1 = "Software   Engineer at  Google"
        jd2 = "Software Engineer at Google"
        assert hash_jd(jd1) == hash_jd(jd2)

    def test_case_insensitive(self):
        assert hash_jd("Software Engineer") == hash_jd("software engineer")
