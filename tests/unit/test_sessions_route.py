import base64
import json

import httpx
import pytest

from backend.dependencies import get_storage_service
from backend.main import app
from backend.storage_service import StorageService


@pytest.mark.asyncio
async def test_sessions_route_filters_and_preserves_caller_origin(tmp_path):
    storage = StorageService(data_dir=str(tmp_path / "conversations"))

    async def override_storage():
        return storage

    app.dependency_overrides[get_storage_service] = override_storage
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/conversations",
                json={"mode": "fight"},
                headers={"X-Agent-Id": "codex-dogfood", "X-Curia-Origin": "mcp"},
            )
            assert created.status_code == 200

            response = await client.get(
                "/api/sessions",
                params={"mode": "fight", "caller": "codex-dogfood", "limit": 25},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["origin"] == "mcp"
        assert body["items"][0]["last_caller"] == "codex-dogfood"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sessions_route_rejects_cursor_for_another_sort(tmp_path):
    storage = StorageService(data_dir=str(tmp_path / "conversations"))
    storage.create_conversation("one")
    storage.create_conversation("two")

    async def override_storage():
        return storage

    app.dependency_overrides[get_storage_service] = override_storage
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get(
                "/api/sessions", params={"limit": 1, "sort": "created_desc"}
            )
            cursor = first.json()["next_cursor"]
            response = await client.get(
                "/api/sessions",
                params={"limit": 1, "sort": "updated_desc", "cursor": cursor},
            )
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sessions_route_rejects_cursor_with_invalid_bound_type(tmp_path):
    storage = StorageService(data_dir=str(tmp_path / "conversations"))

    async def override_storage():
        return storage

    encoded = base64.urlsafe_b64encode(
        json.dumps(["updated_desc", {"not": "bindable"}, "one"]).encode()
    ).decode().rstrip("=")
    app.dependency_overrides[get_storage_service] = override_storage
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/sessions", params={"cursor": encoded})
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_sessions_route_rejects_malformed_date_filter(tmp_path):
    storage = StorageService(data_dir=str(tmp_path / "conversations"))

    async def override_storage():
        return storage

    app.dependency_overrides[get_storage_service] = override_storage
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/sessions", params={"from": "not-a-date"})
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid from timestamp"
    finally:
        app.dependency_overrides.clear()
