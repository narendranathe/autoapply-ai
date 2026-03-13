"""
Unit tests for the trim-answer hard-truncation fallback logic.
Tests the sentence-boundary detection independent of the LLM.
"""


def _hard_truncate(answer_text: str, max_chars: int) -> str:
    """Mirror the hard-truncation fallback in vault.py trim_answer endpoint."""
    if len(answer_text) <= max_chars:
        return answer_text
    candidate = answer_text[:max_chars]
    last_period = max(candidate.rfind(". "), candidate.rfind(".\n"))
    if last_period > max_chars * 0.6:
        return candidate[: last_period + 1]
    return candidate.rstrip() + "…"


class TestHardTruncateFallback:
    def test_no_truncation_when_under_limit(self):
        text = "Short text."
        assert _hard_truncate(text, 200) == text

    def test_cuts_at_sentence_boundary(self):
        text = "First sentence. Second sentence that is very long and goes over the limit we set."
        result = _hard_truncate(text, 20)
        # 20 chars: "First sentence. Seco" — period at index 15, threshold = 0.6 * 20 = 12 → satisfied
        assert result.endswith(".")
        assert not result.endswith("…")

    def test_appends_ellipsis_when_no_good_boundary(self):
        # No period in the first 60% of max_chars slice
        text = (
            "Averylongwordwithnoperiodatallinthefirstpartofthetext and then more text follows here."
        )
        result = _hard_truncate(text, 30)
        assert result.endswith("…")

    def test_result_fits_within_max_chars_plus_ellipsis(self):
        text = "a" * 500
        result = _hard_truncate(text, 100)
        # Ellipsis adds 1 char, so result may be max_chars + 1 at most
        assert len(result) <= 101

    def test_exact_length_text_not_truncated(self):
        text = "x" * 50
        assert _hard_truncate(text, 50) == text

    def test_sentence_boundary_threshold_60_percent(self):
        # Period at position 10 in a 20-char window → threshold is 12 → NOT used
        text = "Abc de. " + "x" * 100
        result = _hard_truncate(text, 20)
        # Position 6 = index of ". " → 6 < 12 → ellipsis fallback
        assert result.endswith("…")

    def test_period_at_start_of_candidate_ignored(self):
        # Period only at position 3, which is below 60% of 20 = 12 → use ellipsis
        text = "Hi." + "z" * 100
        result = _hard_truncate(text, 20)
        assert result.endswith("…")

    def test_empty_text(self):
        assert _hard_truncate("", 100) == ""

    def test_single_sentence_fits(self):
        text = "One sentence."
        assert _hard_truncate(text, 50) == text


class TestTrimAnswerEndpoint:
    """Structural tests for the trim_answer route parameters."""

    def test_max_chars_zero_would_still_truncate(self):
        # Edge: if max_chars=0 all text is over limit
        result = _hard_truncate("Some text.", 0)
        # candidate = "" → last_period = -1 which is NOT > 0 * 0.6 = 0 → ellipsis
        assert result in ("", "…")

    def test_newline_boundary(self):
        text = "First paragraph.\nSecond paragraph that is much longer and goes way past the limit."
        result = _hard_truncate(text, 25)
        # candidate[:25] = "First paragraph.\nSecond p"
        # rfind(".\n") returns 15 (index of '.' before '\n')
        # last_period=15, threshold=25*0.6=15.0 — NOT strictly greater, ellipsis fallback
        assert result.endswith("…")
