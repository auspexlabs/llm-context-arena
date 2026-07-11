"""Tests for execution quality assessment."""

from backend.execution_quality import (
    assess_execution_quality,
    assess_from_response_dict,
    format_agent_notice,
)


def test_round_robin_single_draft_is_degraded():
    quality = assess_execution_quality(
        mode="round_robin",
        metadata={
            "arena_models": ["a", "b", "c"],
            "model_failures": [
                {"model": "a", "status": 429, "message": "rate limited", "stage": "draft_p1_t1"},
            ],
            "steps": [
                {"role": "draft_p1_t1", "model": "a", "response": ""},
                {"role": "draft_p1_t2", "model": "b", "response": ""},
                {"role": "draft_p1_t3", "model": "c", "response": "only draft"},
                {"role": "chair_final", "model": "chair", "response": "final"},
            ],
        },
        stage3={"model": "chair", "response": "final"},
    )
    assert quality["acceptable"] is False
    assert quality["severity"] == "degraded"
    assert any(i["code"] == "rr_chain_degraded" for i in quality["issues"])
    notice = format_agent_notice(quality)
    assert "EXECUTION DEGRADED" in notice
    assert "acceptable is false" in notice


def test_all_ok_when_every_model_succeeds():
    quality = assess_execution_quality(
        mode="round_robin",
        metadata={
            "arena_models": ["a", "b"],
            "steps": [
                {"role": "draft_p1_t1", "model": "a", "response": "draft a"},
                {"role": "draft_p1_t2", "model": "b", "response": "draft b"},
                {"role": "chair_final", "model": "chair", "response": "final"},
            ],
        },
        stage3={"model": "chair", "response": "final"},
    )
    assert quality["acceptable"] is True
    assert quality["severity"] == "ok"
    assert format_agent_notice(quality) == ""


def test_empty_final_is_failed():
    quality = assess_execution_quality(
        mode="council",
        metadata={"arena_models": ["a"]},
        stage1=[{"model": "a", "response": "answer"}],
        stage3={"model": "chair", "response": ""},
    )
    assert quality["acceptable"] is False
    assert quality["severity"] == "failed"


def test_agent_notice_formats_count_issues_without_raw_dict():
    quality = assess_execution_quality(
        mode="round_robin",
        metadata={
            "arena_models": ["a", "b", "c"],
            "steps": [
                {"role": "draft_p1_t1", "model": "a", "response": "ok"},
                {"role": "draft_p1_t2", "model": "b", "response": ""},
                {"role": "draft_p1_t3", "model": "c", "response": ""},
                {"role": "chair_final", "model": "chair", "response": "final"},
            ],
        },
        stage3={"model": "chair", "response": "final"},
    )
    notice = format_agent_notice(quality)
    assert "empty_draft_responses: 2 of 3 failed (1 succeeded)" in notice
    assert "{" not in notice


def test_execution_quality_includes_budget_and_summarize_fields():
    quality = assess_execution_quality(
        mode="council",
        metadata={
            "arena_models": ["a"],
            "summarize_jobs": [
                {
                    "outcome": "failed",
                    "prompt_id": "context.summarize.rag",
                    "target_model_id": "model/small",
                    "chairman_fallback": True,
                    "cache_hit": False,
                },
                {
                    "outcome": "ok",
                    "prompt_id": "context.summarize.rag",
                    "target_model_id": "model/big",
                    "chairman_fallback": True,
                    "cache_hit": False,
                },
            ],
            "budget_decisions": {
                "model/small": {"model_id": "model/small", "effective_limit": 64000},
            },
        },
        stage3={"response": "final"},
    )
    assert len(quality["summarize_failures"]) == 1
    assert quality["summarizer_used_chairman"] is True
    assert len(quality["budget_decisions"]) == 1
    assert quality["observation_pending"] == []
    assert any(i["code"] == "summarize_failure" for i in quality["issues"])
    assert any(i["code"] == "chairman_summarizer" for i in quality["issues"])
    assert quality["acceptable"] is True
    assert format_agent_notice(quality) == ""


def test_assess_from_response_dict():
    payload = {
        "metadata": {
            "mode": "round_robin",
            "model_failures": [{"model": "x", "status": 500, "message": "err"}],
            "steps": [{"role": "draft_p1_t1", "response": ""}],
        },
        "stage3": {"response": "ok"},
    }
    quality = assess_from_response_dict(payload)
    assert quality["acceptable"] is False
    assert quality["stats"]["model_failures"] == 1