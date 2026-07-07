"""Tests for CodeRetriever orchestration."""

from backend.rag.entity_index import EntityIndex
from backend.rag.graph import CodeGraph
from backend.rag.rerank import CrossEncoderReranker
from backend.rag.retriever import CodeRetriever, RetrievalConfig
from backend.rag.store import ConversationStore
from backend.rag.types import CodeChunk


class _FakeEmbedder:
    def embed_query(self, text: str):
        return [1.0, 0.0]

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _chunk(cid: str, symbol: str, content: str, source: str = "a.py") -> CodeChunk:
    return CodeChunk(
        chunk_id=cid,
        source=source,
        content=content,
        line_start=1,
        line_end=10,
        chunk_type="function",
        symbol=symbol,
        index_text=content,
        references=["beta"] if symbol == "alpha" else [],
    )


class TestCodeRetriever:
    def test_retrieve_merges_semantic_and_graph(self, tmp_path):
        alpha = _chunk("a", "alpha", "alpha logic", "alpha.py")
        beta = _chunk("b", "beta", "beta logic", "beta.py")
        readme = _chunk("r", None, "project intro", "README.md")

        store = ConversationStore("test-convo", tmp_path, _FakeEmbedder())
        store.chunks = {c.chunk_id: c for c in [alpha, beta, readme]}
        store.chunk_order = ["a", "b", "r"]
        store.entity_index = EntityIndex.from_chunks([alpha, beta, readme])
        store.graph = CodeGraph.from_chunks([alpha, beta, readme], store.entity_index)

        class _FakeVS:
            def similarity_search_with_score(self, query, k=10):
                from langchain_core.documents import Document
                return [
                    (Document(page_content=readme.content, metadata=readme.to_faiss_metadata(2)), 0.1),
                    (Document(page_content=alpha.content, metadata=alpha.to_faiss_metadata(0)), 0.5),
                ]

        store.vectorstore = _FakeVS()

        reranker = CrossEncoderReranker(
            score_fn=lambda q, d: 0.95 if "alpha" in d else 0.2,
            enabled=True,
        )
        retriever = CodeRetriever(store, reranker=reranker, retrieve_candidates=10, rerank_top_k=5)

        block, entries, _ = retriever.retrieve("trace call chain for alpha")
        assert "alpha.py:1-10" in block
        sources = {e["source"] for e in entries}
        assert "alpha.py" in sources
        assert "README.md" not in sources or entries[0]["source"] != "README.md"

    def test_append_graph_does_not_displace_top_ranked(self, tmp_path):
        alpha = _chunk("a", "alpha", "alpha logic", "alpha.py")
        beta = _chunk("b", "beta", "beta logic", "beta.py")
        noise = _chunk("n", "noise", "noise logic", "noise.py")

        store = ConversationStore("test-convo", tmp_path, _FakeEmbedder())
        store.chunks = {c.chunk_id: c for c in [alpha, beta, noise]}
        store.chunk_order = ["a", "b", "n"]
        store.entity_index = EntityIndex.from_chunks([alpha, beta, noise])
        store.graph = CodeGraph.from_chunks([alpha, beta, noise], store.entity_index)

        class _FakeVS:
            def similarity_search_with_score(self, query, k=10):
                from langchain_core.documents import Document
                return [
                    (Document(page_content=noise.content, metadata=noise.to_faiss_metadata(2)), 0.99),
                    (Document(page_content=alpha.content, metadata=alpha.to_faiss_metadata(0)), 0.5),
                ]

        store.vectorstore = _FakeVS()
        reranker = CrossEncoderReranker(
            score_fn=lambda q, d: 0.95 if "alpha" in d else 0.1,
            enabled=True,
        )
        config = RetrievalConfig(
            fusion_mode="rrf",
            graph_mode="append",
            use_query_router=True,
            rerank_blend_prior=False,
        )
        retriever = CodeRetriever(
            store,
            reranker=reranker,
            retrieve_candidates=10,
            rerank_top_k=3,
            config=config,
        )

        ranked = retriever.retrieve_ranked("trace call chain for alpha")
        assert ranked[0][0].chunk_id == "a"
        assert any(chunk.chunk_id == "b" for chunk, _ in ranked[1:])