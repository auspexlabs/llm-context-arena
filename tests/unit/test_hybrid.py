"""Tests for hybrid retrieval helpers."""

from backend.rag.entity_index import EntityIndex
from backend.rag.hybrid import (
    apply_readme_demotion,
    extract_path_mentions,
    is_trace_query,
    readme_demotion_factor,
    resolve_path_mentions,
    seed_chunks_from_paths,
    seed_chunks_from_identifiers,
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

    def test_extracts_and_resolves_punctuated_paths(self):
        query = "Trace backend/routes/turns.py, mcp_arena/client.py, and server.py."
        assert extract_path_mentions(query) == [
            "backend/routes/turns.py",
            "mcp_arena/client.py",
            "server.py",
        ]
        assert resolve_path_mentions(
            query,
            ["backend/routes/turns.py", "mcp_arena/client.py", "mcp_arena/server.py"],
        ) == [
            "backend/routes/turns.py",
            "mcp_arena/client.py",
            "mcp_arena/server.py",
        ]

    def test_path_seed_selects_query_relevant_chunk_per_file(self):
        create = CodeChunk("c", "backend/routes/turns.py", "create", 1, 5, "function", "create_turn")
        cancel = CodeChunk("x", "backend/routes/turns.py", "cancel", 6, 10, "function", "cancel_turn")
        hits = seed_chunks_from_paths(
            "Explain create_turn in backend/routes/turns.py.",
            {"c": create, "x": cancel},
        )
        assert [chunk.chunk_id for chunk, _ in hits] == ["c"]

    def test_identifier_seed_finds_attachment_sites(self):
        definition = CodeChunk(
            "definition", "backend/execution_quality.py", "def assess_execution_quality(): ...", 1, 5, "function", "assess_execution_quality"
        )
        attachment = CodeChunk(
            "attachment", "backend/run_turn.py", 'metadata["execution_quality"] = quality', 10, 12, "function", "run_turn"
        )
        noise = CodeChunk("noise", "docs/notes.md", "quality prose", 1, 2, "text")
        hits = seed_chunks_from_identifiers(
            "identify where execution_quality is attached",
            {chunk.chunk_id: chunk for chunk in (definition, attachment, noise)},
        )
        assert {chunk.chunk_id for chunk, _ in hits} == {"definition", "attachment"}

    def test_identifier_seed_ignores_identifier_like_path_components(self):
        path_only = CodeChunk(
            "path", "backend/turn_service.py", "unrelated", 1, 2, "function", "other"
        )
        named = CodeChunk(
            "named", "backend/run_turn.py", 'metadata["execution_quality"] = quality', 3, 4, "function", "run_turn"
        )
        hits = seed_chunks_from_identifiers(
            "Inspect backend/turn_service.py and execution_quality",
            {"path": path_only, "named": named},
        )
        assert [chunk.chunk_id for chunk, _ in hits] == ["named"]
