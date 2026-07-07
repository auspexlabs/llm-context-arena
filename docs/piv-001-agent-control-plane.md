# PIV-001: Agent control plane — arena as orchestration, UI as observatory

**Status:** accepted · **date:** 2026-07-07  
**Ledger stub:** `docs/decision_log.md` → `PIV-001`  
**Work checklist:** [`piv-001-checklist.md`](piv-001-checklist.md)

---

## Pivot statement

LLM Context Arena stops being a **chat UI that happens to run multiple models**, and becomes an **agent control plane** that runs deliberation protocols on hypotheses about code (and anything else worth multi-model review).

- **Primary driver:** external agents (and eventually in-repo automation) invoke turns, advance steps, manage index hygiene, and read structured disagreement.
- **Primary UI:** observatory — watch stages, rankings, timeline, context trace, chairman synthesis. Humans **interact when the playthrough awaits them**, not on every turn by default.
- **Disagreement remains signal:** anonymous peer review, aggregate rankings, and stage-1 spread are first-class outputs for the driver — not noise to collapse in stage 3.

The existing multi-mode arena (Council, Fight, Stacks, Round Robin, Complex*) plus CodeRAG stack are the **experiment designs and sensor array**. The pivot adds **execution state, tool APIs, and human checkpoint semantics** so something other than a human clicking Send can run the lab.

---

## What changes in product posture

| Before | After (PIV-001 target) |
|--------|-------------------------|
| User sends message → full arena runs → read answer | Agent posts turn → step/advance/resume → consume structured execution |
| UI owns input, progress, context picker | UI subscribes to execution; drive controls are advanced / override |
| One-shot context injection | Index discipline + optional re-retrieval (`expand_trace`, DEF-003) as tools |
| Chairman answer = product output | `ArenaExecution` = product output; chairman = one field among stages + metadata |
| Metadata partly ephemeral / UI-only | Turn state, steps, rankings, router class, index_stale persisted and API-addressable |

**Rejected for this pivot:** replacing the arena with a single agent + tools; autonomous repo editing without deliberation protocol; UI-first redesign before agent API exists.

---

## Human in the loop: `await_user`

Some playthrough steps need a human as a **role in the protocol**, not as the default operator.

Examples:
- Chairman (or agent supervisor) detects missing context → turn pauses with `await_user` + structured question.
- Budget overflow → ask human to narrow scope or pick files.
- Agent deliberately yields before irreversible synthesis: “three models disagree on auth model — pick A or B?”

Semantics:
- Turn `status`: `running` | `await_user` | `complete` | `failed` | `cancelled`
- Resume via `POST .../turns/{id}/resume` with human reply and optional manual context.
- UI shows await banner; agent may forward the same prompt or auto-resume if policy allows.

This is distinct from DEF-003 (`expand_trace`): await is **any** human checkpoint; expand_trace is **retrieval deepening** on follow-up turns.

---

## Control plane architecture (target)

```
┌─────────────────────────────────────────────────────────────┐
│ Agent driver (CLI, IDE agent, CI, supervisor LLM)           │
│  tools: turn, advance, resume, manifest, reindex, context   │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP / SSE
┌───────────────────────────▼─────────────────────────────────┐
│ Control plane API (new layer on backend/main.py)            │
│  turn state · step checkpoints · structured ArenaExecution  │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
 ContextEngine          arena.py MODE_RUNNERS   RAGProvider
 (directives, budget)   (6 deliberation modes) (index, retrieve)
        └───────────────────┴───────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ Observatory UI — subscribe, timeline, stages, await_user    │
└─────────────────────────────────────────────────────────────┘
```

**Phase 0 (now):** document + expose existing endpoints as tools; fix watch-mode bugs.  
**Phase 1:** turn model + council step API + shared `run_turn()` service.  
**Phase 2:** `await_user` + watch-first UI shell.  
**Phase 3:** all modes checkpointed + `expand_trace` (resolves DEF-003) + agent SDK.

---

## Relationship to prior decisions

| Entry | Relationship |
|-------|----------------|
| **DEC-001** | CodeRAG stack is the **sensor array** agents must index before trusting retrieval. Pivot does not replace it. |
| **DEC-007** | ContextEngine single path remains; agents call the same prepare → arena pipeline via tools. |
| **DEC-010 / DEC-011** | Production retrieval topology (RRF, append graph, embedding router, Jina) is what agents inherit on each turn — no parallel RAG path. |
| **DEC-013** | Index freshness (`needs_reindex`, git drift) becomes an **agent gate** (reindex tool), not only a UI banner. |
| **DEF-003** | Chairman-driven trace expansion deferred; PIV-003 phase targets `expand_trace` as agent tool with budget cap. |
| **DEF-004** | Index hygiene / conditional rerank still deferred; agents may pass `RERANK_ENABLED=false` via env until resolved. |

**Does not supersede** arena modes, council anonymity, or decision-log policy. **Supersedes** the implicit product goal of “human-driven chat app” as the primary interface.

---

## Disagreement as signal (operating doctrine)

Drivers (human or agent) should routinely:
1. Read **stage 1 spread** before stage 3 — what did each model actually assert?
2. Read **stage 2 rankings + raw evaluations** — who won peer review and was parsing valid?
3. Treat chairman output as **synthesis under conflict**, not ground truth.
4. Re-run with different **mode** or **narrower context** when rankings diverge sharply from chairman choice.

This matches how the maintainer already works: ask agents to review each other's plans critically. The control plane makes that **machine-readable** instead of copy-paste between chat windows.

---

## OpenRouter ops note (dev / eval)

For control-plane development and cheap arena smoke tests, OpenRouter exposes **24 explicit `:free` models** (e.g. `meta-llama/llama-3.3-70b-instruct:free`, `qwen/qwen3-coder:free`, `openai/gpt-oss-120b:free`, `nvidia/nemotron-3-super-120b-a12b:free`) plus router `openrouter/free`. Production arena defaults remain paid frontier models in settings; free models are for harness/dev cost control, not quality claims.

---

## Success criteria

- An agent can run a full council turn without opening the UI.
- UI can display the same turn in real time without owning the send button.
- A turn can pause at `await_user` and resume with human input.
- Index stale → agent receives `needs_reindex` and can call reindex before deliberation.
- Stage 2 aggregate rankings are in the structured response for downstream agent logic.