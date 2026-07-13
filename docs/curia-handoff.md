# Curia — agent handoff (2026-07-13)

**For the next session:** open workspace `/home/phaze/PycharmProjects/curia`, start a **new Composer/Agent chat**, and paste:

> Read `docs/curia-handoff.md` and execute **First actions** below.

---

## First actions (do these before dogfood)

```bash
cd /home/phaze/PycharmProjects/curia
git checkout main && git pull origin main
git status
```

**If handoff changes are uncommitted** (likely — shell died mid-commit during dir rename):

```bash
git add docs/curia-handoff.md docs/piv-003-curia-rebrand.md \
  docs/hyp001_results_learned.json docs/hyp002_results.json README.md
git commit -m "docs: handoff and local path ~/PycharmProjects/curia"
git push origin main
```

**Verify stack:**

```bash
uv run pytest tests/unit -q -m "not eval"   # same as CI — expect ~241 passed
cd frontend && npm run build && cd ..
./start.sh                                 # API :8001, deck :5173
```

**Update Cursor MCP** `cwd` if still pointing at `llm-council-rag`:

```json
"curia": {
  "command": "uv",
  "args": ["run", "curia-mcp"],
  "cwd": "/home/phaze/PycharmProjects/curia",
  "env": {
    "CURIA_API_URL": "http://127.0.0.1:8001",
    "CURIA_AGENT_ID": "cursor"
  }
}
```

Optional symlink so old Grok sessions resolve:

```bash
ln -sf /home/phaze/PycharmProjects/curia /home/phaze/PycharmProjects/llm-council-rag
```

---

## Where things live

| Item | Value |
|------|--------|
| **Product** | **Curia** — multi-model deliberation + code RAG |
| **GitHub** | [github.com/Auspex-Aerie/curia](https://github.com/Auspex-Aerie/curia) |
| **Local path** | `/home/phaze/PycharmProjects/curia` (renamed from `llm-council-rag` in place) |
| **License** | PolyForm Shield 1.0.0 — free to use; no competing commercial fork; **Curia Pro** reserved |
| **Ledger** | [`docs/decision_log.md`](decision_log.md) |

---

## What landed on `main` (this arc)

### PR #11 — Observatory deck (merged)

- Vanilla TS cutover: `frontend/src/deck/` (rail · deck · inspector · verdict)
- Live poll for MCP/external turns, per-step runtime timers
- Context trace (CodeRAG-first), quality panel, chairman failure → `severity: failed`
- Greptile fixes: metadata merge, DOMPurify, escapeHtml, SSE buffer, poll overlap guard, rankings XSS

### PR #12 — OSS + Curia rebrand (merged `344a506`)

- Org: `auspexlabs/llm-context-arena` → **`Auspex-Aerie/curia`**
- PolyForm Shield `LICENSE`, README refresh, GitHub Actions CI
- Rebrand tiers A–C: `curia` package, `curia-mcp`, `CURIA_*` env (`ARENA_*` aliases)
- CI: `uv sync --extra dev`, `pytest tests/unit -m "not eval"`, frontend build
- Ledger: **PIV-003**, **DEC-020**, **DEF-011** ([`piv-003-curia-rebrand.md`](piv-003-curia-rebrand.md))

### After PR #12 (local only, may be uncommitted)

- Directory renamed: `~/PycharmProjects/llm-council-rag` → **`~/PycharmProjects/curia`**
- `data/config.json` `repo_root` updated (gitignored)
- This handoff doc expanded

---

## Architecture snapshot

| Surface | Entry | Notes |
|---------|-------|-------|
| **Observatory UI** | `./start.sh` → :5173 | Watch-first; Take control for UI-driven turns |
| **HTTP API** | `:8001` | FastAPI; no auth (local/trusted only) |
| **MCP agents** | `uv run curia-mcp` | ~30 tools; thin client over API |
| **Quality gate** | `execution_quality.acceptable` | Agents must check before trusting stage 3 |

**Agent flow:** `get_index_manifest` → reindex if stale → `create_conversation` → `run_council_turn` or `create_turn` + `advance_turn` × 3. Deck live-polls external runs.

**Docs:** [`agent-control-plane-architecture.md`](agent-control-plane-architecture.md), [`piv-001-checklist.md`](piv-001-checklist.md)

---

## Next goal: MCP dogfood

User wants to **drive real work via MCP** with deck open as observer.

Suggested first tasks:

1. Index `curia` repo itself → council question about `mcp_arena/` or observatory deck
2. Verify deck shows MCP-started turn (live poll, quality panel, verdict)
3. Note friction → GitHub issue or `DEC`/`DEF` in decision log

CLI template (non-Cursor): `scripts/dogfood_bayence.py`

**Do not commit** unless asked: `.playwright-mcp/`, `observatory-deck-*.png`, `scripts/quiz_contract_rankings.py`

---

## Known gaps (not blocking dogfood)

| Item | Ref |
|------|-----|
| `await_user` / resume, watch SSE | PIV-002b |
| Agent attribution in deck (`CURIA_AGENT_ID`) | piv-001-checklist |
| Client abort → cancel backend run | piv-001-checklist |
| `prepare_context` standalone MCP tool | piv-001-checklist |
| Deep rename (`mcp_arena/`, `arena_config.yaml`) | DEF-011 |
| Free-squad 429s (Venice etc.) | operational — quality panel handles |

---

## CI / test notes

- Full unit suite locally may fail `test_hyp001` (recall thresholds) — **excluded in CI** via `@pytest.mark.eval`
- Pre-push command: `uv run pytest tests/unit -m "not eval"`

---

## Policy (from user)

When multiple branches/PRs are active: **Greptile/review fixes land on the PR’s head branch**, not a side branch. Merge feature work into the pivot branch before expecting review bots to see fixes.

---

## Prior session (orphaned)

Long Composer thread broke shell after directory rename (workspace path mismatch). Session ID for Grok resume:

```
019f33ba-78f3-75c0-ac2d-0f1517bd801a
```

Resume: `grok --resume 019f33ba-78f3-75c0-ac2d-0f1517bd801a` (or new agent + this file).

---

## Local runtime config (gitignored)

- `.env` — `OPENROUTER_API_KEY` required
- `data/config.json` — squad often `freebee9`; `repo_root` should be `/home/phaze/PycharmProjects/curia`