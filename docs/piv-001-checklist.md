# PIV-001 implementation checklist

Companion to [`piv-001-agent-control-plane.md`](piv-001-agent-control-plane.md). Check boxes as work lands; do not duplicate into `decision_log.md`.

---

## BLOCKER — Mode turn routing (DIS-002) — do before agent API

See [`dis-002-mode-turn-routing.md`](dis-002-mode-turn-routing.md). **Remediated by DEC-014** (2026-07-07).

- [x] **Streaming:** per-step SSE (`step_complete`), not one `stage1_complete` after full runner
- [x] **Backend return contract:** separate `execution.steps` from council `stage1`/`stage2`; stop stuffing fight/stacks/RR into `stage1`
- [x] **Progress:** unified `step_index`/`step_total`; fix parallel `stage1_collect_responses` counter; every progress event carries `step`
- [x] **UI mode router:** council → Stage1/2/3; advanced modes → RoundTrack + role panels (hide misleading Stage1)
- [x] **RoundTrack sync:** stable step ids; fix focus jump to Stage1/tab (`__idx`)
- [x] **Fight-only transcript:** generalize or remove duplicate partial UI
- [x] **Council metadata.steps:** include real rankings content or drop empty stub

**Agent `POST /turns/advance` may proceed on the normalized contract (PIV-001 Phase 1).**

---

## Phase 0 — Quick wins (unblock prototyping)

### Bugs / jank (watch mode blockers)
- [x] Pass `repoRoot` from `App.jsx` → `ChatInterface` (git reindex + freshness broken in chat)
- [x] Normalize SSE `mode_progress` (`current` vs `completed`) in `arena.py` + frontend consumers
- [x] Fight / stacks / round_robin: stop overloading `stage1` with all pipeline steps; use `metadata.steps` for timeline
- [ ] Client abort (`AbortController`) should cancel backend arena task, not orphan in-flight runs
- [ ] Deduplicate directive parsing: remove `ChatInterface.parseDirectives()` divergence from `backend/directives.py`

### Agent-adjacent plumbing
- [x] Extract shared `run_turn()` from `send_message()` + `send_message_stream()` (`backend/run_turn.py`)
- [x] Use `ArenaExecution.to_response_dict()` (`backend/models.py`) for sync + stream final payloads
- [ ] Wire `@temp` / `@maxtokens` from `ParsedDirectives` → `query_model()` (`openrouter.py`)
- [ ] Attach `@trace` payload to assistant metadata (context_sources, router category, fusion flags)
- [ ] Emit per-model progress in `stage2_collect_rankings()` (`arena.py`)
- [x] Document Phase 0 tools — see [`agent-control-plane-architecture.md`](agent-control-plane-architecture.md)

---

## Phase 1 — Turn state + step API (council first)

### Data model
- [x] Turn record: `turn_id`, `status`, `step_index`, `mode`, `agent_id`, `await_reason`, `await_prompt` (`backend/models.py`)
- [x] Persist partial steps to turn sidecar (`backend/turn_store.py`)
- [x] Serializable checkpoint for council stages (`TurnCheckpoint`)

### API
- [x] `POST /api/conversations/{id}/turns` — agent-initiated turn
- [x] `POST /api/conversations/{id}/turns/{turn_id}/advance` — single step (council)
- [x] `GET /api/conversations/{id}/turns/{turn_id}` — poll state
- [x] `DELETE /api/conversations/{id}/turns/{turn_id}` — cancel

### Agent tools (wrap existing + new)
- [ ] `prepare_context` → standalone MCP tool (context prep is implicit in create_turn today)
- [x] `get_index_manifest` / `reindex` / `reindex_git` (MCP)
- [x] `get_repo_tree` / `get_file` / `search_repo` / `resolve_path` (MCP)
- [x] `get_settings` / `update_settings` (MCP)

---

## Phase 2 — `await_user` + observatory UI

### Backend
- [ ] Detect chairman / supervisor “need input” → `status: await_user` + structured question
- [ ] `POST .../turns/{id}/resume` with human reply + optional manual context
- [ ] Block concurrent turns while `await_user`
- [ ] `GET /api/conversations/{id}/events` — SSE subscribe without sending a message

### Frontend (watch-first)
- [ ] Default read-only; explicit “human override” for send
- [ ] `await_user` banner + reply box (distinct from new deliberation)
- [ ] Execution dashboard primary: timeline, progress, stage tabs, context trace
- [ ] Agent attribution on turns (when `X-Agent-Id` present)
- [ ] Decouple SSE consumer from `handleSendMessage()` in `App.jsx`

---

## Phase 3 — Full pivot

- [ ] Step checkpoints for all six `MODE_RUNNERS` (`arena.py`)
- [ ] `POST /api/conversations/{id}/expand_trace` — resolves **DEF-003**
- [ ] Tool registry + `@noexecute` enforcement
- [ ] Agent SDK (Python minimum)
- [ ] Multi-agent supervisor (out of scope until Phase 2 stable)

---

## File index

| Area | Paths |
|------|--------|
| API | `backend/main.py` |
| Arena | `backend/arena.py` |
| Context | `backend/context_engine.py`, `backend/directives.py`, `backend/budget.py` |
| Models | `backend/models.py` |
| Storage | `backend/storage.py`, `backend/storage_service.py` |
| OpenRouter | `backend/openrouter.py` |
| UI | `frontend/src/App.jsx`, `frontend/src/components/ChatInterface.jsx`, `Sidebar.jsx` |
| Deferred | `docs/decision_log.md` DEF-003, DEF-004 |