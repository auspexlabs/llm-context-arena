"""Tests for DEC-018 metrics instrumentation (A10)."""

from fastapi.testclient import TestClient

from backend.dependencies import clear_caches
from backend.main import app
from backend.metrics import increment_counter, record_turn_metrics, render_prometheus, reset_metrics


def setup_function():
    reset_metrics()
    clear_caches()


def test_record_turn_metrics_increments_counters():
    record_turn_metrics(
        metadata={
            "mode": "council",
            "model_failures": [{"status": 429}],
            "budget_decisions": {
                "m1": {
                    "components": {"rag": 1000, "user": 50, "total": 1050},
                }
            },
            "summarize_jobs": [
                {
                    "outcome": "ok",
                    "prompt_id": "context.summarize.rag",
                    "cache_hit": False,
                    "duration_ms": 250,
                },
                {
                    "outcome": "failed",
                    "prompt_id": "context.summarize.rag",
                    "cache_hit": False,
                    "duration_ms": 0,
                },
            ],
        },
        quality={"severity": "degraded", "observation_pending": []},
    )
    body = render_prometheus()
    assert "arena_turns_total" in body
    assert 'mode="council"' in body
    assert 'quality_severity="degraded"' in body
    assert "arena_model_failures_total" in body
    assert 'status_class="rate_limit"' in body
    assert "arena_prompt_tokens" in body
    assert 'component="rag"' in body
    assert "arena_summarize_jobs_total" in body
    assert 'outcome="failed"' in body
    assert "arena_summarize_duration_seconds" in body
    assert "arena_config_freeze_generation" in body


def test_metrics_endpoint():
    reset_metrics()
    increment_counter("arena_turns_total", mode="council", quality_severity="ok")
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "arena_turns_total" in resp.text