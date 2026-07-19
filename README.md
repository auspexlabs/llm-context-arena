# Curia

*Latin: the chamber where deliberation happens.*

**Curia is a local-first, multi-model deliberation system grounded in your codebase.** It runs several models through a chosen discussion structure, records the complete execution trace, and gives a chairman model the material needed to produce a final answer.

Curia was independently implemented by Auspex Labs and inspired by Andrej Karpathy's [llm-council](https://github.com/karpathy/llm-council) concept. The classic three-stage council is the default mode; Curia's additional modes, CodeRAG pipeline, agent control plane, storage model, and Observatory are its own.

> **Build in public:** [Auspex-Aerie/curia](https://github.com/Auspex-Aerie/curia). Architecture and product decisions are recorded in the [decision log](docs/decision_log.md).

## At a glance

| Area | What Curia provides |
|------|---------------------|
| **Deliberation** | Six orchestration modes: Council, Round Robin, Fight, Stacks, Complex Iterative, and Complex Questioning |
| **Grounding** | Conversation-scoped CodeRAG with AST chunking, ColBERT retrieval, entity and graph signals, RRF fusion, and cross-encoder reranking |
| **Observability** | A canonical execution trace, prompt provenance, model failures, quality status, token usage, cost, and per-step timing |
| **Interface** | A watch-first Observatory with mode-aware turn views and a full-width, searchable Sessions catalog |
| **Agent control** | A 30-tool MCP server over the HTTP API for driving and inspecting Curia from coding agents |
| **Storage** | Canonical conversation JSON plus a rebuildable SQLite projection for session queries |

## Quick start

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Node.js/npm, and an [OpenRouter](https://openrouter.ai/) API key.

```bash
uv sync
cd frontend && npm install && cd ..
cp .env.example .env   # set OPENROUTER_API_KEY
./start.sh
```

Open [http://localhost:5173](http://localhost:5173). The script starts the FastAPI backend on `127.0.0.1:8001` and the Observatory on `127.0.0.1:5173`; both hosts and the API port can be changed with `CURIA_API_HOST`, `CURIA_API_PORT`, and `CURIA_WEB_HOST`.

Curia currently has no application-level authentication. Keep the API and Observatory on localhost or a trusted network boundary.

The default learned ColBERT path does not require LM Studio. LM Studio is needed only when `SEMANTIC_BACKEND=biencoder`; see [RAG_LMSTUDIO.md](RAG_LMSTUDIO.md).

## The Observatory

The Observatory separates active deliberation from session history:

- **Turns** shows the current session, its distinct turns, mode-specific execution views, context and prompt provenance, rankings where applicable, quality evidence, and the final verdict.
- **Sessions** is a full-width catalog with activity dates, caller and origin, mode and squad, turn/message counts, outcome, duration, token/call totals, and cost. Search filters the loaded rows immediately; facet controls re-query SQLite; scrolling loads additional pages lazily.
- **Inspector** is split into participants, a mode-aware deliberation pulse, and selectable cost series for the current session, matching squad, or all remembered sessions. Single-series views can be broken down by model, top session, week, or month as appropriate.

Conversation IDs and session links are shareable URLs. The deck live-polls the backend, so turns started through MCP appear without being initiated in the browser. **Take control** enables the turn composer when you do want to continue a session from the UI.

The Context view distinguishes three different things:

1. the user's grounded prompt and whether CodeRAG supplied context;
2. Curia-owned orchestration text injected at each stage; and
3. artifacts handed from earlier models or stages to later ones.

The injection workflow is clickable: artifact references link back to their producing answers, while RAG links open the retrieved-source view rather than duplicating repository text inside orchestration prompts.

## Deliberation modes

Every mode uses the same canonical trace contract, but each has its own topology and visual treatment.

### Council (default)

Models answer independently, anonymously rank the collected answers, and a chairman synthesizes the responses and peer rankings.

```text
query + context
      │
      ├── model answers (parallel)
      │          │
      │          └── anonymous peer rankings
      │                         │
      └─────────────────────────┴── chairman final
```

The aggregate ranking is calculated from each model's parsed ordering. It is evidence for the chairman and the user, not a replacement for the final synthesis.

### Round Robin

Models refine one shared draft sequentially. Each model receives its grounded base prompt and the latest predecessor draft. `@iterations <n>` runs additional passes over the squad before the chairman receives the latest draft and original grounded question.

```text
query + context ── model A ── model B ── model C ── … ── chairman final
                         latest draft moves forward
```

### Fight

All models take an opening position, critique peer positions, then defend or revise their own answer against peer critiques. The chairman receives the openings, critiques, and defenses.

```text
openings (parallel) ── peer critiques ── defenses ── chairman final
```

### Stacks

The first two models answer, the chairman merges their answers, and the remaining models critique the merge. The chairman judges the merge against those critiques, the original two models defend or repair it, and the chairman produces the final report.

With a two-model squad, those same two models also serve as critics.

```text
2 answers ── chair merge ── critics ── chair judgment ── 2 defenses ── chair final
```

### Complex Iterative

The first two arena models alternate through a fixed two-cycle extract/expand chain. The first model extracts intent, constraints, and a next prompt; the second expands the prior extract with actionable detail. After four hops, the chairman answers from the original grounded question and latest chain state.

```text
extract ── expand ── extract ── expand ── chairman final
```

### Complex Questioning

All models answer, then reassess their own answer through the other answers. The chairman turns those reflections into a brief; each model muses on that brief alone; the chairman then synthesizes the brief and muse round.

```text
answers ── self-questioning through peers ── chair brief ── muses ── chair final
```

## Code grounding and context

CodeRAG indexes a ZIP snapshot or configured Git working tree per conversation. Its current pipeline includes:

- tree-sitter AST chunking for Python, Rust, JavaScript, TypeScript/TSX, and Go;
- learned PyLate ColBERT retrieval by default, with an optional FAISS/LM Studio bi-encoder path;
- entity seeds and an append-only code graph;
- reciprocal-rank fusion, an embedding query router, and Jina v3 cross-encoder reranking;
- manifest-based file-level delta indexing and index-freshness APIs; and
- explicit source, score, size, and estimated-token records for retrieved chunks.

Manual context can be supplied through the HTTP API or CLI. When manual files are present, they replace retrieval for that request.

Preview the context selected for a query without running a deliberation:

```bash
python -m backend.cli_context \
  --conversation <id> \
  --query "How does authentication work?"

# Force one or more files and bypass RAG for this request:
python -m backend.cli_context \
  --conversation <id> \
  --query "Review this implementation" \
  --manual-file backend/main.py
```

### Reliable query directives

Directives are removed from the user text before prompting.

| Directive | Current effect |
|-----------|----------------|
| `@norag` / `@raw` | Skip retrieval for this turn |
| `@lastchair` | When one exists, use the previous chairman response as context and skip retrieval |
| `@tokenbudget <n>` | Cap the per-model prompt budget for the turn |
| `@iterations <n>` | Set the number of Round Robin squad passes |
| `@short` / `@detailed` | Add a response-length instruction to model prompts |
| `@cite` | Ask models to cite supplied context as `[file:line]` |
| `@noexecute` | Add a reasoning-only, no-tools instruction to model prompts |
| `@reset` | Clear the conversation state instead of running a turn |

Prompt-level instructions are requests to the selected models, not independently enforced policy controls.

## Agent control with MCP

Run the API, then start Curia's stdio MCP server:

```bash
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8001
uv run curia-mcp
```

`CURIA_API_URL` defaults to `http://127.0.0.1:8001`. Set `CURIA_AGENT_ID` to record who initiated agent-driven work. Legacy `ARENA_*` aliases remain accepted for compatibility.

A typical full-turn flow is:

```text
get_index_manifest
  → reindex when needed
  → create_conversation
  → send_message
  → inspect execution_quality, trace, failures, and cost
```

`send_message` is the mode-agnostic full-turn tool. For Council only, `run_council_turn` is a convenience wrapper around the lower-level `create_turn` / `advance_turn` lifecycle. Always check `execution_quality.acceptable` before treating the chairman response as a successful run; a transport-level success does not guarantee that every required model stage succeeded.

See [Agent Control Plane Architecture](docs/agent-control-plane-architecture.md) for the tool map and response contracts.

## Configuration

### Squad presets

Squads live in `backend/squads/` and define both arena participants and the chairman.

| Squad | Arena | Chairman |
|-------|-------|----------|
| `normal` (default) | 5 diverse free models | `google/gemini-2.5-pro` |
| `freebee9` | 9 free models | `google/gemini-2.5-pro` |
| `cheap_pros` | 4 low-cost paid models | `deepseek/deepseek-v4-flash` |

Choose the startup default in `.env`:

```bash
ARENA_SQUAD=cheap_pros
```

The Observatory's **Settings → Arena squad** control persists a selection to `data/config.json`. Persisted runtime settings take precedence over the environment default. Settings also controls the light/dark theme.

### Retrieval environment

```bash
OPENROUTER_API_KEY=sk-or-v1-...

# Default semantic path
SEMANTIC_BACKEND=colbert       # colbert | biencoder
COLBERT_LEARNED=true
COLBERT_DEVICE=auto            # CUDA when available, otherwise CPU

# Retrieval topology
QUERY_ROUTER=embedding         # embedding | regex
FUSION_MODE=rrf                # rrf | max_score
GRAPH_MODE=append              # append | resort
RERANK_MODEL=jinaai/jina-reranker-v3
RERANK_ENABLED=true
RETRIEVE_CANDIDATES=50
RERANK_TOP_K=20
CONTEXT_CHUNK_CAP=60

# Only used by SEMANTIC_BACKEND=biencoder
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_EMBED_MODEL=text-embedding-nomic-embed-text-v1.5
```

### Model context limits

Registered model limits and tags live in `data/model_catalog.yaml`. Allocation policy—including the 85% safety margin, 4,000-token output allowance, fallback limit, and tag modifiers—lives in `data/arena_config.yaml`. These files are frozen at process start; restart the backend after changing them.

Accepted runtime observations may supersede a registered planning limit. `backend/config.py` retains fallback limits for uncatalogued and legacy model IDs.

## Architecture

- **Backend:** FastAPI, Python 3.10+, async httpx, OpenRouter API
- **Frontend:** vanilla TypeScript, Vite 7, `marked` with DOMPurify, highlight.js
- **Agent control:** FastMCP in `mcp_arena/`; `curia-mcp` entry point, with deprecated `arena-mcp` alias
- **RAG:** tree-sitter, PyLate ColBERT or FAISS bi-encoder, entity/graph hybrid retrieval, Jina v3 reranking
- **Storage:** conversation JSON as the source of truth; SQLite as a reconciled, rebuildable Sessions projection
- **Configuration:** squad JSON plus startup-frozen model catalog and arena policy YAML

## Development checks

```bash
# Backend unit suite used by CI (evaluation workloads excluded)
uv run pytest tests/unit -m "not eval"

# Frontend type-check and production build
cd frontend && npm run build
```

The retrieval evaluation harnesses are intentionally separate from the ordinary unit suite:

```bash
python -m backend.run_hyp001
python -m backend.run_hyp002
```

## Documentation

- [RAG_LMSTUDIO.md](RAG_LMSTUDIO.md) — retrieval setup, topology, environment, and indexing APIs
- [Decision log](docs/decision_log.md) — append-only decisions, incidents, hypotheses, and deferrals
- [Agent control plane](docs/agent-control-plane-architecture.md) — MCP architecture, tools, and contracts
- [PIV-001 checklist](docs/piv-001-checklist.md) — agent-control implementation status and open work
- [PIV-002 Observatory](docs/piv-002-observatory-ui.md) — accepted Observatory direction and design history
- [PIV-003 Curia rebrand](docs/piv-003-curia-rebrand.md) — completed rename tiers and remaining compatibility work
- [DEC-018 frozen configuration](docs/dec-018-catalog-config-summarizer.md) — model catalog, limit observations, summarizer, and prompt registry
- [LICENSING.md](LICENSING.md) — source-tree and repository-history licensing boundary

## License

Curia is open source under the [Apache License 2.0](LICENSE). You may run, modify, distribute, and use it commercially under that license. Redistributors must provide the license, mark modified files, retain applicable source notices, and preserve the applicable attribution in [NOTICE](NOTICE). The license does not grant rights to Auspex Labs trade names, trademarks, service marks, or product names beyond customary attribution.

See [LICENSING.md](LICENSING.md) for the source-tree and repository-history boundary.

## Acknowledgments

Thanks to [Andrej Karpathy](https://github.com/karpathy) for publishing [llm-council](https://github.com/karpathy/llm-council) and popularizing the answer → anonymous peer review → chairman synthesis pattern that inspired Curia.

Contributions and feedback are welcome under the license terms above.
