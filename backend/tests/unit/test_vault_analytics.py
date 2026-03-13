"""
Unit tests for vault analytics helpers and bulk-save validation logic.
Tests don't require DB or LLM connections.
"""

import sys
import types

# ── Stub heavy dependencies ──────────────────────────────────────────────────
for mod_name in [
    "loguru",
    "anthropic",
    "openai",
    "groq",
    "google",
    "google.generativeai",
    "google.ai",
    "google.ai.generativelanguage_v1beta",
    "google.generativeai.types",
    "google.generativeai.generative_models",
    "numpy",
    "sklearn",
    "sklearn.metrics",
    "sklearn.metrics.pairwise",
    "sklearn.feature_extraction",
    "sklearn.feature_extraction.text",
    "passlib",
    "passlib.context",
    "jose",
    "jose.jwt",
]:
    if mod_name not in sys.modules:
        m = types.ModuleType(mod_name)
        sys.modules[mod_name] = m

import loguru as _loguru_mod  # noqa: E402

_loguru_mod.logger = types.SimpleNamespace(  # type: ignore
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
    debug=lambda *a, **k: None,
)

from app.routers.vault import _compute_reward, _levenshtein  # noqa: E402


class TestLevenshtein:
    def test_identical_strings_zero(self):
        assert _levenshtein("hello", "hello") == 0

    def test_empty_a(self):
        assert _levenshtein("", "abc") == 3

    def test_empty_b(self):
        assert _levenshtein("abc", "") == 3

    def test_single_substitution(self):
        assert _levenshtein("cat", "bat") == 1

    def test_insertion(self):
        assert _levenshtein("cat", "cats") == 1

    def test_deletion(self):
        assert _levenshtein("cats", "cat") == 1

    def test_long_strings_truncated_to_1000(self):
        # Should not crash on very long inputs
        a = "a" * 2000
        b = "b" * 2000
        result = _levenshtein(a, b)
        assert isinstance(result, int)
        assert result > 0


class TestComputeReward:
    def test_used_as_is_is_1(self):
        assert _compute_reward("used_as_is") == 1.0

    def test_skipped_is_0(self):
        assert _compute_reward("skipped") == 0.0

    def test_regenerated_is_0_2(self):
        assert _compute_reward("regenerated") == 0.2

    def test_edited_no_distance_is_0_8(self):
        score = _compute_reward("edited", edit_distance=0, answer_len=100)
        assert score == 0.8

    def test_edited_high_distance_capped_at_0_4(self):
        score = _compute_reward("edited", edit_distance=1000, answer_len=100)
        assert score == 0.4

    def test_edited_partial_distance_between_0_4_and_0_8(self):
        score = _compute_reward("edited", edit_distance=20, answer_len=100)
        assert 0.4 <= score <= 0.8

    def test_unknown_feedback_returns_0_5(self):
        assert _compute_reward("unknown_value") == 0.5

    def test_pending_returns_0_5(self):
        assert _compute_reward("pending") == 0.5

    def test_reward_is_float(self):
        result = _compute_reward("used_as_is")
        assert isinstance(result, float)
