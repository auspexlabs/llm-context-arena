# Curia — rolling agent handoff (2026-07-19)

Read this file before resuming go-live preparation in `/home/phaze/PycharmProjects/curia`.

## Current checkpoint

| Item | State |
|------|-------|
| **Main** | `53489c0` — PR #15 merged; current source tree is Apache-2.0 |
| **Active branch** | `docs/readme-accuracy` |
| **Open PR** | [#16 — refresh README for current Curia](https://github.com/Auspex-Aerie/curia/pull/16), draft |
| **README commit** | `0671967` — pushed to `origin/docs/readme-accuracy` |
| **This handoff** | Updated after PR #16 was opened and included on the same branch |
| **Working tree caution** | Preserve the untracked artifacts listed below |

PR #16 is a documentation-only go-live cleanup. It removes stale roadmap and licensing prose, corrects all mode/squad/configuration descriptions, documents the current Observatory and Sessions catalog, and narrows the directive table to behavior users can rely on.

### Resume actions

```bash
cd /home/phaze/PycharmProjects/curia
git fetch origin
git switch docs/readme-accuracy
git status -sb
gh pr view 16 --repo Auspex-Aerie/curia
```

If PR #16 is still open, review its checks and Greptile findings on this branch. If it has merged, fast-forward local `main` before beginning new work:

```bash
git switch main
git merge --ff-only origin/main
```

## Verification at this checkpoint

- `uv run pytest tests/unit/test_directives.py tests/unit/test_frozen_config.py -q` — **32 passed**
- `cd frontend && npm run build` — **passed**
- `git diff --check` — **passed**
- README stale-term scan — **clean** for Bicameral Mind, speculative commercial-offering language, phantom `@file:` support, unwired directives, and removed UI controls

The focused test run emits existing Pydantic v2 class-config and `langchain-community` deprecation warnings; no test failed.

## Where things live

| Item | Value |
|------|-------|
| **Product** | Curia — multi-model deliberation grounded in code |
| **GitHub** | [Auspex-Aerie/curia](https://github.com/Auspex-Aerie/curia) |
| **Local path** | `/home/phaze/PycharmProjects/curia` |
| **License** | Apache-2.0 from the source-tree boundary recorded in `LICENSING.md` and DEC-029 |
| **Decision ledger** | [`docs/decision_log.md`](decision_log.md) |
| **Backend / UI** | FastAPI `:8001` / Observatory `:5173` via `./start.sh` |
| **MCP** | `uv run curia-mcp`; 30 tools over the local HTTP API |

Curia currently has no application-level authentication. Bind it to localhost or place it behind a trusted network boundary.

## What landed in the current arc

### PR #13 — Sessions catalog (merged `08af98a`)

- Moved Sessions to a dedicated, full-width Observatory page.
- Added a reconciled SQLite query projection while keeping conversation JSON canonical.
- Added server-side facets/sorting, browser filtering of loaded rows, lazy pagination, cost and outcome metadata, and shareable session links.
- Recorded DEC-027.

### PR #14 — prompt artifact provenance (merged `699dbe9`)

- Added typed prompt provenance distinct from execution topology.
- Made injected orchestration a clickable workflow, with artifact references back to producing answers and a link to RAG evidence rather than duplicated RAG text.
- Added Council rank bubbles and a dedicated aggregate-ranking view.
- Preserved mode-specific Round Robin and Fight handoffs in the canonical trace.
- Recorded DEC-028 and the related mode incidents/decisions.

### PR #15 — Apache-2.0 source boundary (merged `53489c0`)

- Replaced the remaining inherited implementation/media in the current tree with independently written Curia code.
- Added the standard Apache-2.0 `LICENSE`, Auspex Labs `NOTICE`, and `LICENSING.md` history boundary.
- Updated package metadata and CI license detection; Greptile's portability findings were fixed before merge.
- Recorded DEC-029.

### PR #16 — README accuracy (open)

- Rewrote the public entry point around current product behavior.
- Removed Bicameral Mind and speculative future-commercial-offering language.
- Corrected the six orchestration topologies, Cheap Pros chair, frozen model limits, MCP lifecycle, and reliable directives.
- Replaced stale UI claims with the current Turns/Sessions/Inspector/provenance/cost/quality surfaces.
- Added the local/trusted-network boundary and current validation commands.

Earlier foundations remain in PR #11 (Observatory cutover) and PR #12 (Curia rebrand and CI).

## Architecture snapshot

| Surface | Current contract |
|---------|------------------|
| **Turns** | Distinct turns with mode-specific execution views, context/provenance, quality, rankings where applicable, and verdict |
| **Sessions** | Full-width searchable catalog backed by a rebuildable SQLite projection; JSON remains canonical |
| **Inspector** | Participants, mode-aware deliberation pulse, and cost series/breakdowns |
| **Execution** | Canonical trace is the source of topology, step counts, runtime, failures, usage, and cost |
| **Prompt provenance** | Separate typed contract for Curia-owned instructions and artifact handoffs; RAG content stays in the RAG view |
| **MCP** | Full-turn tools for every mode; stepwise `create_turn` / `advance_turn` remains Council-specific |
| **Quality gate** | Check `execution_quality.acceptable`; HTTP 200 alone is not evidence of a valid deliberation |
| **Configuration** | Squad JSON plus frozen `data/model_catalog.yaml` and `data/arena_config.yaml` |

Current squads:

- `normal`: five free arena models, `google/gemini-2.5-pro` chair
- `freebee9`: nine free arena models, `google/gemini-2.5-pro` chair
- `cheap_pros`: four low-cost paid arena models, `deepseek/deepseek-v4-flash` chair

Current modes: Council, Round Robin, Fight, Stacks, Complex Iterative, and Complex Questioning.

## Next work

1. Let CI and Greptile review PR #16. Poll at two-minute intervals when actively shepherding the PR; address actionable P-severity findings on `docs/readme-accuracy` until clean.
2. Merge PR #16, then fast-forward `main` before starting another branch.
3. Resume go-live cleanup from the decision ledger rather than the retired `PLAN.md` roadmap.
4. Treat RAG behavior as its own focused task. In particular, preserve the user's policy that retrieved RAG tokens must never trigger/request model summarization; audit the existing budget/summarizer path before changing or advertising it.
5. Revisit explicit-path retrieval and ranking behavior only within that focused RAG task (INC-002 / DEC-021 context).

## Known gaps and follow-ups

| Item | Reference / note |
|------|------------------|
| Advanced-mode visual vocabulary remains less specialized for Stacks and both Complex modes | DIS-003 |
| Complex Iterative uses only the first two arena models but participant expectations have counted the full squad | INC-006 |
| Client abort does not cancel an already-running backend turn | PIV-001 checklist |
| `prepare_context` is not a standalone MCP tool | PIV-001 checklist |
| Deep internal rename (`mcp_arena/`, `backend/arena.py`, `arena_config.yaml`) remains deferred | DEF-011 |
| Parsed `@temp`, `@maxtokens`, `@trace`, and safety fields are not wired through model execution | Do not advertise as functional directives |
| Free OpenRouter squads can encounter provider rate limits | Prefer `cheap_pros` for reliable dogfood runs; inspect model failures and quality |
| The API has no application authentication | Local/trusted-network deployment only |

## Working-tree boundaries

These user-owned artifacts are intentionally untracked. Do not stage or delete them unless explicitly asked:

- `.playwright-mcp/`
- `observatory-deck-complete.png`
- `observatory-deck-mock.png`
- `scripts/quiz_contract_rankings.py`

Local runtime configuration is gitignored:

- `.env` — requires `OPENROUTER_API_KEY`
- `data/config.json` — persisted squad/theme settings and local `repo_root`

## GitHub and review policy

- Use one branch and one PR per phase.
- Review fixes belong on the PR head branch; do not hide them on a side branch.
- Allow Greptile a few minutes to review. During active shepherding, poll every two minutes up to ten times per turn.
- Fix actionable P-severity findings until none remain. Ask the user only when feedback requires a product-direction choice or material scope expansion.
- The Karpathy `upstream` remote was removed on 2026-07-19. `origin` is the only configured remote and points to `Auspex-Aerie/curia`; still pass `--repo Auspex-Aerie/curia` to scripted `gh` calls when practical.

## Standard checks

```bash
uv run pytest tests/unit -m "not eval"
cd frontend && npm run build
```

Evaluation-marked RAG tests load ML models and are intentionally excluded from ordinary CI.

## Historical recovery note

The original Grok/Composer thread was orphaned after the workspace rename. Its session ID was:

```text
019f33ba-78f3-75c0-ac2d-0f1517bd801a
```

This handoff and the decision ledger now supersede that session as the source for resuming work.
