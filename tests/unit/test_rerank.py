"""Tests for cross-encoder reranker."""

from backend.rag.rerank import CrossEncoderReranker
from backend.rag.types import CodeChunk


def _chunk(text: str, symbol: str = "foo") -> CodeChunk:
    return CodeChunk(
        chunk_id="c1",
        source="a.py",
        content=text,
        line_start=1,
        line_end=5,
        chunk_type="function",
        symbol=symbol,
        index_text=text,
    )


class TestCrossEncoderReranker:
    def test_injectable_score_fn(self):
        def score_fn(query: str, doc: str) -> float:
            return 1.0 if "target" in doc else 0.1

        reranker = CrossEncoderReranker(score_fn=score_fn, enabled=True)
        items = [
            (_chunk("irrelevant"), 0.5),
            (_chunk("target function"), 0.5),
        ]
        ranked = reranker.rerank("find target", items, top_k=1)
        assert ranked[0][0].content == "target function"

    def test_disabled_passthrough(self):
        reranker = CrossEncoderReranker(enabled=False)
        items = [(_chunk("a"), 0.2), (_chunk("b"), 0.9)]
        ranked = reranker.rerank("q", items, top_k=2)
        assert ranked[0][1] == 0.9