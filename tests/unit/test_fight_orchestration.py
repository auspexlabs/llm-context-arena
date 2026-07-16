"""Fight persists RAG-free orchestration projections for every debate phase."""

import pytest

from backend.arena import run_mode_fight
from backend.execution_trace import build_execution_trace


@pytest.mark.asyncio
async def test_fight_orchestration_tracks_handoffs_without_rag(monkeypatch):
    grounded = "# Relevant repository context (CodeRAG)\nSECRET_RAG_BODY\n\nUser question: Why?"
    calls = 0

    async def fake_query(model, messages, timeout=120.0, log_error=True):
        nonlocal calls
        calls += 1
        return {"content": f"response {calls} from {model}", "usage": {}}

    monkeypatch.setattr("backend.arena.query_model", fake_query)
    _, _, chair, metadata = await run_mode_fight(
        grounded,
        {"m1": grounded, "m2": grounded},
        ["m1", "m2"],
        "chair",
    )

    steps = metadata["steps"]
    assert [step["role"] for step in steps] == [
        "answer",
        "answer",
        "critique",
        "critique",
        "defense",
        "defense",
        "chair_final",
    ]
    assert all("SECRET_RAG_BODY" in step["prompt_full"] for step in steps)
    assert all("SECRET_RAG_BODY" not in step["orchestration_text"] for step in steps)
    assert "Mode: Fight" in steps[0]["orchestration_text"]
    assert "opening position artifact attached" in steps[2]["orchestration_text"]
    assert "peer critique artifact attached" in steps[4]["orchestration_text"]
    assert "defense artifact attached" in chair["orchestration_text"]

    critique_parts = steps[2]["prompt_provenance"]["parts"]
    defense_parts = steps[4]["prompt_provenance"]["parts"]
    assert [
        part["producer"]
        for part in critique_parts
        if part["kind"] == "artifact_ref"
    ] == [{"role": "answer", "model": "m2"}]
    assert [
        part["producer"]
        for part in defense_parts
        if part["kind"] == "artifact_ref"
    ] == [
        {"role": "answer", "model": "m1"},
        {"role": "critique", "model": "m2"},
    ]

    trace = build_execution_trace(
        mode="fight",
        metadata_steps=steps,
        arena_models=["m1", "m2"],
        chairman_model="chair",
        has_context=True,
    )
    defense_node = next(
        node
        for node in trace["steps"]
        if node["kind"] == "defense" and node["model"] == "m1"
    )
    linked = [
        part
        for part in defense_node["prompt_provenance"]["parts"]
        if part["kind"] == "artifact_ref"
    ]
    assert all(part["producer_step_id"] for part in linked)
    assert all(part["artifact_id"] for part in linked)
    assert defense_node["prompt_input_artifact_ids"][0] == "rag-context"
