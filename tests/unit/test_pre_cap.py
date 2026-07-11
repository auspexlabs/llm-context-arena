"""Tests for AST-aware RAG pre-cap (DEC-018 B4)."""

from backend.rag.pre_cap import apply_ast_aware_cap
from backend.rag.types import CodeChunk


def _chunk(cid: str, parent: str | None = None) -> CodeChunk:
    return CodeChunk(
        chunk_id=cid,
        source="a.py",
        content="x",
        line_start=1,
        line_end=2,
        chunk_type="function",
        parent_id=parent,
    )


def test_apply_cap_drops_orphan_child():
    parent = _chunk("p1")
    child = _chunk("c1", parent="p1")
    other = _chunk("o1")
    ranked = [(parent, 1.0), (child, 0.9), (other, 0.8), (_chunk("x"), 0.1)]
    capped = apply_ast_aware_cap(ranked, cap=3)
    ids = [c.chunk_id for c, _ in capped]
    assert "c1" not in ids or "p1" in ids