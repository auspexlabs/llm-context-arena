# Curia

*Latin: the chamber where deliberation happens.*

> **Build in public** — [`Auspex-Aerie/curia`](https://github.com/Auspex-Aerie/curia). Decisions are logged in [`docs/decision_log.md`](docs/decision_log.md).

**Multi-model deliberation with code context** — independently implemented by Auspex Labs and inspired by Andrej Karpathy's [llm-council](https://github.com/karpathy/llm-council) concept.

**License:** [Apache License 2.0](LICENSE). Curia is open source: commercial use, modification, and redistribution are permitted under the license. Applicable attribution is preserved through [NOTICE](NOTICE), and the license does not grant rights to Auspex Labs trade or product names beyond customary attribution.

Credit to [Karpathy](https://twitter.com/karpathy) for popularizing the seed idea: put several frontier models in a room, let them answer independently, review each other anonymously, and have a chairman synthesize a final answer. That three-stage council is Curia's default mode; the implementation, additional modes, grounding system, control plane, and observatory are Curia's own.

Same local-first spirit, more ways to make models argue, and machinery for grounding answers in your codebase.

## What Curia adds

| Area | Addition |
|------|----------|
| **Modes** | Six orchestration strategies: Council, Round Robin, Fight, Stacks, Complex Iterative, Complex Questioning |
| **RAG** | CodeRAG pipeline: tree-sitter chunking, learned ColBERT (default), entity/graph hybrid, RRF fusion, Jina rerank, embedding query router |
| **Context** | Per-model token budgets, explicit context provenance, manual file picker |
| **Directives** | Inline `@norag`, `@summarize`, `@tokenbudget`, `@cite`, `@lastchair`, and more |
| **UI** | **Observatory deck** — watch-first rail/deck/inspector for council runs; take-control stream bridge; context trace, quality panel, live refresh |
| **Agents** | MCP control plane (`curia-mcp`) — ~30 tools wrapping the HTTP API for Cursor and other MCP clients |

**Roadmap:** Bicameral Mind mode, cost tracking, conditional rerank / index hygiene (see `docs/decision_log.md` DEF-004). Retrieval eval harnesses: `python -m backend.run_hyp001`, `python -m backend.run_hyp002`.

**Repo:** [github.com/Auspex-Aerie/curia](https://github.com/Auspex-Aerie/curia)

---

## Quick Start

```bash
uv sync
cd frontend && npm install && cd ..
cp .env.example .env   # add OPENROUTER_API_KEY
./start.sh             # backend :8001, observatory deck :5173
```

Open **http://localhost:5173** — rail (sessions/turns), deck (timeline + step viewers), inspector (context / rankings / quality), verdict lane. Use **Take control** to run a council turn from the UI.

**RAG defaults (ColBERT + local rerank) need no LM Studio.** LM Studio is only required if you set `SEMANTIC_BACKEND=biencoder` — see [RAG_LMSTUDIO.md](RAG_LMSTUDIO.md). First ColBERT index on GPU is much faster (`COLBERT_DEVICE=auto`); CPU fallback works everywhere.

### Agent control (MCP)

Run the backend, then start the MCP server (stdio — typical for Cursor):

```bash
python -m backend.main          # API only
uv run curia-mcp                # CURIA_API_URL defaults to http://127.0.0.1:8001
```

Set `CURIA_AGENT_ID` to attribute turns (`ARENA_*` env names still work during transition). Recommended flow: `get_index_manifest` → `create_conversation` → `run_council_turn` or stepwise `create_turn` / `advance_turn`. Always check `execution_quality.acceptable` before trusting stage 3. Full tool map: [`docs/agent-control-plane-architecture.md`](docs/agent-control-plane-architecture.md).

With the observatory deck open, MCP-started runs appear via live poll — no need to drive from the UI.

---

## The Arena Modes

### 1. Council (Default Mode)
The classic: everyone answers, everyone reviews anonymously, chairman synthesizes.

```
┌─────────────────────────────────────────────────────────┐
│ Query ──► ALL MODELS ANSWER (parallel, +RAG context)    │
│              │                                          │
│              ▼                                          │
│         ANONYMOUS PEER REVIEW                           │
│         "Rank Response A, B, C, D..."                   │
│              │                                          │
│              ▼                                          │
│         CHAIRMAN SYNTHESIZES                            │
│         (uses top-ranked as spine)                      │
└─────────────────────────────────────────────────────────┘
```

**Prompt flow:**
- Stage 1: Each model gets `[system: you are Agent N] + [context] + [user query]`
- Stage 2: Each model gets `[all responses anonymized as A/B/C/D] + [rank them]`
- Stage 3: Chairman gets `[all responses + rankings] + [synthesize final answer]`

---

### 2. Round Robin (Sequential Refinement)
Each model builds on the previous answer. Like a relay race of ideas.

```
Query ──► Model A ──► Model B refines ──► Model C refines ──► Chairman finalizes
              │              │                   │
              └──────────────┴───────────────────┘
                    each sees prior + original context
```

**Prompt flow:**
- Turn 1: Model A gets `[context] + [query]` → produces draft
- Turn 2: Model B gets `[original context] + [Model A's draft]` → refines
- Turn N: Model N gets `[original context] + [previous draft]` → refines
- Final: Chairman gets `[last draft]` → produces final answer

---

### 3. Fight (Adversarial Debate)
Models critique each other, then defend their positions. Chairman summarizes the battle.

```
Query ──► ALL ANSWER ──► ALL CRITIQUE PEERS ──► ALL DEFEND ──► Chairman: debate summary
               │                │                    │
               └────────────────┴────────────────────┘
                      pointed critique, brief defense
```

**Prompt flow:**
- Round 1: All models answer (parallel)
- Round 2: Each model critiques peers: `[your answer] + [peer answers] → point out errors, risks`
- Round 3: Each model defends: `[your answer] + [critiques of you] → fix or rebut`
- Final: Chairman summarizes consensus, disagreements, key risks

---

### 4. Stacks (Hierarchical Merge + Attack)
Two answer, chairman merges, two critics attack, chairman judges, defenders respond.

```
Query ──► 2 ANSWER ──► CHAIRMAN MERGES ──► 2 CRITICS ATTACK ──► CHAIRMAN JUDGES
                            │                     │                    │
                            ▼                     ▼                    ▼
                    "preserve optionality"   "attack weak spots"   (has original context)
                                                                       │
                                              ┌────────────────────────┘
                                              ▼
                                    ORIGINAL 2 DEFEND ──► CHAIRMAN FINAL
                                                          (no original context)
```

**Prompt flow:**
- Phase 1: Models A & B answer
- Phase 2: Chairman merges with "preserve optionality" instruction
- Phase 3: Models C & D critique the merged answer
- Phase 4: Chairman judges critiques against original context
- Phase 5: Models A & B defend against critiques
- Final: Chairman synthesizes (deliberately without original context)

---

### 5. Complex Iterative (Extract/Expand Alternation)
Alternating summarize-then-elaborate cycles. Good for deep dives.

```
Query ──► EXTRACT ──► EXPAND ──► EXTRACT ──► EXPAND ──► Chairman final
           (summary)   (detail)   (summary)   (detail)
              │           │           │           │
              └───────────┴───────────┴───────────┘
                   each sees only prior step + original context
```

**Prompt flow:**
- Extract: `[context] + [query] → summarize intent, list key facts, suggest next prompt`
- Expand: `[prior summary] + [suggested prompt] → elaborate with actionable detail`
- Repeat alternation for N cycles
- Chairman synthesizes the extract/expand chain

---

### 6. Complex Questioning (Socratic Method)
Models question their own answers through peers' perspectives. Two-phase introspection.

```
Query ──► ALL ANSWER ──► ALL QUESTION OWN ANSWERS ──► Chairman summary
                              (via peer lenses)              │
                                    │                        ▼
                                    │              MUSE ROUND (no original context)
                                    │                        │
                                    └────────────────────────┴──► Chairman final
```

**Prompt flow:**
- Round 1: All models answer (parallel)
- Round 2: Each model re-reads own answer "through peers' lenses", updates position
- Round 3: Chairman summarizes convergences/divergences
- Round 4: Models "muse" on the summary alone (no original context)
- Final: Chairman synthesizes debate + muse rounds

---

## What We Added (detail)

Built around the council pattern:

### Local RAG System
- **ZIP or git snapshot** per conversation — drop a `.zip` or reindex from a configured repo root
- **CodeRAG indexing**: tree-sitter AST chunking (Python, Rust, JS/TS/TSX, Go), entity index, code graph, manifest-based delta reindex
- **Semantic search** (default `SEMANTIC_BACKEND=colbert`): learned PyLate ColBERT per conversation; optional `biencoder` path uses FAISS + LM Studio nomic embeddings
- **Query-time retrieval** (variant F): ColBERT top-K ∥ entity seed → **RRF fusion** → **Jina v3 cross-encoder rerank** → README demotion → **append-only graph** neighbors (embedding query router picks trace vs architectural policy)
- **Index freshness**: UI polls `GET /api/index_manifest`, warns when git or snapshot drifted, one-click reindex (`POST .../reindex` or `.../reindex_git`)

### Context Intelligence
- **Per-model token budgets** with safety margins (85% of context window)
- **Auto-summarization** when context exceeds budget (Chairman compresses)
- **Manual context override**: file picker + `@file:` directives bypass RAG

### @Directives
Control behavior inline with your query:

| Directive | Effect |
|-----------|--------|
| `@norag` / `@raw` | Skip RAG retrieval entirely |
| `@summarize` | Force context summarization even if under budget |
| `@tokenbudget <n>` | Set per-turn context cap |
| `@cite` | Require inline citations `[file:line]` |
| `@short` / `@detailed` | Hint at response length |
| `@trace` / `@debug` | Attach retrieval metadata to response |
| `@reset` | Clear conversation state |
| `@temp <0-1>` | Override temperature |
| `@maxtokens <n>` | Override max output tokens |

### UX Improvements
- **Stop button** to abort streaming responses
- **Collapsible context panel** showing RAG sources, scores, token counts
- **File tree browser** for manual context selection
- **Stale index banner** when the codebase changed since last index (git drift or snapshot drift) with reindex CTA
- **Settings panel** for arena models, chairman, and repo root
- **Upload progress** with indexing feedback
- **Scroll-to-bottom** shortcut

---

## Configuration

### Arena Models

Squad presets live in `backend/squads/`:

| Squad | File | Arena size |
|-------|------|------------|
| **normal** (default) | `normal.json` | 5 free models |
| **freebee9** | `freebee9.json` | 9 free models |
| **cheap_pros** | `cheap_pros.json` | 4 low-cost paid models |

Swap without editing code:

```bash
# .env — startup default (before data/config.json overrides)
ARENA_SQUAD=normal    # or freebee9
```

Or use **Settings → Arena squad** in the UI (persists to `data/config.json`). Chairman stays `google/gemini-2.5-pro` in both presets; edit the JSON files to change it.

### Environment

```bash
# Required
OPENROUTER_API_KEY=sk-or-v1-...

# LM Studio (bi-encoder embeddings for FAISS path only — skip if SEMANTIC_BACKEND=colbert)
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_EMBED_MODEL=text-embedding-nomic-embed-text-v1.5

# Retrieval pipeline (production defaults — see docs/decision_log.md DEC-010/011)
SEMANTIC_BACKEND=colbert
COLBERT_LEARNED=true
COLBERT_DEVICE=auto          # cuda when available, else cpu
QUERY_ROUTER=embedding       # embedding | regex
FUSION_MODE=rrf              # rrf | max_score
GRAPH_MODE=append              # append | resort
RERANK_MODEL=jinaai/jina-reranker-v3
RERANK_ENABLED=true
RETRIEVE_CANDIDATES=50
RERANK_TOP_K=20
CONTEXT_CHUNK_CAP=60
```

### Context Limits

Per-model limits live in `backend/config.py` (`MODEL_CONTEXT_LIMITS`). Unknown models fall back to `DEFAULT_MODEL_CONTEXT_LIMIT` (131,072). Chairman default:

| Model | Default Context | Env Override |
|-------|-----------------|--------------|
| `google/gemini-2.5-pro` | 1,048,576 | `CTX_LIMIT_GEMINI_2_5_PRO` |

Safety margin: 85% (`CONTEXT_SAFETY_MARGIN=0.85`)
Output allowance: 4000 tokens (`OUTPUT_TOKEN_ALLOWANCE=4000`)

---

## Tech Stack

- **Backend:** FastAPI, Python 3.10+, async httpx, OpenRouter API
- **Frontend:** Vanilla TypeScript observatory deck, Vite 7, `marked` + DOMPurify, highlight.js
- **Agents:** FastMCP server in `mcp_arena/` (`curia-mcp` entry point; `arena-mcp` alias deprecated)
- **RAG:** CodeRAG (tree-sitter chunking, entity/graph hybrid, RRF fusion, embedding query router), ColBERT (default) or FAISS bi-encoder, Jina v3 cross-encoder rerank (`sentence-transformers`); LM Studio only for bi-encoder embeddings; PyTorch cu126 wheel for GPU ColBERT encode
- **Storage:** canonical conversation JSON plus a rebuildable SQLite session-query projection

---

## CLI Tools

Preview context that would be sent for a query:

```bash
python -m backend.cli_context --conversation <id> --query "How does auth work?"

# Force specific files (bypass RAG):
python -m backend.cli_context --conversation <id> --query "..." --manual-file backend/main.py
```

---

## Documentation

- [RAG_LMSTUDIO.md](RAG_LMSTUDIO.md) — RAG setup, env vars, retrieval topology, indexing APIs
- [docs/decision_log.md](docs/decision_log.md) — append-only architecture / policy ledger (ADRLight-style)
- [docs/piv-001-agent-control-plane.md](docs/piv-001-agent-control-plane.md) — agent control plane, UI as observatory
- [docs/piv-001-checklist.md](docs/piv-001-checklist.md) — implementation status (MCP, turns API, open items)
- [docs/piv-002-observatory-ui.md](docs/piv-002-observatory-ui.md) — observatory deck spec
- [docs/piv-003-curia-rebrand.md](docs/piv-003-curia-rebrand.md) — Curia rename tiers (A–C done; D–F deferred)
- [docs/curia-handoff.md](docs/curia-handoff.md) — resume here: paths, MCP config, dogfood loop
- [PLAN.md](PLAN.md) — Feature roadmap and mode specifications

---

## License

Curia is open source under the [Apache License 2.0](LICENSE). In short:

- **Use** — run, modify, distribute, and use Curia commercially
- **Attribute** — retain the license, applicable source notices, and the attribution in [NOTICE](NOTICE) when redistributing derivatives
- **Mark changes** — modified files must carry prominent notices that they were changed
- **Names stay separate** — the license does not grant rights to Auspex Labs trade names, trademarks, service marks, or product names beyond reasonable attribution

Curia is currently developed in the open. Any future separately developed commercial offering would not change the Apache-2.0 terms of versions already released under this license. See [LICENSING.md](LICENSING.md) for the source-tree and history boundary.

---

## Acknowledgments

**Thanks to [Andrej Karpathy](https://twitter.com/karpathy)** for publishing [llm-council](https://github.com/karpathy/llm-council) and popularizing the three-stage council pattern (answer → anonymous peer review → chairman synthesis) that inspired Curia.

Contributions and feedback are welcome under the license terms above.
