"""Tests for GET /api/prompts (DEC-018 A5)."""

from fastapi.testclient import TestClient

from backend.main import app


def test_list_prompts():
    client = TestClient(app)
    resp = client.get("/api/prompts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 5
    ids = {p["prompt_id"] for p in data["prompts"]}
    assert "council.stage1" in ids


def test_list_prompts_mode_filter():
    client = TestClient(app)
    resp = client.get("/api/prompts", params={"mode": "council"})
    assert resp.status_code == 200
    ids = {p["prompt_id"] for p in resp.json()["prompts"]}
    assert "council.rank" in ids
    assert "round_robin.turn" not in ids


def test_get_prompt_includes_template():
    client = TestClient(app)
    resp = client.get("/api/prompts/rag.control")
    assert resp.status_code == 200
    body = resp.json()
    assert body["prompt_id"] == "rag.control"
    assert "Retrieval guidance" in body["template"]


def test_get_unknown_prompt_404():
    client = TestClient(app)
    resp = client.get("/api/prompts/does.not.exist")
    assert resp.status_code == 404