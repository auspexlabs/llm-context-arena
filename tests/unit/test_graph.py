"""Tests for code graph expansion."""

from backend.rag.entity_index import EntityIndex
from backend.rag.graph import CodeGraph
from backend.rag.types import CodeChunk


def _chunk(cid: str, symbol: str, refs=None) -> CodeChunk:
    return CodeChunk(
        chunk_id=cid,
        source=f"{symbol}.py",
        content=f"def {symbol}(): pass",
        line_start=1,
        line_end=3,
        chunk_type="function",
        symbol=symbol,
        references=refs or [],
    )


class TestCodeGraph:
    def test_neighbors_1hop(self):
        a = _chunk("a", "alpha", refs=["beta"])
        b = _chunk("b", "beta")
        index = EntityIndex.from_chunks([a, b])
        graph = CodeGraph.from_chunks([a, b], index)
        expanded = graph.neighbors_1hop(["a"])
        assert "b" in expanded

    def test_trace_expand_multi_hop(self):
        a = _chunk("a", "a", refs=["b"])
        b = _chunk("b", "b", refs=["c"])
        c = _chunk("c", "c")
        index = EntityIndex.from_chunks([a, b, c])
        graph = CodeGraph.from_chunks([a, b, c], index)
        trace = graph.trace_expand(["a"], max_hops=3)
        assert "a" in trace
        assert "c" in trace