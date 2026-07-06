"""Tests for HYP-001 multi-checkpoint eval reporting."""

from pathlib import Path

from backend.rag.eval import CHECKPOINTS, build_eval_store, load_golden_queries, run_variant_eval

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_REPO = FIXTURES / "golden_repo"
QUERIES = FIXTURES / "hyp001_golden_queries.json"


class TestEvalCheckpoints:
    def test_variant_eval_includes_all_checkpoints(self):
        store = build_eval_store(GOLDEN_REPO, colbert_mode="hash")
        queries = load_golden_queries(QUERIES)
        result = run_variant_eval(store, queries, "E", k=10)
        assert set(result["checkpoints"].keys()) == set(CHECKPOINTS)
        for cp in CHECKPOINTS:
            assert "recall_at_k" in result["checkpoints"][cp]
            assert "per_query" in result["checkpoints"][cp]

    def test_fetch_user_query_hits_after_nested_chunking(self):
        store = build_eval_store(GOLDEN_REPO, colbert_mode="hash")
        queries = load_golden_queries(QUERIES)
        q13 = next(q for q in queries if q.id == "q13")
        result = run_variant_eval(store, [q13], "B", k=10)
        assert result["checkpoints"]["pre_rerank"]["recall_at_k"] == 1.0