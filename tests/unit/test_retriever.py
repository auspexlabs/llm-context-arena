"""Tests for CodeRetriever orchestration."""

from backend.rag.entity_index import EntityIndex
from backend.rag.graph import CodeGraph
from backend.rag.rerank import CrossEncoderReranker
from backend.rag.retriever import CodeRetriever, RetrievalConfig
from backend.rag.query_router import QueryRoute
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

    def test_explicit_paths_are_protected_from_hostile_reranker(self, tmp_path):
        paths = [
            "mcp_arena/server.py",
            "mcp_arena/client.py",
            "backend/routes/turns.py",
            "backend/turn_service.py",
        ]
        chunks = [
            _chunk(str(index), "create_turn", "relevant control plane", source)
            for index, source in enumerate(paths)
        ]
        noise = _chunk("noise", "noise", "preferred by reranker", "docs/noise.md")
        all_chunks = chunks + [noise]
        store = ConversationStore("path-convo", tmp_path, _FakeEmbedder())
        store.chunks = {chunk.chunk_id: chunk for chunk in all_chunks}
        store.chunk_order = list(store.chunks)
        store.entity_index = EntityIndex.from_chunks(all_chunks)
        store.graph = CodeGraph.from_chunks(all_chunks, store.entity_index)

        class FakeSemantic:
            def search(self, _query, k=10):
                return [(noise, 1.0)] + [(chunk, 0.1) for chunk in chunks]

        store.colbert_index = FakeSemantic()
        reranker = CrossEncoderReranker(
            score_fn=lambda _query, doc: 1.0 if "noise" in doc else 0.0,
            enabled=True,
        )
        retriever = CodeRetriever(
            store,
            reranker=reranker,
            retrieve_candidates=10,
            rerank_top_k=4,
            config=RetrievalConfig(use_graph=False, use_query_router=False),
        )
        query = (
            "Trace mcp_arena/server.py, mcp_arena/client.py, "
            "backend/routes/turns.py, and backend/turn_service.py."
        )
        ranked = retriever.retrieve_post_rerank_pre_graph(query, top_k=4)
        assert [chunk.source for chunk, _ in ranked] == paths

    def test_multiple_explicit_paths_override_architectural_no_graph_route(self, tmp_path):
        store = ConversationStore("route-convo", tmp_path, _FakeEmbedder())
        retriever = CodeRetriever(
            store,
            config=RetrievalConfig(use_query_router=True),
            route_fn=lambda _query: QueryRoute("architectural", False, False, 0),
        )
        route = retriever._resolve_route("Compare backend/a.py with backend/b.py")
        assert route.category == "cross_file"
        assert route.use_graph_append is True

    def test_parent_display_content_is_deduplicated(self):
        parent = _chunk("parent", "Service", "class Service: ...", "service.py")
        child_a = _chunk("a", "Service.a", "def a(): ...", "service.py")
        child_b = _chunk("b", "Service.b", "def b(): ...", "service.py")
        child_a.parent_id = parent.chunk_id
        child_b.parent_id = parent.chunk_id
        ranked = CodeRetriever._dedupe_parent_content(
            [(child_a, 0.9), (parent, 0.8), (child_b, 0.7)]
        )
        assert [chunk.chunk_id for chunk, _ in ranked] == ["a"]

    def test_auxiliary_seeds_extend_instead_of_displacing_semantic_pool(self, tmp_path):
        semantic = [_chunk(str(i), f"symbol_{i}", f"body {i}", f"src/{i}.py") for i in range(5)]
        explicit = _chunk("explicit", "named", "named body", "named.py")
        store = ConversationStore("fusion-convo", tmp_path, _FakeEmbedder())
        all_chunks = semantic + [explicit]
        store.chunks = {chunk.chunk_id: chunk for chunk in all_chunks}
        store.entity_index = EntityIndex.from_chunks(all_chunks)

        class FakeSemantic:
            def search(self, _query, k=10):
                return [(chunk, 1.0 - index * 0.1) for index, chunk in enumerate(semantic)]

        store.colbert_index = FakeSemantic()
        retriever = CodeRetriever(
            store,
            retrieve_candidates=5,
            config=RetrievalConfig(use_graph=False, use_query_router=False),
        )
        pool = retriever._build_candidate_pool("Inspect named.py")
        assert {chunk.chunk_id for chunk, _ in pool} == {
            "0", "1", "2", "3", "4", "explicit"
        }

    def test_code_focused_selection_caps_docs_and_keeps_code(self):
        docs = [
            (_chunk(f"d{i}", f"doc_{i}", "prose", f"docs/{i}.md"), 1.0 - i * 0.01)
            for i in range(8)
        ]
        code = [
            (_chunk(f"c{i}", f"code_{i}", "code", f"backend/{i}.py"), 0.5 - i * 0.01)
            for i in range(8)
        ]
        selected = CodeRetriever._select_source_diverse(docs + code, top_k=8)
        selected_sources = [chunk.source for chunk, _ in selected]
        assert sum(source.startswith("docs/") for source in selected_sources) == 2
        assert sum(source.startswith("backend/") for source in selected_sources) == 6

    def test_source_diversity_never_drops_protected_docs(self):
        docs = [
            (_chunk(f"d{i}", f"doc_{i}", "prose", f"docs/{i}.md"), 1.0 - i * 0.01)
            for i in range(4)
        ]
        code = [
            (_chunk(f"c{i}", f"code_{i}", "code", f"backend/{i}.py"), 0.5 - i * 0.01)
            for i in range(4)
        ]
        protected = {"d0", "d1", "d2"}
        selected = CodeRetriever._select_source_diverse(
            docs + code,
            top_k=4,
            protected_ids=protected,
        )
        assert protected.issubset({chunk.chunk_id for chunk, _ in selected})
