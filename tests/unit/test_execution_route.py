"""Tests for opt-in execution detail route."""

from fastapi.testclient import TestClient

from backend.main import app


def test_message_execution_failures_only(tmp_path, monkeypatch):
    from backend.dependencies import get_storage_service
    from backend.storage_service import StorageService

    storage = StorageService(data_dir=str(tmp_path / "conversations"))
    conv = storage.create_conversation("c1", mode="fight")
    storage.add_user_message("c1", "test")
    storage.add_assistant_message(
        "c1",
        [],
        [],
        {"model": "chair", "response": "done"},
        metadata={
            "mode": "fight",
            "model_failures": [
                {
                    "model": "qwen/qwen3-coder:free",
                    "stage": "stage1",
                    "role": "answer",
                    "status": 429,
                    "message": "rate limited",
                }
            ],
        },
    )

    app.dependency_overrides[get_storage_service] = lambda: storage
    client = TestClient(app)
    try:
        resp = client.get("/api/conversations/c1/messages/1/execution")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["model_failures"]) == 1
        assert data["model_failures"][0]["status"] == 429
    finally:
        app.dependency_overrides.clear()