# Curia contributor notes

Curia is a multi-model deliberation service with an observability-first web client,
repository grounding, and an MCP control plane. This file is a compact orientation
guide; durable architecture and policy choices belong in
[`docs/decision_log.md`](docs/decision_log.md).

## Working agreements

- Preserve the canonical execution trace and prompt-provenance contracts when adding
  or changing a deliberation mode.
- Treat conversation JSON as the source of truth. SQLite session data is a rebuildable
  query projection.
- Never summarize retrieved RAG material merely to fit a model budget. Retrieval and
  conversation-memory compression are separate concerns.
- Keep route modules thin. Orchestration belongs in the arena/run-turn layer; storage
  invariants belong in `StorageService` and its projections.
- Add decisions, incidents, pivots, and explicit deferrals to the append-only decision
  log using its existing format.
- Do not commit `.env`, conversation data, repository snapshots, model indexes, or
  local observability artifacts.

## Runtime map

| Boundary | Location | Responsibility |
|---|---|---|
| API assembly | `backend/main.py` | FastAPI construction, routers, local CORS |
| Deliberation | `backend/arena.py`, `backend/run_turn.py` | Mode execution and turn lifecycle |
| API routes | `backend/routes/` | HTTP contracts for conversations, sessions, settings, execution, and repositories |
| Canonical storage | `backend/storage_service.py` | Atomic conversation mutations and turn persistence |
| Session projection | `backend/session_catalog.py`, `backend/session_projection.py` | Searchable, recoverable SQLite catalog |
| Grounding | `backend/rag_lmstudio.py` and retrieval modules | Snapshot indexing and code-context retrieval |
| Trace contracts | `backend/execution_trace.py`, `backend/prompt_provenance.py` | Mode-neutral topology and exact injected artifacts |
| Observatory | `frontend/src/deck/` | Turn, session, context, cost, quality, and provenance views |
| Agent control | `mcp_arena/` | MCP tools over the HTTP API |

The backend listens on port 8001 by default and the Vite client on port 5173.
`./start.sh` starts both processes and cleans them up together.

## Deliberation modes

- **Council:** parallel answers, anonymous peer ranking, chair synthesis.
- **Round Robin:** sequential refinement with explicit predecessor handoffs.
- **Fight:** opening positions, peer critique, defense, and chair synthesis.
- **Stacks:** pair generation followed by merge, attack, judgment, defense, and final.
- **Complex Iterative:** alternating extraction and expansion.
- **Complex Questioning:** answers, reflective questions, synthesis, muse, and final.

Each runner must emit the canonical trace contract. If a stage receives Curia-owned
instructions or a previous model artifact, record that exact composition in prompt
provenance. RAG content is referenced by retrieval event, not copied into provenance.

## Local development

```bash
uv sync
cd frontend && npm install && cd ..
cp .env.example .env
./start.sh
```

Useful checks before committing:

```bash
uv run pytest
cd frontend && npm run build
```

Tests marked `eval` load local retrieval models and are intentionally separate from the
normal fast suite. Use `python -m backend.main` when starting only the API; running a
backend module from inside `backend/` will break package-relative imports.

## Licensing boundary

The independently implemented current Curia tree is released under Apache-2.0. See
[`LICENSING.md`](LICENSING.md), [`LICENSE`](LICENSE), and [`NOTICE`](NOTICE). Generated
dependency locks and conventional tool scaffolding follow their generators and listed
dependencies; do not paste unlicensed third-party implementation into the repository.
