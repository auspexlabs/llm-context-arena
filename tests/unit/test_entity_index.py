"""Tests for entity index."""

from backend.rag.entity_index import EntityIndex
from backend.rag.types import CodeChunk


def _chunk(symbol: str, cid: str) -> CodeChunk:
    return CodeChunk(
        chunk_id=cid,
        source="mod.py",
        content=f"def {symbol.split('.')[-1]}(): pass",
        line_start=1,
        line_end=2,
        chunk_type="function",
        symbol=symbol,
    )


class TestEntityIndex:
    def test_lookup_and_query_seeding(self):
        chunks = [_chunk("helper", "c1"), _chunk("Widget.spin", "c2")]
        index = EntityIndex.from_chunks(chunks)
        assert index.lookup("helper")
        assert "spin" in index.seed_symbols_from_query("Where is spin defined?")