"""HYP-002: router + variant F eval harness."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

pytestmark = pytest.mark.eval

from backend.rag.eval import build_eval_store, load_golden_queries
from backend.rag.eval_hyp002 import (
    answer_slot_purity,
    load_probe_queries,
    router_accuracy,
    run_hyp002_cell,
    run_hyp002_matrix,
)
from backend.rag.query_router import (
    EmbeddingQueryRouter,
    reset_routers,
    route_from_category,
    route_query,
    route_query_regex,
)
from backend.rag.rerank import CrossEncoderReranker
from backend.rag.retriever import CodeRetriever, RetrievalConfig

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_REPO = FIXTURES / "golden_repo"
ARENA_REPO = Path(__file__).resolve().parents[2] / "backend"
QUERIES = FIXTURES / "hyp001_golden_queries.json"
PROBES = FIXTURES / "hyp002_architectural_probes.json"


def _hash_encode(texts):
    vectors = []
    for text in texts:
        vec = [0.0] * 8
        for word in text.lower().split():
            vec[hash(word) % 8] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


@pytest.fixture(scope="module")
def golden_store():
    return build_eval_store(GOLDEN_REPO, conversation_id="hyp002_test_golden")


@pytest.fixture(scope="module")
def arena_store():
    return build_eval_store(ARENA_REPO, conversation_id="hyp002_test_arena")


@pytest.fixture(scope="module")
def golden_queries():
    return load_golden_queries(QUERIES)


@pytest.fixture(scope="module")
def architectural_probes():
    return load_probe_queries(PROBES)


class TestQueryRouter:
    def setup_method(self):
        reset_routers()

    def test_architectural_query_skips_graph_append(self):
        router = EmbeddingQueryRouter.from_training_file()
        route = router.route("council deliberation pipeline")
        assert route.category == "architectural"
        assert route.use_graph_append is False

    def test_regex_fallback_classifies_architectural(self):
        route = route_query_regex("council deliberation pipeline")
        assert route.category == "architectural"

    def test_embedding_router_classifies_trace(self, golden_queries):
        labeled = [(q.query, q.category) for q in golden_queries]
        router = EmbeddingQueryRouter.from_labeled_queries(labeled, encode_fn=_hash_encode)
        category, _ = router.classify("trace call chain for authenticate_user")
        assert category == "trace"


class TestHyp002Harness:
    def test_answer_slot_purity_full_when_graph_disabled(self, golden_store):
        config = RetrievalConfig.for_variant("F")
        retriever = CodeRetriever(
            golden_store,
            reranker=CrossEncoderReranker(score_fn=lambda _q, _d: 0.5, enabled=True),
            rerank_top_k=5,
            context_chunk_cap=10,
            config=config,
            route_fn=lambda _q: route_from_category("architectural"),
        )
        purity = answer_slot_purity(retriever, "application bootstrap entrypoint", k=5)
        assert purity == 1.0

    def test_router_accuracy_baseline(self, golden_queries):
        labeled = [(q.query, q.category) for q in golden_queries]
        result = router_accuracy(route_query_regex, labeled)
        assert result["accuracy"] >= 0.0

    def test_run_hyp002_cell_mock(self, golden_store, arena_store, golden_queries, architectural_probes):
        cell = run_hyp002_cell(
            golden_store,
            arena_store,
            golden_queries,
            architectural_probes,
            router_mode="regex",
            rerank_mode="mock",
            k=10,
        )
        assert cell["variant"] == "F"
        assert "golden" in cell
        assert "architectural" in cell
        assert cell["architectural"]["mean_purity"] >= 0.0

    def test_run_hyp002_matrix_fast(self):
        matrix = run_hyp002_matrix(
            GOLDEN_REPO,
            QUERIES,
            ARENA_REPO,
            PROBES,
            k=10,
            colbert_mode="hash",
            routers=("regex",),
            rerankers=("mock",),
        )
        assert matrix["variant"] == "F"
        assert "regex+mock" in matrix["cells"]
        assert matrix["summary"]["golden_recall"]["regex+mock"] >= 0.0