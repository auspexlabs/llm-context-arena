"""MCP server exposing Curia as agent tools."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from backend.catalog_refresh import refresh_catalog, validate_frozen_config
from backend.dependencies import load_runtime_settings
from backend.observations import get_observation_service
from backend.prompts import get_prompt, list_prompts
from backend.squad_presets import load_squad_preset

from .client import ArenaClient
from .env import env_int_prefixed, env_prefixed
from .quality import enrich_turn_payload, enrich_turn_record

mcp = FastMCP(
    "curia",
    instructions=(
        "Curia control plane — multi-model deliberation with code RAG. "
        "Use index tools before deliberation on code. "
        "Prefer create_turn + advance_turn for stepwise council runs; send_message for full turns. "
        "Always read execution_quality.acceptable and agent_notice — if acceptable is false, "
        "inform the user and retry; do not present partial deliberation as success. "
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
    """Run a full arena turn (all stages). Returns stage1, stage2, stage3, metadata, execution_quality."""
    payload = enrich_turn_payload(await _get_client().send_message(conversation_id, content))
    return _json(payload)


@mcp.tool()
async def create_turn(conversation_id: str, content: str) -> str:
    """Start an agent turn: prepare context, persist checkpoint. Council mode only."""
    return _json(await _get_client().create_turn(conversation_id, content))


@mcp.tool()
async def advance_turn(conversation_id: str, turn_id: str) -> str:
    """Advance council turn by one step: stage1, stage2, or stage3."""
    payload = enrich_turn_record(await _get_client().advance_turn(conversation_id, turn_id))
    return _json(payload)


@mcp.tool()
async def get_turn(conversation_id: str, turn_id: str) -> str:
    """Poll turn state. Complete turns include full execution payload."""
    payload = enrich_turn_record(await _get_client().get_turn(conversation_id, turn_id))
    return _json(payload)


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
    return _json(enrich_turn_record(advanced))


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
async def ensure_indexed(
    conversation_id: str,
    repo_root: Optional[str] = None,
) -> str:
    """Reindex conversation from git when stale; safe to call before deliberation."""
    return _json(
        await _get_client().ensure_indexed(conversation_id, repo_root=repo_root)
    )


@mcp.tool()
async def get_message_execution(
    conversation_id: str,
    message_index: int,
    include: str = "failures,prompts,cost,context,steps",
) -> str:
    """Opt-in execution detail for a stored assistant message (history by index)."""
    return _json(
        await _get_client().get_message_execution(
            conversation_id, message_index, include=include
        )
    )


@mcp.tool()
async def list_system_prompts(mode: Optional[str] = None) -> str:
    """List registered system prompts (metadata; no templates). Optional mode filter."""
    return _json({"prompts": list_prompts(mode=mode)})


@mcp.tool()
async def get_system_prompt(prompt_id: str) -> str:
    """Return one system prompt including template."""
    entry = get_prompt(prompt_id)
    if entry is None:
        return _json({"error": f"Unknown prompt_id: {prompt_id}"})
    return _json(
        {
            "prompt_id": entry.prompt_id,
            "version": entry.version,
            "mode": entry.mode,
            "variables": list(entry.variables),
            "description": entry.description,
            "template": entry.template,
        }
    )


@mcp.tool()
async def catalog_refresh(force: bool = False, dry_run: bool = False) -> str:
    """Pull OpenRouter registered limits into model_catalog.yaml."""
    return _json(await refresh_catalog(force=force, dry_run=dry_run))


@mcp.tool()
async def catalog_effective_limits(squad: Optional[str] = None) -> str:
    """Show effective limits and pending observations for a squad or current settings."""
    if squad:
        preset = load_squad_preset(squad)
        model_ids = list(preset["arena_models"])
        squad_name = squad
    else:
        settings = load_runtime_settings()
        model_ids = list(settings.get("arena_models") or [])
        squad_name = settings.get("arena_squad")
    return _json(get_observation_service().effective_limits_report(model_ids, squad_name=squad_name))


@mcp.tool()
async def list_pending_observations(squad: Optional[str] = None) -> str:
    """List pending limit observations awaiting user acceptance."""
    model_ids: List[str] = []
    if squad:
        preset = load_squad_preset(squad)
        model_ids = list(preset["arena_models"])
    pending = get_observation_service().pending_for_models(model_ids)
    return _json({"pending": [p.to_dict() for p in pending], "count": len(pending)})


@mcp.tool()
async def accept_observation(observation_id: int) -> str:
    """Accept a pending limit observation — promotes to live observed_limit."""
    accepted = get_observation_service().accept(observation_id)
    if accepted is None:
        return _json({"ok": False, "error": f"Pending observation {observation_id} not found"})
    return _json({"ok": True, "observation": accepted.to_dict()})


@mcp.tool()
async def decline_observation(observation_id: int) -> str:
    """Decline a pending limit observation."""
    ok = get_observation_service().decline(observation_id)
    return _json({"ok": ok})


@mcp.tool()
async def sweep_expired_observations() -> str:
    """Archive expired accepted observations and return models needing re-verification."""
    return _json(get_observation_service().sweep_expired_observations())


@mcp.tool()
async def config_validate() -> str:
    """Validate arena_config.yaml and model_catalog.yaml against frozen schemas."""
    ok, issues = validate_frozen_config()
    return _json({"ok": ok, "issues": issues})


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
    transport = env_prefixed("CURIA_MCP_TRANSPORT", "ARENA_MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        host = env_prefixed("CURIA_MCP_HOST", "ARENA_MCP_HOST", "127.0.0.1")
        port = env_int_prefixed("CURIA_MCP_PORT", "ARENA_MCP_PORT", 8010)
        mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    main()