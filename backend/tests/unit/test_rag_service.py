"""
Unit tests for rag_service.py — chunking, context formatting, similarity helpers.

All tests are pure unit tests (no DB, no async) — fast and always runnable.
"""

from app.services.rag_service import (
    RetrievedChunk,
    _estimate_tokens,
    _split_into_paragraphs,
    chunk_markdown,
    format_rag_context,
)

# ── _estimate_tokens ───────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 1  # min 1

    def test_four_chars_per_token(self):
        text = "a" * 400  # 400 chars → 100 tokens
        assert _estimate_tokens(text) == 100

    def test_short_string(self):
        assert _estimate_tokens("hello") == 1  # 5 chars → 1


# ── _split_into_paragraphs ─────────────────────────────────────────────────


class TestSplitIntoParagraphs:
    def test_empty_text(self):
        assert _split_into_paragraphs("") == []

    def test_whitespace_only(self):
        assert _split_into_paragraphs("   \n  \n  ") == []

    def test_short_text_stays_in_one_chunk(self):
        text = "Short paragraph that fits in one chunk."
        chunks = _split_into_paragraphs(text)
        assert len(chunks) == 1
        assert "Short paragraph" in chunks[0]

    def test_long_text_splits_into_multiple_chunks(self):
        # Generate a line that is ~20 tokens (80 chars each) x 25 lines = ~500 tokens
        lines = [f"Line {i}: " + "word " * 16 for i in range(25)]
        text = "\n".join(lines)
        chunks = _split_into_paragraphs(text)
        assert len(chunks) >= 2

    def test_overlap_preserves_context(self):
        lines = [f"Important context line {i}: " + "word " * 18 for i in range(30)]
        text = "\n".join(lines)
        chunks = _split_into_paragraphs(text, overlap=3)
        # First chunk should not appear in the last chunk (too far apart)
        assert len(chunks) >= 2
        # But consecutive chunks should share some lines (overlap)
        if len(chunks) >= 2:
            last_lines_of_first = set(chunks[0].split("\n")[-3:])
            first_lines_of_second = set(chunks[1].split("\n")[:3])
            overlap = last_lines_of_first & first_lines_of_second
            assert len(overlap) > 0


# ── chunk_markdown ─────────────────────────────────────────────────────────


class TestChunkMarkdown:
    def test_empty_document(self):
        assert chunk_markdown("") == []

    def test_whitespace_document(self):
        assert chunk_markdown("   \n\n\n  ") == []

    def test_simple_one_section(self):
        md = "## Experience\n\nBuilt data pipelines with Apache Spark."
        chunks = chunk_markdown(md)
        assert len(chunks) >= 1
        assert chunks[0].section_header == "Experience"
        assert "Apache Spark" in chunks[0].chunk_text

    def test_multiple_sections(self):
        md = """## Summary
Senior data engineer with 5 years experience.

## Experience
### Company A
Led team of 4 engineers.

## Skills
Python, Scala, Spark, Kafka."""
        chunks = chunk_markdown(md)
        headers = {c.section_header for c in chunks}
        assert "Summary" in headers or any("Summary" in c.chunk_text for c in chunks)
        assert "Skills" in headers or any("Skills" in c.chunk_text for c in chunks)

    def test_chunk_index_is_sequential(self):
        md = """## Section 1
Content here.

## Section 2
More content here.

## Section 3
Even more content."""
        chunks = chunk_markdown(md)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_no_headers_treated_as_one_chunk(self):
        md = "Just some text without any headers.\nAnother line here."
        chunks = chunk_markdown(md)
        assert len(chunks) >= 1
        combined = " ".join(c.chunk_text for c in chunks)
        assert "Just some text" in combined

    def test_long_section_splits_into_sub_chunks(self):
        # Build a section with ~800 tokens of content
        long_body = "\n".join([f"Bullet point {i}: " + "detail " * 20 for i in range(40)])
        md = f"## Long Experience Section\n\n{long_body}"
        chunks = chunk_markdown(md)
        assert len(chunks) >= 2
        # All chunks should have the same section_header
        assert all(c.section_header == "Long Experience Section" for c in chunks)

    def test_section_header_included_in_chunk_text(self):
        md = "## Technical Skills\n\nPython, Go, Rust, Terraform."
        chunks = chunk_markdown(md)
        assert any("Technical Skills" in c.chunk_text for c in chunks)

    def test_hash3_headers_work(self):
        md = "### Sub-section\nContent under sub-section."
        chunks = chunk_markdown(md)
        assert len(chunks) >= 1
        assert "Sub-section" in chunks[0].section_header or "Sub-section" in chunks[0].chunk_text


# ── format_rag_context ─────────────────────────────────────────────────────


class TestFormatRagContext:
    def _make_chunk(
        self, text: str, section: str = "Experience", doc_type: str = "resume"
    ) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_text=text,
            section_header=section,
            doc_type=doc_type,
            source_filename="resume.md",
            chunk_index=0,
            score=0.8,
        )

    def test_empty_chunks_returns_empty(self):
        result = format_rag_context([])
        assert result == ""

    def test_single_chunk_included(self):
        chunk = self._make_chunk("Led data pipeline engineering team.")
        result = format_rag_context([chunk])
        assert "Led data pipeline engineering team." in result
        assert "RELEVANT BACKGROUND" in result
        assert "--- END BACKGROUND ---" in result

    def test_custom_label(self):
        chunk = self._make_chunk("Some content.")
        result = format_rag_context([chunk], label="MY PROFILE")
        assert "MY PROFILE" in result

    def test_max_tokens_respected(self):
        # Create a chunk with ~400 token text
        long_text = "word " * 400  # ~400 tokens
        chunk = self._make_chunk(long_text)
        result = format_rag_context([chunk], max_tokens=100)
        # Should be truncated — result text should be shorter than full chunk
        assert len(result) < len(long_text)
        assert "..." in result

    def test_multiple_chunks_sorted_by_index(self):
        chunk_a = RetrievedChunk(
            chunk_text="First chunk content.",
            section_header="Summary",
            doc_type="resume",
            source_filename="resume.md",
            chunk_index=0,
            score=0.9,
        )
        chunk_b = RetrievedChunk(
            chunk_text="Second chunk content.",
            section_header="Experience",
            doc_type="resume",
            source_filename="resume.md",
            chunk_index=1,
            score=0.7,
        )
        # Pass in reverse order — output should sort by index
        result = format_rag_context([chunk_b, chunk_a])
        pos_a = result.find("First chunk")
        pos_b = result.find("Second chunk")
        assert pos_a < pos_b  # chunk 0 comes before chunk 1

    def test_header_shown_in_brackets(self):
        chunk = self._make_chunk("Some skill content.", section="Technical Skills")
        result = format_rag_context([chunk])
        assert "Technical Skills" in result
