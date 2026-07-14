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

    def test_score_input_includes_source_path(self):
        seen = []

        def score_fn(_query: str, doc: str) -> float:
            seen.append(doc)
            return 1.0

        reranker = CrossEncoderReranker(score_fn=score_fn, enabled=True)
        reranker.rerank("find a.py", [(_chunk("body"), 0.1)], top_k=1)
        assert seen and seen[0].startswith("Path: a.py")

    def test_jina_v3_uses_listwise_results(self):
        class FakeJina:
            def rerank(self, query, documents, top_n=None):
                assert query == "q"
                assert top_n == 2
                assert all(doc.startswith("Path: a.py") for doc in documents)
                return [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ]

        reranker = CrossEncoderReranker(model_name="jinaai/jina-reranker-v3")
        reranker._model = FakeJina()
        reranker._model_kind = "listwise"
        reranker._load_attempted = True
        items = [(_chunk("first"), 0.5), (_chunk("second"), 0.5)]
        ranked = reranker.rerank("q", items, top_k=2, blend_prior=False)
        assert [chunk.content for chunk, _ in ranked] == ["second", "first"]

    def test_jina_v3_loads_custom_auto_model(self, monkeypatch):
        class FakeJina:
            def to(self, device):
                assert device == "cpu"
                return self

            def eval(self):
                return self

            def rerank(self, _query, _documents, top_n=None):
                return []

        calls = []
        tokenizer_calls = []

        class FakeTokenizer:
            pad_token = "<pad>"
            unk_token = "<unk>"
            padding_side = "right"

        def fake_load(model_name, **kwargs):
            calls.append((model_name, kwargs))
            return FakeJina()

        def fake_tokenizer_load(model_name, **kwargs):
            tokenizer_calls.append((model_name, kwargs))
            return FakeTokenizer()

        monkeypatch.setattr("transformers.AutoModel.from_pretrained", fake_load)
        monkeypatch.setattr("transformers.AutoTokenizer.from_pretrained", fake_tokenizer_load)
        monkeypatch.setattr("backend.config.get_colbert_device", lambda: "cpu")
        reranker = CrossEncoderReranker(model_name="jinaai/jina-reranker-v3")
        reranker._load_model()
        assert reranker._model_kind == "listwise"
        assert calls == [(
            "jinaai/jina-reranker-v3",
            {
                "dtype": "auto",
                "revision": "10fb694fc21f7a710a563ff1eb977a460f3868e4",
                "trust_remote_code": True,
            },
        )]
        assert tokenizer_calls == [(
            "jinaai/jina-reranker-v3",
            {
                "revision": "10fb694fc21f7a710a563ff1eb977a460f3868e4",
                "trust_remote_code": True,
            },
        )]
