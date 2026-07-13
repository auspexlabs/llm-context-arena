# PIV-003: Curia rebrand

**Status:** accepted · **date:** 2026-07-13  
**Ledger:** `PIV-003`, `DEC-020`, `DEF-011` in [`decision_log.md`](decision_log.md)

---

## Pivot

Rename the product from **LLM Context Arena** to **Curia** (*the chamber where deliberation happens*) — aligned with Auspex-Aerie Latin naming (`tessera`, `auspice`, `signet`). Repository: [`Auspex-Aerie/curia`](https://github.com/Auspex-Aerie/curia).

Open-core posture unchanged: PolyForm Shield (free to use; no competing commercial fork; **Curia Pro** reserved).

---

## Rename tiers

### Tier A — user-visible (done)

- [x] `README.md`, `LICENSE`, `CHANGELOG.md`
- [x] `frontend/index.html` title
- [x] `backend/main.py` FastAPI title + health `service`
- [x] `mcp_arena/server.py` FastMCP name + instructions
- [x] `docs/agent-control-plane-architecture.md` Cursor snippet

### Tier B — packages / entry points (done)

- [x] `pyproject.toml` → `name = "curia"`
- [x] `curia-mcp` script; `arena-mcp` deprecated alias
- [x] `frontend/package.json` → `name = "curia"`
- [x] `scripts/arena_cli.py` → `prog = "curia"`
- [x] `uv.lock` regenerated

### Tier C — env vars (done; legacy aliases)

| Preferred | Legacy alias |
|-----------|--------------|
| `CURIA_API_URL` | `ARENA_API_URL` |
| `CURIA_AGENT_ID` | `ARENA_AGENT_ID` |
| `CURIA_MCP_TRANSPORT` | `ARENA_MCP_TRANSPORT` |
| `CURIA_MCP_HOST` | `ARENA_MCP_HOST` |
| `CURIA_MCP_PORT` | `ARENA_MCP_PORT` |

Implementation: `mcp_arena/env.py` (`env_prefixed`).

**Not renamed (domain terms):** `ARENA_SQUAD`, `ARENA_MODELS`, `arena_models` settings key, `data/arena_config.yaml`.

### Tier D — deferred (`DEF-011`)

- [ ] `mcp_arena/` package → `mcp_curia/` or nested layout
- [ ] `backend/arena.py` module rename
- [ ] Widespread `ARENA_MODELS` / `run_full_arena` symbol rename
- [ ] `data/arena_config.yaml` → `curia_config.yaml`

### Tier E — docs / module docstrings (deferred)

- [ ] `CLAUDE.md`, `RAG_LMSTUDIO.md`, PIV-001 intro lines
- [ ] Backend module one-line docstrings

### Tier F — external (manual)

- [ ] Developer Cursor MCP configs
- [ ] Greptile / CI app repo mapping after org transfer
- [ ] Remove `arena-mcp` script alias after grace period