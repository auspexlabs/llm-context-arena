"""Tests for MCP HTTP client."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_arena.client import ArenaClient


@pytest.mark.asyncio
async def test_create_turn_sends_agent_header():
    client = ArenaClient(base_url="http://test", agent_id="cursor-agent")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = {"turn": {"turn_id": "t1"}}

    mock_http = AsyncMock()
    mock_http.request = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("mcp_arena.client.httpx.AsyncClient", return_value=mock_http):
        result = await client.create_turn("conv-1", "hello")

    assert result["turn"]["turn_id"] == "t1"
    call_kwargs = mock_http.request.call_args.kwargs
    assert call_kwargs["headers"]["X-Agent-Id"] == "cursor-agent"
    body = call_kwargs["json"]
    assert body["content"] == "hello"