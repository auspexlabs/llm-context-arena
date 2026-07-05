"""Tests for context formatting."""

from backend.rag.format import build_context_block, estimate_tokens
from backend.rag.types import CodeChunk


class TestFormat:
    def test_citation_in_context_block(self):
        chunk = CodeChunk(
            chunk_id="c1",
            source="backend/main.py",
            content="def run(): pass",
            line_start=12,
            line_end=18,
            chunk_type="function",
            symbol="run",
        )
        block, entries = build_context_block([(chunk, 0.9)])
        assert "backend/main.py:12-18" in block
        assert entries[0]["citation"] == "backend/main.py:12-18"

    def test_estimate_tokens(self):
        assert estimate_tokens("abcd") == 1