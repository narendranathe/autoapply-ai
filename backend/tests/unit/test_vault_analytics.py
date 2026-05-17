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

from app.routers.vault import _compute_reward, _levenshtein, _levenshtein_ratio  # noqa: E402


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


class TestLevenshteinRatio:
    def test_identical_strings_ratio_1(self):
        assert _levenshtein_ratio("hello world", "hello world") == 1.0

    def test_completely_different_ratio_0(self):
        # No characters in common, equal length → ratio == 0.0
        assert _levenshtein_ratio("aaaa", "bbbb") == 0.0

    def test_both_empty_ratio_1(self):
        assert _levenshtein_ratio("", "") == 1.0

    def test_partial_similarity_in_range(self):
        ratio = _levenshtein_ratio("hello world", "hello globe")
        assert 0.0 < ratio < 1.0


class TestComputeRewardRatio:
    def test_edited_ratio_zero_maps_to_0_4(self):
        # ratio 0.0 → 0.4 + 0.0 * 0.4 = 0.4
        score = _compute_reward("edited", ratio=0.0)
        assert score == 0.4

    def test_edited_ratio_half_maps_to_0_6(self):
        # ratio 0.5 → 0.4 + 0.5 * 0.4 = 0.6
        score = _compute_reward("edited", ratio=0.5)
        assert abs(score - 0.6) < 1e-9

    def test_edited_ratio_one_maps_to_0_8(self):
        # ratio 1.0 → 0.4 + 1.0 * 0.4 = 0.8
        score = _compute_reward("edited", ratio=1.0)
        assert abs(score - 0.8) < 1e-9

    def test_edited_missing_ratio_fallback_to_0_8(self):
        # No ratio + no edit_distance → backward-compat 0.8
        assert _compute_reward("edited") == 0.8

    def test_edited_ratio_clamped_above_1(self):
        score = _compute_reward("edited", ratio=1.5)
        assert abs(score - 0.8) < 1e-9

    def test_edited_ratio_clamped_below_0(self):
        score = _compute_reward("edited", ratio=-0.3)
        assert score == 0.4

    def test_used_as_is_unaffected_by_ratio(self):
        assert _compute_reward("used_as_is", ratio=0.0) == 1.0

    def test_regenerated_unaffected_by_ratio(self):
        assert _compute_reward("regenerated", ratio=1.0) == 0.2

    def test_skipped_unaffected_by_ratio(self):
        assert _compute_reward("skipped", ratio=1.0) == 0.0


class TestLevenshteinRatioUnicode:
    def test_unicode_nfc_nfd_normalization(self):
        # "café" in NFC (single precomposed é, U+00E9) vs. NFD
        # ("e" + combining acute U+0301). Visually identical → ratio == 1.0
        nfc = "café"  # café
        nfd = "café"  # café (decomposed)
        assert nfc != nfd  # sanity: they really are different byte sequences
        assert _levenshtein_ratio(nfc, nfd) == 1.0

    def test_long_input_truncated_to_1000_for_ratio(self):
        # Both inputs exceed 1000 chars but agree on the first 1000 →
        # truncation should cause ratio == 1.0.
        a = "a" * 1000 + "x" * 5000
        b = "a" * 1000 + "y" * 5000
        assert _levenshtein_ratio(a, b) == 1.0


class TestRecordAnswerFeedbackTextHandling:
    """
    Exercise the PATCH /answers/{id}/feedback handler in isolation by stubbing
    the DB and user dependencies. Validates the empty/whitespace fallback
    behaviour that prevents data loss.
    """

    def _make_env(self):
        import asyncio

        from app.routers.vault.answers import record_answer_feedback

        class _Ans:
            answer_text = "Original draft text."
            word_count = 3
            feedback: str | None = None
            edit_distance: int | None = None
            reward_score: float | None = None

        ans = _Ans()

        class _Result:
            def scalar_one_or_none(self_inner):
                return ans

        class _DB:
            async def execute(self_inner, _stmt):
                return _Result()

            async def commit(self_inner):
                return None

        class _User:
            id = "00000000-0000-0000-0000-000000000000"

        def _run(**kwargs):
            return asyncio.get_event_loop().run_until_complete(
                record_answer_feedback(
                    answer_id="11111111-1111-1111-1111-111111111111",
                    db=_DB(),
                    user=_User(),
                    **kwargs,
                )
            )

        return ans, _run

    def test_edited_with_empty_submitted_text_falls_back_to_0_8(self):
        ans, run = self._make_env()
        resp = run(feedback="edited", submitted_text="", edited_answer=None)
        # Empty submitted_text must NOT wipe the stored answer.
        assert ans.answer_text == "Original draft text."
        assert resp["reward_score"] == 0.8
        assert resp["similarity_ratio"] is None
        assert resp["edit_distance"] == 0

    def test_edited_with_whitespace_only_submitted_text_falls_back_to_0_8(self):
        ans, run = self._make_env()
        resp = run(feedback="edited", submitted_text="   \n\t  ", edited_answer=None)
        assert ans.answer_text == "Original draft text."
        assert resp["reward_score"] == 0.8
        assert resp["similarity_ratio"] is None

    def test_edited_with_real_submitted_text_updates_answer_and_returns_ratio(self):
        ans, run = self._make_env()
        resp = run(
            feedback="edited",
            submitted_text="Original draft text!",  # one-char edit
            edited_answer=None,
        )
        assert ans.answer_text == "Original draft text!"
        assert resp["similarity_ratio"] is not None
        assert 0.0 < resp["similarity_ratio"] < 1.0
        assert 0.4 <= resp["reward_score"] <= 0.8

    def test_edited_with_blank_submitted_text_falls_back_to_edited_answer(self):
        ans, run = self._make_env()
        resp = run(
            feedback="edited",
            submitted_text="",
            edited_answer="Original draft text edited.",
        )
        assert ans.answer_text == "Original draft text edited."
        assert resp["similarity_ratio"] is not None

    def test_response_uses_similarity_ratio_key(self):
        _ans, run = self._make_env()
        resp = run(feedback="used_as_is", submitted_text=None, edited_answer=None)
        # The renamed response field must be present (even when None).
        assert "similarity_ratio" in resp
        assert "ratio" not in resp
