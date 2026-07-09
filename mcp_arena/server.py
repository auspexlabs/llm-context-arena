"""MCP server exposing LLM Context Arena as agent tools."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from .client import ArenaClient

mcp = FastMCP(
    "llm-context-arena",
    instructions=(
        "LLM Context Arena control plane. Use index tools before deliberation on code. "
        "Prefer create_turn + advance_turn for stepwise council runs; send_message for full turns. "
        "Stage 1 spread and stage 2 aggregate_rankings are first-class disagreement signals."
    ),
)

_client: Optional[ArenaClient] = None


def _get_client() -> ArenaClient:
    global _client
    if _client is None:
        _client = ArenaClient()
    return _client


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def arena_health() -> str:
    """Check backend availability."""
    return _json(await _get_client().health())


@mcp.tool()
async def list_conversations() -> str:
    """List conversation metadata (id, title, mode, cost)."""
    return _json(await _get_client().list_conversations())


@mcp.tool()
async def create_conversation(mode: str = "council") -> str:
    """Create a new deliberation conversation. Mode: council, fight, stacks, round_robin, etc."""
    return _json(await _get_client().create_conversation(mode=mode))


@mcp.tool()
async def get_conversation(conversation_id: str) -> str:
    """Fetch full conversation including message history and arena results."""
    return _json(await _get_client().get_conversation(conversation_id))


@mcp.tool()
async def send_message(
    conversation_id: str,
    content: str,
) -> str:
    """Run a full arena turn (all stages). Returns stage1, stage2, stage3, metadata."""
    return _json(await _get_client().send_message(conversation_id, content))


@mcp.tool()
async def create_turn(conversation_id: str, content: str) -> str:
    """Start an agent turn: prepare context, persist checkpoint. Council mode only."""
    return _json(await _get_client().create_turn(conversation_id, content))


@mcp.tool()
async def advance_turn(conversation_id: str, turn_id: str) -> str:
    """Advance council turn by one step: stage1, stage2, or stage3."""
    return _json(await _get_client().advance_turn(conversation_id, turn_id))


@mcp.tool()
async def get_turn(conversation_id: str, turn_id: str) -> str:
    """Poll turn state. Complete turns include full execution payload."""
    return _json(await _get_client().get_turn(conversation_id, turn_id))


@mcp.tool()
async def cancel_turn(conversation_id: str, turn_id: str) -> str:
    """Cancel an in-progress turn."""
    return _json(await _get_client().cancel_turn(conversation_id, turn_id))


@mcp.tool()
async def run_council_turn(conversation_id: str, content: str) -> str:
    """Convenience: create_turn then advance through all three council steps."""
    client = _get_client()
    created = await client.create_turn(conversation_id, content)
    turn_id = created["turn"]["turn_id"]
    turn = created["turn"]
    advanced = created
    while turn.get("next_step") in {"stage1", "stage2", "stage3"}:
        advanced = await client.advance_turn(conversation_id, turn_id)
        turn = advanced["turn"]
    return _json(advanced)


@mcp.tool()
async def get_index_manifest(
    conversation_id: Optional[str] = None,
    repo_root: Optional[str] = None,
) -> str:
    """Index freshness and drift. Call before deliberation; reindex if changed_since_index."""
    return _json(await _get_client().get_index_manifest(conversation_id, repo_root))


@mcp.tool()
async def reindex_git(
    conversation_id: str,
    repo_root: Optional[str] = None,
    include_untracked: Optional[bool] = None,
) -> str:
    """Snapshot git working tree and build ColBERT index for conversation."""
    return _json(
        await _get_client().reindex_git(
            conversation_id,
            repo_root=repo_root,
            include_untracked=include_untracked,
        )
    )


@mcp.tool()
async def reindex_snapshot(conversation_id: str) -> str:
    """Reindex existing conversation snapshot (ZIP upload dir)."""
    return _json(await _get_client().reindex_snapshot(conversation_id))


@mcp.tool()
async def get_repo_tree(conversation_id: str) -> str:
    """File tree for indexed conversation snapshot."""
    return _json(await _get_client().get_repo_tree(conversation_id))


@mcp.tool()
async def get_file(conversation_id: str, path: str) -> str:
    """Read a file from conversation snapshot by relative path."""
    return _json(await _get_client().get_file(conversation_id, path))


@mcp.tool()
async def search_repo(conversation_id: str, query: str, limit: int = 3) -> str:
    """Substring search across indexed repo files."""
    return _json(await _get_client().search_repo(conversation_id, query, limit=limit))


@mcp.tool()
async def resolve_path(
    conversation_id: str,
    query: str,
    user_query: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Resolve fuzzy path matches; optional rerank with user_query."""
    return _json(
        await _get_client().resolve_path(
            conversation_id,
            query,
            user_query=user_query,
            limit=limit,
        )
    )


@mcp.tool()
async def get_settings() -> str:
    """Runtime settings: arena_models, chairman_model, repo_root, squad."""
    return _json(await _get_client().get_settings())


@mcp.tool()
async def update_settings(
    arena_models: Optional[List[str]] = None,
    chairman_model: Optional[str] = None,
    theme: Optional[str] = None,
    repo_root: Optional[str] = None,
) -> str:
    """Update runtime settings persisted to data/config.json."""
    fields: Dict[str, Any] = {}
    if arena_models is not None:
        fields["arena_models"] = arena_models
    if chairman_model is not None:
        fields["chairman_model"] = chairman_model
    if theme is not None:
        fields["theme"] = theme
    if repo_root is not None:
        fields["repo_root"] = repo_root
    return _json(await _get_client().update_settings(**fields))


def main() -> None:
    transport = os.getenv("ARENA_MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        host = os.getenv("ARENA_MCP_HOST", "127.0.0.1")
        port = int(os.getenv("ARENA_MCP_PORT", "8010"))
        mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    main()