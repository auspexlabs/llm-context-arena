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

    def test_method_chunks_link_to_parent_class(self):
        chunks = chunk_file(FIXTURES / "sample_module.py", FIXTURES)
        by_symbol = {c.symbol: c for c in chunks if c.symbol}
        widget = by_symbol.get("Widget")
        method = next((c for c in chunks if (c.symbol or "").endswith("spin")), None)
        assert widget is not None
        assert method is not None
        assert method.parent_id == widget.chunk_id
        assert method.parent_content == widget.content

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

    def test_rust_extracts_types_and_methods(self):
        chunks = chunk_file(FIXTURES / "sample.rs", FIXTURES)
        symbols = {c.symbol for c in chunks if c.symbol}
        assert "Widget" in symbols
        assert "helper" in symbols
        assert any("Widget.spin" in (s or "") for s in symbols)
        assert all(c.language == "rust" for c in chunks)

    def test_javascript_extracts_functions_and_classes(self):
        chunks = chunk_file(FIXTURES / "sample.js", FIXTURES)
        symbols = {c.symbol for c in chunks if c.symbol}
        assert "helper" in symbols
        assert "Widget" in symbols
        assert any("Widget.spin" in (s or "") for s in symbols)
        assert all(c.language == "javascript" for c in chunks)

    def test_typescript_extracts_interface(self):
        chunks = chunk_file(FIXTURES / "sample.ts", FIXTURES)
        symbols = {c.symbol for c in chunks if c.symbol}
        assert "Config" in symbols
        assert "Widget" in symbols
        assert all(c.language == "typescript" for c in chunks)

    def test_tsx_extracts_component(self):
        chunks = chunk_file(FIXTURES / "sample.tsx", FIXTURES)
        symbols = {c.symbol for c in chunks if c.symbol}
        assert "App" in symbols
        assert "Panel" in symbols
        assert all(c.language == "tsx" for c in chunks)

    def test_go_extracts_methods(self):
        chunks = chunk_file(FIXTURES / "sample.go", FIXTURES)
        symbols = {c.symbol for c in chunks if c.symbol}
        assert "Helper" in symbols
        assert "Widget" in symbols
        assert any("Widget.Spin" in (s or "") for s in symbols)
        assert all(c.language == "go" for c in chunks)