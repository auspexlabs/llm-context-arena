# Agent control plane architecture

**Status:** implemented (Phase 0 plumbing + Phase 1 council API + MCP Phase 0)  
**Related:** [`piv-001-agent-control-plane.md`](piv-001-agent-control-plane.md), [`piv-001-checklist.md`](piv-001-checklist.md)

---

## Design intent

The arena is a **deliberation protocol engine**, not a chat widget. External agents drive turns; the UI (and MCP clients) observe structured disagreement: stage-1 spread, stage-2 rankings, chairman synthesis.

Two surfaces share one backend contract:

| Surface | Role | Transport |
|---------|------|-----------|
| **HTTP API** (`:8001`) | Control plane source of truth | REST + SSE |
| **MCP server** (`arena-mcp`) | IDE/CI agent ergonomics | stdio (default) or SSE |

MCP is a **thin HTTP client** — no duplicated arena logic.

---

## Layer diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Drivers: Cursor MCP, CLI, CI, supervisor LLM              │
└───────────────┬─────────────────────────┬─────────────────┘
                │ MCP tools               │ REST / SSE
┌───────────────▼──────────┐   ┌──────────▼──────────────────┐
│ mcp_arena/server.py      │   │ backend/main.py             │
│  └─ mcp_arena/client.py  │──►│  ├─ run_turn()              │
└──────────────────────────┘   │  ├─ routes/turns.py          │
                               │  └─ existing RAG/settings    │
                               └──────────┬──────────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
             turn_service.py        arena.py            ContextEngine
             turn_store.py          (stage fns)         RAGProvider
```

---

## Core modules

### `backend/run_turn.py`

Single entry for **full turns** (sync message API, stream runner, MCP `send_message`).

- Prepares context via `ContextEngine` (unless `prepared_ctx` passed — stream path avoids double RAG)
- Runs `run_full_arena()`
- Builds `ArenaExecution` → `to_response_dict()`
- Split persistence: `persist_user` / `persist_assistant` for SSE finalize

### `backend/turn_service.py` + `backend/turn_store.py`

**Stepwise council** for agents that want stage boundaries.

Turn sidecar: `data/conversations/turns/{conversation_id}/{turn_id}.json`

| `step_index` | After advance | `status` |
|--------------|---------------|----------|
| 0 | (created) | `pending` |
| 1 | stage1 answers | `stage1_complete` |
| 2 | peer rankings | `stage2_complete` |
| 3 | chairman synthesis | `complete` |

Checkpoint holds everything needed to resume: augmented prompt, per-model prompts, context maps, directives.

### `backend/routes/turns.py`

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/conversations/{id}/turns` | Create turn (context prep only) |
| `POST` | `/api/conversations/{id}/turns/{tid}/advance` | Run next council step |
| `GET` | `/api/conversations/{id}/turns/{tid}` | Poll state |
| `DELETE` | `/api/conversations/{id}/turns/{tid}` | Cancel |
| `GET` | `/api/conversations/{id}/turns` | List turns |

Agent attribution: `X-Agent-Id` header on create.

### `mcp_arena/`

| File | Purpose |
|------|---------|
| `client.py` | Async httpx wrapper |
| `server.py` | FastMCP tool registry |

Env:

- `ARENA_API_URL` — backend base (default `http://127.0.0.1:8001`)
- `ARENA_AGENT_ID` — sent as `X-Agent-Id`
- `ARENA_MCP_TRANSPORT` — `stdio` (default) or `sse`

Run: `uv run arena-mcp` or `uv run python -m mcp_arena.server`

---

## MCP tool map

| Tool | HTTP endpoint |
|------|---------------|
| `arena_health` | `GET /` |
| `list_conversations` | `GET /api/conversations` |
| `create_conversation` | `POST /api/conversations` |
| `get_conversation` | `GET /api/conversations/{id}` |
| `send_message` | `POST /api/conversations/{id}/message` |
| `create_turn` | `POST /api/conversations/{id}/turns` |
| `advance_turn` | `POST .../turns/{tid}/advance` |
| `get_turn` / `cancel_turn` | `GET` / `DELETE` turn |
| `run_council_turn` | create + 3× advance (convenience) |
| `get_index_manifest` | `GET /api/index_manifest` |
| `reindex_git` / `reindex_snapshot` | reindex routes |
| `get_repo_tree` / `get_file` / `search_repo` / `resolve_path` | repo tools |
| `get_settings` / `update_settings` | settings |

---

## Agent workflow (recommended)

1. `get_index_manifest(conversation_id, repo_root)` — if stale, `reindex_git`
2. `create_conversation(mode="council")` or reuse existing
3. **Option A — full turn:** `send_message` or `run_council_turn`
4. **Option B — stepwise:** `create_turn` → `advance_turn` × 3, inspect rankings after step 2 before chairman
5. Read `aggregate_rankings` and raw stage-2 evaluations before trusting stage-3

---

## Cursor MCP config snippet

```json
{
  "mcpServers": {
    "llm-context-arena": {
      "command": "uv",
      "args": ["run", "arena-mcp"],
      "cwd": "/home/phaze/PycharmProjects/llm-council-rag",
      "env": {
        "ARENA_API_URL": "http://127.0.0.1:8001",
        "ARENA_AGENT_ID": "cursor"
      }
    }
  }
}
```

Backend must be running (`uv run python -m backend.main`).

---

## Deferred (Phase 2+)

- `await_user` + `POST .../resume`
- `GET .../events` SSE subscribe without sending
- Step checkpoints for fight/stacks/complex modes
- `expand_trace` tool (DEF-003)
- Client abort → cancel in-flight arena task
- Python agent SDK (thin wrapper over `mcp_arena/client.py`)

---

## Phase 1.5 — Economics layer (DEC-018)

Catalog, frozen config, summarizer service, prompt registry, component token budgets, and metrics instrumentation. Extends the control plane so agents see honest per-model limits and inspectable system injections before accepting a turn.

**Design doc:** [`dec-018-catalog-config-summarizer.md`](dec-018-catalog-config-summarizer.md)  
**Checklist:** [`piv-001-checklist.md`](piv-001-checklist.md) → Phase 1.5  
**Ledger:** `DEC-018`, `DEF-005`–`DEF-009`

---

## Decision record

See `docs/decision_log.md` — `DEC-015` (control plane), `DEC-016` (failures), `DEC-017` (execution_quality), `DEC-018` (catalog/config/summarizer).