#!/usr/bin/env python3
"""Dogfood Bayence-Certus via Arena HTTP API (MCP client surface)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp_arena.client import ArenaClient

BAYENCE_ROOT = "/home/phaze/PycharmProjects/Bayence-Certus/"
EXISTING_CONVO = "38198b96-b929-4422-ae9e-e5c85402cbcc"


def _short(obj, limit=1200) -> str:
    text = json.dumps(obj, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + "\n…"


async def ensure_index(client: ArenaClient, conversation_id: str) -> dict:
    manifest = await client.get_index_manifest(conversation_id, BAYENCE_ROOT)
    delta = manifest.get("changed_since_index") or {}
    if delta.get("needs_reindex") or not manifest.get("has_index", True):
        print("Reindexing…", file=sys.stderr)
        result = await client.reindex_git(conversation_id, repo_root=BAYENCE_ROOT)
        print(_short(result, 400), file=sys.stderr)
        manifest = await client.get_index_manifest(conversation_id, BAYENCE_ROOT)
    return manifest


async def run_round_robin(client: ArenaClient, conversation_id: str) -> dict:
    conv = await client.create_conversation(mode="round_robin")
    cid = conv["id"]
    await ensure_index(client, cid)
    print(f"\n=== Round Robin convo {cid} ===", file=sys.stderr)
    query = (
        "@cite Tell me about the authentication and session handling in this codebase. "
        "What are the main entry points and how does a request get authorized?"
    )
    result = await client.send_message(cid, query)
    steps = (result.get("metadata") or {}).get("steps") or []
    models = [s.get("model") for s in steps]
    print("steps:", len(steps), "models:", models, file=sys.stderr)
    return {"conversation_id": cid, "mode": "round_robin", "result": result}


async def run_fight(client: ArenaClient, conversation_id: str) -> dict:
    conv = await client.create_conversation(mode="fight")
    cid = conv["id"]
    await ensure_index(client, cid)
    print(f"\n=== Fight convo {cid} ===", file=sys.stderr)
    query = (
        "We need to modify how API errors are returned to clients. "
        "Propose two opposing approaches: (A) wrap all errors in a unified JSON envelope "
        "with error codes, vs (B) keep HTTP status codes semantic and return minimal bodies. "
        "Which is the right way to modify the error-handling layer in this repo?"
    )
    result = await client.send_message(cid, query)
    steps = (result.get("metadata") or {}).get("steps") or []
    by_role: dict[str, list] = {}
    for s in steps:
        by_role.setdefault(s.get("role", "?"), []).append(s.get("model"))
    print("steps by role:", {k: len(v) for k, v in by_role.items()}, file=sys.stderr)
    return {"conversation_id": cid, "mode": "fight", "result": result}


async def fetch_history(client: ArenaClient, conversation_id: str) -> dict:
    return await client.get_conversation(conversation_id)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-robin", action="store_true")
    parser.add_argument("--fight", action="store_true")
    parser.add_argument("--history", metavar="CONVO_ID")
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()

    client = ArenaClient(agent_id="dogfood-cli")
    base = EXISTING_CONVO

    manifest = await ensure_index(client, base)
    print("Index:", _short({
        "conversation_id": base,
        "chunk_count": manifest.get("chunk_count"),
        "needs_reindex": (manifest.get("changed_since_index") or {}).get("needs_reindex"),
    }, 300))

    if args.index_only:
        return

    out = {"manifest": manifest, "runs": []}

    if args.history:
        hist = await fetch_history(client, args.history)
        print(_short({
            "id": hist["id"],
            "mode": hist.get("mode"),
            "messages": len(hist.get("messages", [])),
            "last_assistant": hist.get("messages", [{}])[-1] if hist.get("messages") else None,
        }))
        return

    if args.round_robin or not (args.fight):
        out["runs"].append(await run_round_robin(client, base))

    if args.fight or not (args.round_robin):
        out["runs"].append(await run_fight(client, base))

    for run in out["runs"]:
        r = run["result"]
        meta = r.get("metadata") or {}
        print(_short({
            "conversation_id": run["conversation_id"],
            "mode": run["mode"],
            "stage3_preview": (r.get("stage3") or {}).get("response", "")[:500],
            "step_count": len(meta.get("steps") or []),
            "cost": meta.get("cost"),
            "context_sources": len(r.get("context_sources") or []),
        }))


if __name__ == "__main__":
    asyncio.run(main())