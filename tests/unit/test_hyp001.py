"""HYP-001 experiment: recall@10 across ablation variants A–D."""

from pathlib import Path

import pytest

from backend.rag.eval import HYP001_VARIANTS, build_eval_store, run_hyp001_matrix, run_variant_eval
from backend.rag.eval import load_golden_queries

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_REPO = FIXTURES / "golden_repo"
QUERIES = FIXTURES / "hyp001_golden_queries.json"


@pytest.fixture(scope="module")
def eval_store():
    return build_eval_store(GOLDEN_REPO)


@pytest.fixture(scope="module")
def golden_queries():
    return load_golden_queries(QUERIES)


class TestHyp001Matrix:
    def test_golden_repo_indexes(self, eval_store):
        assert len(eval_store.chunks) >= 10
        assert eval_store.entity_index is not None
        assert eval_store.graph is not None
        assert eval_store.colbert_index is not None

    def test_variant_a_weakest_on_symbol_lookup(self, eval_store, golden_queries):
        symbol_queries = [q for q in golden_queries if q.category == "symbol_lookup"]
        a = run_variant_eval(eval_store, symbol_queries, "A", k=10)
        b = run_variant_eval(eval_store, symbol_queries, "B", k=10)
        assert b["recall_at_k"] >= a["recall_at_k"]

    def test_entity_seed_improves_over_biencoder_only(self, eval_store, golden_queries):
        a = run_variant_eval(eval_store, golden_queries, "A", k=10)
        b = run_variant_eval(eval_store, golden_queries, "B", k=10)
        assert b["recall_at_k"] > a["recall_at_k"]

    def test_graph_improves_cross_file_and_trace(self, eval_store, golden_queries):
        cross = [q for q in golden_queries if q.category in {"cross_file", "trace"}]
        b = run_variant_eval(eval_store, cross, "B", k=10)
        c = run_variant_eval(eval_store, cross, "C", k=10)
        assert c["recall_at_k"] >= b["recall_at_k"]

    def test_colbert_beats_biencoder_on_symbol_lookup(self, eval_store, golden_queries):
        symbol_queries = [q for q in golden_queries if q.category == "symbol_lookup"]
        a = run_variant_eval(eval_store, symbol_queries, "A", k=10)
        d = run_variant_eval(eval_store, symbol_queries, "D", k=10)
        assert d["recall_at_k"] > a["recall_at_k"]

    def test_full_matrix_summary(self):
        matrix = run_hyp001_matrix(GOLDEN_REPO, QUERIES, k=10)
        summary = matrix["summary"]
        assert set(summary.keys()) == set(HYP001_VARIANTS)
        assert summary["B"] > summary["A"]
        assert summary["C"] >= summary["B"]
        assert summary["D"] > summary["A"]
        # ColBERT lifts symbol recall; hybrid C still competitive on full set
        assert summary["D"] >= summary["C"]
        symbol = [q for q in load_golden_queries(QUERIES) if q.category == "symbol_lookup"]
        a_sym = run_variant_eval(build_eval_store(GOLDEN_REPO), symbol, "A", k=10)
        d_sym = run_variant_eval(build_eval_store(GOLDEN_REPO), symbol, "D", k=10)
        assert d_sym["recall_at_k"] > a_sym["recall_at_k"]