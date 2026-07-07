"""Tests for RRF fusion (DEC-010)."""

from backend.rag.fusion import reciprocal_rank_fusion
from backend.rag.types import CodeChunk


def _chunk(cid: str) -> CodeChunk:
    return CodeChunk(
        chunk_id=cid,
        source=f"{cid}.py",
        content=cid,
        line_start=1,
        line_end=1,
        chunk_type="function",
        symbol=cid,
        index_text=cid,
    )


class TestReciprocalRankFusion:
    def test_boosts_chunks_present_in_multiple_lists(self):
        a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
        semantic = [(b, 0.9), (a, 0.8), (c, 0.1)]
        entity = [(a, 0.85), (c, 0.55)]
        fused = reciprocal_rank_fusion([semantic, entity], limit=3)
        ids = [chunk.chunk_id for chunk, _ in fused]
        assert ids[0] == "a"
        assert set(ids) == {"a", "b", "c"}

    def test_respects_limit(self):
        chunks = [_chunk(str(i)) for i in range(5)]
        ranked = [(c, float(i)) for i, c in enumerate(chunks)]
        fused = reciprocal_rank_fusion([ranked], limit=2)
        assert len(fused) == 2