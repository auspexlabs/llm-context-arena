"""Fight persists RAG-free orchestration projections for every debate phase."""

import pytest

from backend.arena import run_mode_fight


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
    assert "opening-position artifact attached" in steps[2]["orchestration_text"]
    assert "peer-critique artifact attached" in steps[4]["orchestration_text"]
    assert "[defense artifact]" in chair["orchestration_text"]
