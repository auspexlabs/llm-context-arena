"""Council persists UI-safe orchestration text separately from grounded prompts."""

import pytest

from backend.arena import (
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
)
from backend.models import Stage3Result


@pytest.mark.asyncio
async def test_council_orchestration_omits_grounded_rag(monkeypatch):
    grounded = "# Relevant repository context (CodeRAG)\nSECRET_RAG_BODY\n\nUser question: Why?"

    async def fake_query(model, messages, timeout=120.0, log_error=True):
        return {"content": f"answer from {model}", "usage": {}}

    monkeypatch.setattr("backend.arena.query_model", fake_query)
    stage1 = await stage1_collect_responses(
        grounded,
        {"m1": grounded, "m2": grounded},
        ["m1", "m2"],
    )
    assert "SECRET_RAG_BODY" in stage1[0]["prompt_full"]
    assert "SECRET_RAG_BODY" not in stage1[0]["orchestration_text"]
    assert "attached separately" in stage1[0]["orchestration_text"]

    async def fake_parallel(models, messages):
        return {
            model: {
                "content": "Review\n\nFINAL RANKING:\n1. Response A\n2. Response B",
                "usage": {},
            }
            for model in models
        }

    monkeypatch.setattr("backend.arena.query_models_parallel", fake_parallel)
    stage2, _, _ = await stage2_collect_rankings(
        grounded,
        stage1,
        arena_models=["m1", "m2"],
    )
    assert "SECRET_RAG_BODY" in stage2[0]["prompt_full"]
    assert "SECRET_RAG_BODY" not in stage2[0]["orchestration_text"]
    assert "Response A:" in stage2[0]["orchestration_text"]
    assert stage2[0]["role"] == "rankings"

    stage3 = await stage3_synthesize_final(
        grounded,
        stage1,
        stage2,
        chairman_model="chair",
    )
    assert "SECRET_RAG_BODY" in stage3["prompt_full"]
    assert "SECRET_RAG_BODY" not in stage3["orchestration_text"]
    assert "STAGE 1 - Individual Responses" in stage3["orchestration_text"]
    assert "STAGE 2 - Peer Rankings" in stage3["orchestration_text"]
    serialized_stage3 = Stage3Result.from_dict(stage3).to_dict()
    assert serialized_stage3["orchestration_text"] == stage3["orchestration_text"]
