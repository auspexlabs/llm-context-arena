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

## Phase 1.5 — Catalog, frozen config, summarizer, prompts (DEC-018)

**Design doc:** [`dec-018-catalog-config-summarizer.md`](dec-018-catalog-config-summarizer.md)

### Config & catalog
- [x] `arena_config.yaml` + `model_catalog.yaml` (Pydantic + FREEZE loader — one read per PID)
- [x] OpenRouter catalog refresh → registered limits; tag modifiers (`free`, extensible)
- [x] Observation store: pending / accepted / archived tables; 10% delta gate; 60-day re-verify
- [x] CLI/MCP: `catalog refresh`, `catalog effective-limits`, `config validate`, plan-selection observation warnings

### Summarizer & budget
- [x] `summarizer_model` + chairman fallback log; `SummarizeJob` metadata
- [x] Per-model threshold summarize; pool concurrency `len(arena)-1`
- [x] `PromptComponentBudget` + `BudgetDecision` per turn (rag/system/mode/turn/user)
- [x] RAG pre-cap (modest default chunk count); AST-boundary merge before summarize
- [x] Summarizer modes: `context.rag`, `context.user`, `mid_turn.semantic` (distinct `prompt_id`s)
- [x] Prompt registry + API/MCP expose; wire metrics counters (DEF-006 instrumentation only)

### Quality (extend DEC-017)
- [x] `execution_quality` + `agent_notice` on API/MCP
- [x] Attach summarize failures, budget decisions, observation flags to `execution_quality`

**Defers:** `DEF-005` synthesis model · `DEF-006` Prom stack · `DEF-007` Graph+N · `DEF-008` UI catalog editor · `DEF-009` ContentChecker OSS

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

### Frontend (watch-first) — PIV-002a in progress
- [x] Greenfield observation deck shell (`frontend/src/deck/`, vanilla TS + Vite)
- [x] Rail · Deck · Inspector layout (locked spec); council stage viewers ported
- [x] Take control toggle + stream bridge (decoupled from legacy `ChatInterface`)
- [ ] Default read-only enforced (composer only when Take control on — partial)
- [ ] `await_user` banner + reply box (distinct from new deliberation) — PIV-002b
- [x] Execution dashboard primary: timeline, step viewport, inspector (context/rankings/quality)
- [ ] Agent attribution on turns (when `X-Agent-Id` present)
- [ ] Settings/catalog panel port from React `CatalogEditor` — PIV-002a follow-up

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
| Context | `backend/context_engine.py`, `backend/directives.py`, `backend/budget.py`, `backend/execution_quality.py` |
| Catalog (DEC-018) | `data/arena_config.yaml`, `data/model_catalog.yaml` (planned) |
| Models | `backend/models.py` |
| Storage | `backend/storage.py`, `backend/storage_service.py` |
| OpenRouter | `backend/openrouter.py` |
| UI | `frontend/src/App.jsx`, `frontend/src/components/ChatInterface.jsx`, `Sidebar.jsx` |
| Deferred | `docs/decision_log.md` DEF-003, DEF-004 |