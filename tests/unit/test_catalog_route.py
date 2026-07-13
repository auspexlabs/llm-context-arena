"""Tests for catalog API routes (DEC-018 Phase B)."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_config_validate_endpoint(client):
    resp = client.get("/api/catalog/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


def test_effective_limits_endpoint(client):
    resp = client.get("/api/catalog/effective-limits")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data


def test_catalog_models_endpoint(client):
    resp = client.get("/api/catalog/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert data["count"] >= 1


def test_patch_catalog_model_endpoint(tmp_path, monkeypatch):
    catalog_path = tmp_path / "model_catalog.yaml"
    catalog_path.write_text(
        "version: 1\nmodels:\n  test/patch-model:\n    tags: []\n    registered_limit: 1000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("backend.catalog_editor.MODEL_CATALOG_PATH", catalog_path)
    monkeypatch.setattr("backend.catalog_editor.clear_frozen_cache", lambda: None)

    from backend.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.patch(
        "/api/catalog/models/test/patch-model",
        json={"tags": ["free"], "model_modifier": 0.75},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["entry"]["tags"] == ["free"]
    assert data["entry"]["model_modifier"] == 0.75