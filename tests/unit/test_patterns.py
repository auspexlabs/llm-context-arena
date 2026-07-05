"""Tests for pattern-based edge inference."""

from backend.rag.patterns import infer_pattern_edges, load_pattern_config


class TestPatterns:
    def test_load_config(self):
        cfg = load_pattern_config()
        assert "queue_producer" in cfg

    def test_infer_queue_edge(self):
        cfg = load_pattern_config()
        edges = infer_pattern_edges("c1", "queue.put(item)", cfg)
        assert any(rel == "queue_producer" for _, rel, _ in edges)