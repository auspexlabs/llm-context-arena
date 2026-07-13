# LLM Context Arena

> **Build in public** — development happens in the [`Auspex-Aerie`](https://github.com/Auspex-Aerie) org. Decisions are logged in [`docs/decision_log.md`](docs/decision_log.md).

**Multi-model deliberation with code context — a fork of Andrej Karpathy's [llm-council](https://github.com/karpathy/llm-council).**

**License:** Free to download, run, and modify for your own use. You may not ship a competing product or commercial fork — see [LICENSE](LICENSE) (PolyForm Shield 1.0.0). A **Pro** edition with hosted and enterprise features is planned.

All credit to [Karpathy](https://twitter.com/karpathy) for the original idea: put several frontier models in a room, let them answer independently, review each other anonymously, and have a chairman synthesize a final answer. That three-stage council is elegant and we kept it as the default mode.

This fork extends that foundation into an **arena** — same local-first vibe-coded spirit, more ways to make models argue, and machinery for grounding answers in your codebase.

## What changed in this fork

| Area | Addition |
|------|----------|
| **Modes** | Six orchestration strategies: Council, Round Robin, Fight, Stacks, Complex Iterative, Complex Questioning |
| **RAG** | CodeRAG pipeline: tree-sitter chunking, learned ColBERT (default), entity/graph hybrid, RRF fusion, Jina rerank, embedding query router |
| **Context** | Per-model token budgets, chairman summarization when context is huge, manual file picker |
| **Directives** | Inline `@norag`, `@summarize`, `@tokenbudget`, `@cite`, `@lastchair`, and more |
| **UI** | **Observatory deck** — watch-first rail/deck/inspector for council runs; take-control stream bridge; context trace, quality panel, live refresh |
| **Agents** | MCP control plane (`arena-mcp`) — ~30 tools wrapping the HTTP API for Cursor and other MCP clients |

**Roadmap:** Bicameral Mind mode, cost tracking, conditional rerank / index hygiene (see `docs/decision_log.md` DEF-004). Retrieval eval harnesses: `python -m backend.run_hyp001`, `python -m backend.run_hyp002`.

**Repo:** [github.com/Auspex-Aerie/llm-context-arena](https://github.com/Auspex-Aerie/llm-context-arena)

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
python -m backend.main          # or ./start.sh backend only
uv run arena-mcp                # ARENA_API_URL defaults to http://127.0.0.1:8001
```

Set `ARENA_AGENT_ID` to attribute turns. Recommended flow: `get_index_manifest` → `create_conversation` → `run_council_turn` or stepwise `create_turn` / `advance_turn`. Always check `execution_quality.acceptable` before trusting stage 3. Full tool map: [`docs/agent-control-plane-architecture.md`](docs/agent-control-plane-architecture.md).

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

Built on top of Karpathy's original council:

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
- **Agents:** FastMCP server in `mcp_arena/` (`arena-mcp` entry point)
- **RAG:** CodeRAG (tree-sitter chunking, entity/graph hybrid, RRF fusion, embedding query router), ColBERT (default) or FAISS bi-encoder, Jina v3 cross-encoder rerank (`sentence-transformers`); LM Studio only for bi-encoder embeddings; PyTorch cu126 wheel for GPU ColBERT encode
- **Storage:** JSON files in `data/conversations/`

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
- [PLAN.md](PLAN.md) — Feature roadmap and mode specifications
- [COUNCIL_OG_README.md](COUNCIL_OG_README.md) — Original Karpathy README

---

## License

Source is available under the [PolyForm Shield License 1.0.0](LICENSE). In short:

- **Use** — download, run, and modify for personal, research, and internal workflows
- **Share** — redistribute only with the same license and notices
- **Don't compete** — you may not offer a product that substitutes for LLM Context Arena or the planned Pro edition

Commercial licensing for competing or embedded offerings: contact Auspex Labs.

---

## Acknowledgments

**Massive thanks to [Andrej Karpathy](https://twitter.com/karpathy)** for [llm-council](https://github.com/karpathy/llm-council). The original 3-stage council (answer → anonymous peer review → chairman synthesis) is the spine of this project.

Karpathy's vibe code philosophy — minimal, readable, hackable — is alive here. Contributions and feedback welcome within the license terms above.