"""Tests for AST-aware chunking."""

from pathlib import Path

from backend.rag.chunker import chunk_file, chunk_repository


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestChunkFile:
    def test_python_extracts_functions_and_classes(self):
        path = FIXTURES / "sample_module.py"
        chunks = chunk_file(path, FIXTURES)
        symbols = {c.symbol for c in chunks if c.symbol}
        assert "helper" in symbols
        assert "Widget" in symbols
        assert any("Widget.spin" in (s or "") for s in symbols)

    def test_chunks_have_line_numbers(self):
        path = FIXTURES / "sample_module.py"
        chunks = chunk_file(path, FIXTURES)
        assert chunks
        for chunk in chunks:
            assert chunk.line_start >= 1
            assert chunk.line_end >= chunk.line_start
            assert chunk.citation_header().startswith("sample_module.py:")

    def test_repository_chunking(self):
        chunks = chunk_repository(FIXTURES)
        assert len(chunks) >= 3