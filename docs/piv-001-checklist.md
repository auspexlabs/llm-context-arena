# PIV-001 implementation checklist

Companion to [`piv-001-agent-control-plane.md`](piv-001-agent-control-plane.md). Check boxes as work lands; do not duplicate into `decision_log.md`.

---

## Phase 0 — Quick wins (unblock prototyping)

### Bugs / jank (watch mode blockers)
- [ ] Pass `repoRoot` from `App.jsx` → `ChatInterface` (git reindex + freshness broken in chat)
- [ ] Normalize SSE `mode_progress` (`current` vs `completed`) in `arena.py` + frontend consumers
- [ ] Fight / stacks / round_robin: stop overloading `stage1` with all pipeline steps; use `metadata.steps` for timeline
- [ ] Client abort (`AbortController`) should cancel backend arena task, not orphan in-flight runs
- [ ] Deduplicate directive parsing: remove `ChatInterface.parseDirectives()` divergence from `backend/directives.py`

### Agent-adjacent plumbing
- [ ] Extract shared `run_turn()` from `send_message()` + `send_message_stream()` (`backend/main.py`)
- [ ] Use `ArenaExecution.to_response_dict()` (`backend/models.py`) for sync + stream final payloads
- [ ] Wire `@temp` / `@maxtokens` from `ParsedDirectives` → `query_model()` (`openrouter.py`)
- [ ] Attach `@trace` payload to assistant metadata (context_sources, router category, fusion flags)
- [ ] Emit per-model progress in `stage2_collect_rankings()` (`arena.py`)
- [ ] Document Phase 0 tools in OpenAPI comments: manifest, reindex, repo_tree, file, search, settings

---

## Phase 1 — Turn state + step API (council first)

### Data model
- [ ] Turn record: `turn_id`, `status`, `step_index`, `mode`, `agent_id`, `await_reason`, `await_prompt`
- [ ] Persist partial steps to conversation / turn sidecar (crash-safe)
- [ ] Serializable checkpoint for `run_mode_council()` (label map, stage outputs)

### API
- [ ] `POST /api/conversations/{id}/turns` — agent-initiated turn
- [ ] `POST /api/conversations/{id}/turns/{turn_id}/advance` — single step
- [ ] `GET /api/conversations/{id}/turns/{turn_id}` — poll state
- [ ] `DELETE /api/conversations/{id}/turns/{turn_id}` — cancel

### Agent tools (wrap existing + new)
- [ ] `prepare_context` → `ContextEngine.prepare_context()`
- [ ] `get_index_manifest` / `reindex` / `reindex_git`
- [ ] `get_repo_tree` / `get_file` / `search_repo` / `resolve_path`
- [ ] `get_settings` / `update_settings`

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