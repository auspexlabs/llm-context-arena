"""Tests for hybrid retrieval helpers."""

from backend.rag.entity_index import EntityIndex
from backend.rag.hybrid import (
    apply_readme_demotion,
    is_trace_query,
    readme_demotion_factor,
    seed_chunks_from_query,
)
from backend.rag.types import CodeChunk


class TestHybrid:
    def test_readme_demotion(self):
        assert readme_demotion_factor("docs/README.md") < 1.0
        assert readme_demotion_factor("backend/main.py") == 1.0

    def test_trace_query_detection(self):
        assert is_trace_query("trace the call chain for auth")
        assert not is_trace_query("what is a widget")

    def test_seed_chunks_from_symbol(self):
        chunk = CodeChunk(
            chunk_id="c1",
            source="svc.py",
            content="def authenticate(): ...",
            line_start=10,
            line_end=20,
            chunk_type="function",
            symbol="authenticate",
        )
        index = EntityIndex.from_chunks([chunk])
        hits = seed_chunks_from_query("how does authenticate work", index, {"c1": chunk})
        assert hits
        assert hits[0][0].symbol == "authenticate"

    def test_apply_readme_demotion_reorders(self):
        readme = CodeChunk("r", "README.md", "text", 1, 2, "readme")
        code = CodeChunk("c", "main.py", "code", 1, 2, "function")
        ranked = apply_readme_demotion([(readme, 0.9), (code, 0.8)])
        assert ranked[0][0].source == "main.py"