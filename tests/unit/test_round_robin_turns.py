"""Tests for round robin turn metadata."""

import pytest

from backend.arena import run_mode_round_robin


@pytest.mark.asyncio
async def test_round_robin_chains_prior_draft(monkeypatch):
    calls = []

    async def fake_query(model, messages, timeout=120.0, log_error=True):
        content = messages[0]["content"]
        calls.append(content)
        if model == "m1":
            return {"content": "DRAFT_A", "usage": {}}
        if model == "m2":
            return {"content": "DRAFT_B", "usage": {}}
        return {"content": "CHAIR", "usage": {}}

    monkeypatch.setattr("backend.arena.query_model", fake_query)

    drafts, _, stage3, meta = await run_mode_round_robin(
        "What is auth?",
        {"m1": "ctx+Q", "m2": "ctx+Q"},
        ["m1", "m2"],
        "chair",
    )

    assert len(drafts) == 2
    assert drafts[0]["had_prior_draft"] is False
    assert drafts[0]["prior_draft"] is None
    assert drafts[1]["had_prior_draft"] is True
    assert drafts[1]["prior_draft"] == "DRAFT_A"
    assert "DRAFT_A" in calls[1]
    assert "(none yet)" not in calls[1]
    assert "Prior draft:" in drafts[1]["prompt_preview"]
    assert stage3["response"] == "CHAIR"