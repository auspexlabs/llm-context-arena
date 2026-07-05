"""Tests for recall@k metrics and eval helpers."""

from backend.rag.eval import (
    chunk_matches_target,
    load_golden_queries,
    mean_recall_at_k,
    recall_at_k,
)
from backend.rag.types import CodeChunk

FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures"


class TestRecallMetrics:
    def test_chunk_matches_target_by_symbol(self):
        chunk = CodeChunk("c", "auth/login.py", "body", 1, 5, "function", symbol="authenticate_user")
        assert chunk_matches_target(chunk, {"source": "auth/login.py", "symbol": "authenticate_user"})

    def test_recall_at_k_partial_hits(self):
        chunks = [
            CodeChunk("a", "auth/login.py", "a", 1, 2, "function", symbol="authenticate_user"),
            CodeChunk("b", "main.py", "b", 1, 2, "function", symbol="bootstrap"),
        ]
        relevant = [
            {"source": "auth/login.py", "symbol": "authenticate_user"},
            {"source": "services/user_service.py", "symbol": "UserService.login"},
        ]
        assert recall_at_k(chunks, relevant, k=10) == 0.5

    def test_mean_recall(self):
        assert mean_recall_at_k([1.0, 0.5, 0.0]) == 0.5

    def test_load_golden_queries(self):
        queries = load_golden_queries(FIXTURES / "hyp001_golden_queries.json")
        assert len(queries) >= 15
        assert queries[0].id.startswith("q")