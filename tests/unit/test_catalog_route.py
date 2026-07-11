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