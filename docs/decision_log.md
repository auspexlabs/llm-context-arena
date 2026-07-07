# Decision Log

Append-only decision ledger for `llm-context-arena`, in the style of
[ADRLight](https://github.com/Indubitable-Industries/ADRLight). One file, one
causal history. We record *decisions, deferrals, hypotheses, discoveries, and
incidents* — not tasks (those live in `PLAN.md` / issue trackers).

## How to use this ledger

- **Append-only.** Never delete or rewrite a past entry. The only edit allowed on
  an old entry is a **status update** (e.g. `accepted` → `superseded by DEC-007`).
- **Eight independent ID spaces**, each zero-padded and monotonic: `DEC`, `DEF`,
  `HYP`, `DIS`, `INC`, `OUT`, `BOT`, `PIV`. The ledger allocates IDs — even an external incident
  gets a stub here.
- **Link entries** to form the causal DAG: `triggered_by` (causal origin),
  `supersedes` (DEC replaces DEC), `resolves` (DEC closes a DEF), `promotes`
  (HYP → DEC when a winner is chosen), `related` (non-causal cross-ref).
- Every entry lists **`docs_updated`** — the files it touched (dead links to since-
  deleted files are valid history).
- **Avoid:** essay-length entries, status-less drift, silent backfilling, and using
  this as how-to documentation.

### Status lifecycles
| Type | Purpose | Lifecycle |
|------|---------|-----------|
| **DEC** | Architecture / policy / process decision | `accepted` → `superseded by DEC-###` |
| **DEF** | Deferred work with explicit revisit condition | `active` → `resolved by DEC-###` |
| **HYP** | Systematic experiment with a test matrix | `open` → `promoted to DEC-###` |
| **DIS** | Signal reinterpretation (no action attached) | `observed` (terminal) |
| **INC** | Root cause of a defect found in investigation | `open` → remediated via DEC |
| **OUT** | Service-impact event (downtime, data loss) | `open` → `closed` at recovery |
| **BOT** | Human intuition corrected the AI(s) — "caught the bots" | `logged` (terminal) |
| **PIV** | Product / architectural pivot — new north star | `accepted` → `superseded by PIV-###` (rare) |

### Templates
```
### DEC-###: <imperative title>
- date / status / triggered_by / docs_updated
- decision:  What changed; specific enough to act on
- rationale: Why; rejected alternatives
- impact:    Code/docs affected, work spawned
- supersedes: DEC-### (optional)

### DEF-###: Defer <the work>
- date / status / triggered_by / docs_updated
- decision:     What is deferred, what proceeds in the interim
- rationale:    Why deferring is safe
- revisit_when: Explicit re-entry condition (required)

### HYP-###: <falsifiable question>
- date / status / triggered_by / docs_updated
- question / observation / interventions / test matrix / results (appendable)

### DIS-###: <what the signal actually means>
- finding / implication

### INC-###: <defect summary>
- symptom / root_cause (file:line) / blast_radius / why_not_caught_earlier

### OUT-###:
- severity / summary / remediation / detail

### BOT-###: <the over-claim the human caught>
- date / status / triggered_by
- claim:      what the AI(s) asserted
- correction: the user's intervention
- verified:   what the data/analysis showed afterward
- lesson:     the failure mode to watch

### PIV-###: <pivot title>
- date / status / triggered_by / docs_updated
- pivot:     New north star in one paragraph; what product posture changes
- related:   Prior DEC/DEF this builds on (not supersedes unless stated)
- defers:    What remains unchanged for now
- doc:       Link to `docs/piv-###-*.md` for full vision + checklist
```

---

## Entries

### DEC-001: Adopt phased CodeRAG architecture for conversation-scoped retrieval
- **date:** 2026-07-05 · **status:** accepted · **triggered_by:** P0 repo review; `agentdocs/plans/coderag_pro_plan.md`; field consensus on code-RAG (AST chunking, cross-encoder rerank, hybrid retrieval) · **docs_updated:** `docs/decision_log.md`, `CLAUDE.md`, `README.md` (roadmap line) · **related:** `DEF-001`, `HYP-001`
- **decision:** Replace the current `rag_lmstudio.py` pipeline (character splitting + cosine-on-embeddings “rerank”) with a **three-phase CodeRAG stack**, aligned with `coderag_pro_plan.md` but sequenced for a local per-conversation index:
  - **Phase 1 (ship first):** Tree-sitter AST chunking (Python first); chunk metadata with `path`, `line_start`, `line_end`, `symbol`, `chunk_type`; bi-encoder retrieval (FAISS + LM Studio nomic embed); **proper cross-encoder rerank** (BGE via `sentence-transformers` or equivalent — not embedding cosine); hybrid retrieval (semantic top-K **plus** symbol/path grep seeding from query); wire `RAGProvider` + `ContextEngine` so `main.py` has one context path; context blocks formatted as `path:line_start-line_end` for `@cite`.
  - **Phase 2:** Static **entity index** (def/class → file:line); **NetworkX graph** with Tree-sitter static edges (import, call); **always-on 1-hop expansion** on retrieval hits; parent-child chunks (small index, larger inject); README demotion / chunk-type filtering.
  - **Phase 3:** **Iterative deepening** (2–3 hops) for trace-style queries; pattern-based edges (queues, multiprocessing, UI handlers) via per-lang YAML; **ColBERT or late-interaction retriever** only if Phase 1–2 miss recall targets on a golden query set (see `HYP-001`).
  - **Freshness:** Manifest-based delta reindex (existing `index_manifest.json`); reindex on upload/git snapshot and on explicit UI/CLI trigger — not git pre-commit hooks (see `DEF-001`).
- **rationale:** Current RAG fails on code because chunks are syntactically blind and reranking is not a cross-encoder. The coderag plan is directionally correct; an earlier “defer ColBERT/graph/RAGAS forever” framing was a **sequencing** shortcut, not a rejection. Industry practice (LanceDB code-RAG series, Pinecone reranker guidance) confirms: AST chunks + hybrid search + cross-encoder rerank are the 80% win; graphs and late-interaction retrieval are the precision layer for “how does X call Y” queries. Rejected: keeping `RecursiveCharacterTextSplitter` with tweaks; replacing FAISS with ColBERT on day one (heavy for local LM Studio setup before baseline metrics exist).
- **impact:** New `backend/rag/` package (chunker, rerank, graph, retriever); `rag_lmstudio.py` becomes thin LM Studio adapter; P1 implementation work; tests on fixture repo + golden queries.
- **supersedes:** (implicit) pre-DEC-001 RAG design in `rag_lmstudio.py`

### DEF-001: Defer git pre-commit hook indexing
- **date:** 2026-07-05 · **status:** active · **triggered_by:** `DEC-001` · **docs_updated:** `docs/decision_log.md` · **related:** `agentdocs/plans/coderag_pro_plan.md` § Freshness Automation
- **decision:** Do **not** install repo-wide git pre-commit hooks for index rebuilds in P1. Use per-conversation manifest diff + explicit reindex (`/reindex_git`, upload, CLI) instead.
- **rationale:** Indexes are scoped to `data/conversations/{id}_faiss` and `temp_repos/{id}` — not the developer’s working tree globally. Hooks would surprise users and fight the arena’s “drop a zip per conversation” model.
- **revisit_when:** We add a **workspace-wide** persistent index (single index shared across conversations) or CI-based indexing for a monorepo deployment.

### HYP-001: ColBERT vs bi-encoder + graph for symbol-heavy recall
- **date:** 2026-07-05 · **status:** promoted to DEC-003 (fixture sim) · **triggered_by:** `DEC-001` Phase 3 gate · **docs_updated:** `docs/decision_log.md` · **related:** `agentdocs/plans/coderag_pro_plan.md`
- **question:** After Phase 1–2, is bi-encoder + cross-encoder rerank + 1-hop graph sufficient for our golden code queries, or does ColBERT (token-level late interaction) materially improve recall@10?
- **observation:** Coderag plan centers ColBERT for “exact file/object retrieval”; current nomic bi-encoder misses symbols that never appear in natural-language phrasing.
- **interventions:** Build a 15–20 query golden set from real arena conversations (auth flow, “where is X defined”, cross-file call chains). Measure recall@10 after Phase 1, then Phase 2.
- **test matrix:** (A) bi-encoder + rerank only; (B) + entity seed; (C) + 1-hop graph; (D) ColBERT **replaces** bi-encoder only (isolated ablation — no entity/graph); (E) **production fuse** — ColBERT + entity seed + graph + rerank.
- **results:** *(2026-07-05, simulated golden set — `tests/fixtures/golden_repo` + 18 queries, recall@10)*
  | Variant | Pipeline | recall@10 |
  |---------|----------|-----------|
  | **A** | bi-encoder + rerank | 0.787 |
  | **B** | A + entity seed (union merge) | 0.981 |
  | **C** | B + 1-hop graph | 0.981 |
  | **D** | ColBERT + rerank *(isolated — no seed/graph)* | 1.000 |
  | **E** | ColBERT + entity seed + graph *(production)* | 1.000 |
  - **How layers combine:** ColBERT and bi-encoder are **mutually exclusive** semantic backends — not run in parallel. Entity seed hits are **union-merged** into the semantic pool (max score per `chunk_id`), then cross-encoder rerank, then graph expansion adds 1-hop / trace neighbors. D measured ColBERT's semantic strength alone; E is what ships.
  - **By category:** trace queries 0.67 (A/B/C with bi-encoder) → 1.0 (D/E with ColBERT semantic). Entity seed fixed symbol_lookup for bi-encoder path (0.75 → 1.0); ColBERT also reaches 1.0 on symbols without seed.
  - **Conclusion:** Default semantic backend is **ColBERT** (`DEC-004`). Bi-encoder remains available via `SEMANTIC_BACKEND=biencoder`. FAISS index kept for bi-encoder fallback and LM Studio embedding path.
- **results:** *(2026-07-06, learned ColBERT + real BGE rerank — `tests/fixtures/golden_repo` + 18 queries, recall@10; `python -m backend.run_hyp001`)*
  | Variant | Pipeline | recall@10 |
  |---------|----------|-----------|
  | **A** | bi-encoder + BGE rerank | 0.917 |
  | **B** | A + entity seed | 0.917 |
  | **C** | B + 1-hop graph | 0.917 |
  | **D** | learned ColBERT + BGE *(isolated)* | 0.917 |
  | **E** | learned ColBERT + entity + graph *(production)* | 0.917 |
  - **vs 2026-07-05 sim:** Hash ColBERT + flat rerank scored 1.0 on D/E; learned PyLate + `BAAI/bge-reranker-base` drops to 0.917 because **q13** (`fetch_user`) and **q14** (permission + fetch) miss under real rerank ordering — all variants share the same failure (rerank dominates final top-10).
  - **By category:** trace/semantic/pattern remain 1.0; symbol_lookup 0.875; cross_file 0.833.
  - **Conclusion:** Learned ColBERT index builds and retrieves on golden repo; production stack (E) does not regress vs isolated ColBERT (D). Remaining gap is **rerank demotion of `api/routes.py:fetch_user`** — tune rerank blend or entity seed boost for endpoint symbols (follow-up, not a ColBERT blocker).
  - **artifact:** `docs/hyp001_results_learned.json`

### DEC-002: Ship CodeRAG Phases 1–3 (pre-ColBERT)
- **date:** 2026-07-05 · **status:** accepted · **triggered_by:** `DEC-001` · **docs_updated:** `docs/decision_log.md`, `backend/rag/`, `backend/rag_lmstudio_provider.py`, `backend/rag_lmstudio.py`, `backend/rag_provider.py`, `backend/dependencies.py`, `pyproject.toml`, `tests/unit/test_*.py`, `tests/fixtures/` · **related:** `HYP-001`
- **decision:** Implement and land **Phases 1–3** of `DEC-001` in a new `backend/rag/` package, with `LMStudioRAGProvider` as the concrete `RAGProvider` and `rag_lmstudio.py` as a thin backward-compatible facade. ColBERT / late-interaction retrieval remains **gated** on `HYP-001` golden-query metrics — not shipped in this change.
  - **Phase 1:** Tree-sitter Python chunking (line-window fallback); `CodeChunk` metadata + `path:line_start-line_end` citations; FAISS bi-encoder retrieval; injectable `CrossEncoderReranker` (BGE via `sentence-transformers` when enabled); hybrid symbol/path seeding.
  - **Phase 2:** `EntityIndex` (def/class → location); `CodeGraph` (NetworkX) with static reference edges; always-on 1-hop expansion; README demotion.
  - **Phase 3:** Multi-hop `trace_expand` for trace-style queries; pattern edges from `patterns.yaml`.
- **rationale:** Replaces character-split + cosine-on-embeddings “rerank” with syntactically aware chunks and a proper rerank stage — the 80% win per `DEC-001`. Phases 1–3 are testable without LM Studio (injectable embedder/reranker mocks). ColBERT deferred until baseline recall@10 is measured.
- **impact:** 89 unit tests green; new deps (`tree-sitter`, `tree-sitter-python`, `networkx`, `sentence-transformers`, `pyyaml`). `main.py` still calls `rag_lmstudio` facade — `ContextEngine` wiring is a follow-up.
- **supersedes:** pre-DEC-002 `rag_lmstudio.py` monolith implementation

### DEC-003: Defer production ColBERT; keep late-interaction as optional eval path
- **date:** 2026-07-05 · **status:** superseded by DEC-004 · **triggered_by:** `HYP-001` results · **docs_updated:** `docs/decision_log.md` · **related:** `HYP-001`, `DEC-001`
- **decision:** *(withdrawn)* Initially deferred ColBERT pending real golden-set validation. Superseded after clarifying that HYP-001 variant D was an isolated ablation, not the fused production stack.
- **supersedes:** —

### DEC-004: Default semantic backend to ColBERT (late-interaction)
- **date:** 2026-07-05 · **status:** accepted · **triggered_by:** `HYP-001` results; user review of fusion semantics · **docs_updated:** `docs/decision_log.md`, `backend/config.py`, `backend/rag/retriever.py`, `backend/rag_lmstudio_provider.py`, `backend/rag/eval.py` · **related:** `HYP-001`, `DEC-001` · **supersedes:** `DEC-003`
- **decision:** Set **`SEMANTIC_BACKEND=colbert`** as default. Production retrieval (variant **E**) fuses: ColBERT semantic search → union entity seed → cross-encoder rerank → README demotion → graph expansion. FAISS bi-encoder remains built at index time and selectable via `SEMANTIC_BACKEND=biencoder` for fallback or A/B/C ablations.
- **rationale:** ColBERT does not stack on bi-encoder — it **replaces** the semantic step. D=1.0 isolated showed ColBERT fixes trace/symbol queries bi-encoder misses; E=1.0 confirms ColBERT + entity + graph is the full stack. Learned embeddings wired in `DEC-005` (PyLate); hash MaxSim remains fallback.
- **impact:** `RetrievalConfig.from_settings()` reads `SEMANTIC_BACKEND`; `LMStudioRAGProvider` passes it to `CodeRetriever`. HYP-001 matrix extended with variant E.

### DEC-005: Wire learned ColBERT token embeddings (PyLate) per conversation
- **date:** 2026-07-06 · **status:** accepted · **triggered_by:** `DEC-004`; user request for real ColBERT embeddings scoped per codebase · **docs_updated:** `docs/decision_log.md`, `backend/rag/colbert_learned.py`, `backend/rag/colbert.py`, `backend/rag/store.py`, `backend/config.py`, `pyproject.toml`, `tests/unit/test_colbert_learned.py` · **related:** `DEC-004`, `HYP-001`
- **decision:** Replace the hash-based `LateInteractionIndex` stub with **learned ColBERT token embeddings** via **PyLate** (`colbert-ir/colbertv2.0`) as the default semantic backend when `COLBERT_LEARNED=true`. **Model weights are general** (pre-trained, downloaded once); **indexes are per-conversation** at `data/conversations/{id}_colbert/` (Voyager token-embedding store). On build failure or `COLBERT_LEARNED=false`, fall back to hash MaxSim. Bi-encoder FAISS + BGE cross-encoder rerank unchanged — ColBERT replaces only the semantic retrieval step; entity seed and graph still fuse via union merge.
- **rationale:** Hash ColBERT proved the MaxSim pipeline and HYP-001 ablations but lacks semantic generalization. PyLate gives production ColBERTv2 with per-index persistence without per-codebase training. Rejected: RAGatouille (broken langchain deps in our stack); fine-tuning embeddings per repo (unnecessary for arena use).
- **impact:** New deps `pylate`, `voyager`. Config: `COLBERT_MODEL`, `COLBERT_DEVICE`, `COLBERT_LEARNED`. Score normalization before cross-encoder rerank blend. Golden-set re-run complete (`HYP-001` 2026-07-06 results; `backend/run_hyp001.py`).
- **supersedes:** hash-only default in `DEC-004` implementation note

### DEC-006: Multi-language AST chunking via tree-sitter registry (cheap grammars only)
- **date:** 2026-07-06 · **status:** accepted · **triggered_by:** DEC-001 Phase 1 gap; user lang priority list · **docs_updated:** `docs/decision_log.md` · **related:** `DEC-001`, `DEF-002`
- **decision:** Extend the chunker beyond Python using **drop-in `tree-sitter-*` PyPI wheels** and a **single shared walker** that maps per-language node types → `CodeChunk` (same fields as today). **Ship:** Rust (`.rs`), JavaScript (`.js`/`.mjs`/`.cjs`), TypeScript + TSX (`.ts`/`.tsx` — covers Node and React), Go (`.go`). **Gate:** Ruby (`.rb`) — add only after the registry pattern is proven and `tree-sitter-ruby` fits without bespoke plumbing. **Keep** line-window fallback for unsupported extensions and parse failures. **Do not** add languages that lack an importable grammar wheel or require a materially different chunk pipeline (see `DEF-002`).
- **rationale:** Polyglot repos are common in arena use (Rust services, Go backends, React frontends). Tree-sitter grammars share the same `Language`/`Parser` API; only node-type names differ — a small registry avoids per-lang modules. React needs no separate parser if TSX is covered by `tree-sitter-typescript`. Rejected: Java/C#/Haskell custom extractors; per-language reference parsers beyond lightweight regex on chunk bodies.
- **impact:** New optional deps (`tree-sitter-rust`, `tree-sitter-javascript`, `tree-sitter-typescript`, `tree-sitter-go`; `tree-sitter-ruby` later). Extend `SOURCE_EXTENSIONS`. Fixture repos + unit tests per language. Entity/graph reference extraction stays best-effort (Python-quality refs not required day one for new langs).

### DEF-002: Defer languages without drop-in tree-sitter grammar wheels
- **date:** 2026-07-06 · **status:** active · **triggered_by:** `DEC-006` · **docs_updated:** `docs/decision_log.md`
- **decision:** Do **not** add chunkers for Java, Kotlin, C/C++, C#, PHP, Swift, etc. until a `tree-sitter-*` wheel exists **and** node types map into the shared registry without a separate output format. Unsupported files continue to use line-window chunks.
- **rationale:** User constraint: cheap to add, no heavy plumbing when AST outputs diverge or parsers aren't importable. Custom grammar builds (.so compilation) fight the arena's “drop a zip” model.
- **revisit_when:** A language has a maintained PyPI grammar wheel and ≤~30 lines of registry config in the shared walker.

### DEC-007: Single context path via ContextEngine + RAGProvider DI
- **date:** 2026-07-06 · **status:** accepted · **triggered_by:** `DEC-001` Phase 1 open item; `DEC-002` impact note · **docs_updated:** `docs/decision_log.md` · **related:** `DEC-001`, `DEC-002`
- **decision:** Route **all** arena message handling (sync + SSE) through `ContextEngine` for directive parse → retrieval → budget → prompt assembly. `ContextEngine` must call `RAGProvider` via `dependencies.get_rag_provider_dep()`, not `rag_lmstudio` facade imports. Keep `rag_lmstudio.py` as backward-compatible shim for CLI/scripts only until migrated.
- **rationale:** Two context paths (`main.py` → facade, `ContextEngine` → facade) risk drift now that CodeRAG + ColBERT live in `LMStudioRAGProvider`. One path ensures retrieval config, citations, and budget see the same chunks.
- **impact:** Refactor `backend/main.py`, `backend/context_engine.py`; tests for ContextEngine with injectable `RAGProvider`.

### DEC-008: Manifest-based delta reindex (file-granular)
- **date:** 2026-07-06 · **status:** accepted · **triggered_by:** `DEC-001` freshness clause; full rebuild cost with ColBERT encode · **docs_updated:** `docs/decision_log.md` · **related:** `DEF-001`, `DEC-005`
- **decision:** On reindex/upload, compare `index_manifest.json` file entries (path, mtime, bytes) against the current snapshot. **Re-chunk and rebuild sidecars** (entity index, graph) only for added/changed/removed files. **v1 embedding policy:** if the delta is non-empty, rebuild **FAISS + ColBERT** indexes for the conversation (full re-encode of all chunks — simple, correct); optimize per-file embedding upsert in a follow-up only if rebuild latency hurts. Expose “changed since last index” in manifest API for UI/CLI.
- **rationale:** Manifest already records per-file metadata but `index_directory()` always full-scans. File-granular chunk merge reduces graph/entity work immediately; embedding upsert for Voyager/FAISS is non-trivial — ship correct full re-embed on delta first, optimize later.
- **impact:** `indexer.py` delta path; provider reindex endpoints; tests with fixture manifest diffs.

### DEC-009: Standardize on local BGE cross-encoder rerank (document LM Studio rerank as unused)
- **date:** 2026-07-06 · **status:** accepted · **triggered_by:** `LMSTUDIO_RERANK_MODEL` config drift · **docs_updated:** `docs/decision_log.md`, `RAG_LMSTUDIO.md` (when updated) · **related:** `DEC-001`
- **decision:** **Rerank stage uses `sentence-transformers` BGE** (`BAAI/bge-reranker-base`, configurable). Treat `LMSTUDIO_RERANK_MODEL` as **deprecated/unwired** — remove from docs or map to a future opt-in. Do not run rerank through LM Studio unless a later DEC explicitly adds it.
- **rationale:** Rerank is query-time batch scoring; local BGE avoids a second LM Studio round-trip and matches DEC-001 intent (“proper cross-encoder”). LM Studio env var was legacy from pre-CodeRAG cosine hack.
- **impact:** Align `rerank.py` model name with config; README/RAG_LMSTUDIO cleanup task.

### DEC-010: RRF fusion, append-only graph, code rerank; query router gated on HYP-002
- **date:** 2026-07-06 · **status:** accepted · **triggered_by:** live retrieval probe (graph pollution on broad queries); HYP-001 learned rerank homogenization; user review of modern retrieval plumbing · **docs_updated:** `docs/decision_log.md`, `backend/rag/fusion.py`, `backend/rag/query_router.py`, `backend/rag/retriever.py`, `backend/rag/rerank.py`, `backend/config.py`, `tests/unit/test_fusion.py` · **related:** `DEC-004`, `DEC-009`, `HYP-001`, `HYP-002`, `DEF-003` · **supersedes:** graph re-sort policy in `DEC-004` / `DEC-001` Phase 2 note (“always-on 1-hop” competing for rank slots)
- **decision:** Adopt a **DEC-010 production topology** (eval variant **F**; `FUSION_MODE=rrf`, `GRAPH_MODE=append` defaults):
  1. **Separate ranked lists** — ColBERT (or bi-encoder) semantic top-`RETRIEVE_CANDIDATES`; entity seed top-8 (scores used only for list order, not cross-scale merge).
  2. **RRF fuse** (`reciprocal_rank_fusion`, `k=60`) → candidate pool; replaces max-score union merge.
  3. **Cross-encoder rerank** on fused pool top-N → **answer slots** (top `RERANK_TOP_K`). When `fusion_mode=rrf`, **do not blend** prior retrieval scores (`blend_prior=False`); CE owns ordering. Default model remains `BAAI/bge-reranker-base` until HYP-002 matrix confirms a code-capable reranker (candidate: `jinaai/jina-reranker-v2-base-multilingual` via `RERANK_MODEL`).
  4. **README demotion** on answer slots (unchanged).
  5. **Graph append-only** — expand from top `graph_seed_k` reranked seeds (default 3); neighbors fill up to `graph_append_slots` (default 10) **after** answer slots, deduped, **no re-sort**. Trace queries use multi-hop expansion on append path. **Interim routing** via regex `query_router.route_query()` until HYP-002 promotes embedding router; architectural queries skip graph append.
  - **HYP-001 legacy:** variant **E** keeps `fusion_mode=max_score`, `graph_mode=resort`, `rerank_blend_prior=True` for apples-to-apples comparison.
  - **Rejected:** agentic repo exploration as core retrieval path (out of product scope); score-blend across RRF + CE scales; graph neighbors at fixed `0.45` competing in top-K.
- **rationale:** Live probe showed ColBERT found `arena.py` pre-rerank but BGE + 1-hop re-sort displaced it with `storage.py` neighbors — diverged from original “graph enriches context” intent. RRF is the standard fix for heterogeneous retriever score scales; append-only graph restores enrichment without rank pollution. Code reranker swap deferred to measured HYP-002 matrix, not assumed.
- **impact:** New `backend/rag/fusion.py`; `RetrievalConfig` flags `fusion_mode`, `graph_mode`, `graph_append_slots`, `use_query_router`, `rerank_blend_prior`; env `FUSION_MODE`, `GRAPH_MODE`; variant F in `RetrievalConfig.for_variant`. Extend `run_hyp001` / eval with variant F + architectural probe queries. Amend `DEC-009` default rerank model only after HYP-002 results.

### DEF-003: Defer chairman-requested trace expansion on follow-up turns
- **date:** 2026-07-06 · **status:** active · **triggered_by:** user review; `DEC-010` graph policy discussion · **docs_updated:** `docs/decision_log.md` · **related:** `DEC-007`, `DEC-010`
- **decision:** Do **not** expose `trace_expand` / graph deepening as a chairman tool in the current sprint. First message retrieval uses static pipeline (`ContextEngine` → `CodeRetriever`). Chairman may cite injected context only.
- **rationale:** Fits arena product shape (one-shot context injection for deliberation, not autonomous repo agent). DEC-010 append-only graph covers most cross-file context on trace queries. Chairman-driven re-retrieval is a second context path with budget/SSE implications.
- **revisit_when:** (a) HYP-002 shows regex router misses trace/architectural intent on real arena queries, **or** (b) users need multi-turn “dig into call chain X” without re-sending the whole repo — then add an explicit `POST /api/conversations/{id}/expand_trace` tool with line-budget cap and chairman-only invocation.

### HYP-002: Embedding router vs regex for query-conditioned retrieval policy
- **date:** 2026-07-06 · **status:** promoted to DEC-011 · **triggered_by:** `DEC-010` interim `query_router.route_query()`; golden `category` labels in `hyp001_golden_queries.json` · **docs_updated:** `docs/decision_log.md`, `backend/rag/query_router.py` · **related:** `DEC-010`, `HYP-001`
- **question:** Does a lightweight **embedding router** (query embedding → softmax over per-class prototypes from golden `category` labels) improve downstream recall@10 and stop graph pollution on architectural queries vs interim regex routing?
- **observation:** `is_trace_query` regex is too narrow (“council deliberation pipeline” needs `use_graph_append=False` but does not match trace patterns). Golden set already has `symbol_lookup`, `trace`, `cross_file`, `semantic` labels — bootstrap for prototypes without new annotation.
- **interventions:**
  - **Router A (baseline):** `route_query()` regex (shipped as interim in `query_router.py`).
  - **Router B:** embed query with `all-MiniLM-L6-v2` (or shared embedder); cosine to class centroids built from golden queries per `category` + augmented paraphrases; `argmax` → `QueryRoute` flags (`use_graph_append`, `graph_trace`, `graph_seed_k`).
  - **Router C (optional):** fine-tuned DistilBERT 5-class classifier if B plateaus.
- **test matrix:** Run variants **F** (DEC-010 stack) under Router A vs B on:
  - HYP-001 golden 18 queries (recall@10 by category + router classification accuracy vs golden `category`).
  - **Architectural probe set** (≥5 queries: e.g. “council deliberation pipeline”, “SSE streaming progress”, “context budgeting flow”) — metric: **answer-slot purity** (fraction of top-10 that are non-neighbor semantic hits, not graph-appended chunks).
  - **Reranker sub-matrix** on best router: `BAAI/bge-reranker-base` vs `jinaai/jina-reranker-v2-base-multilingual` (local `sentence-transformers`).
- **results:** *(2026-07-06, learned ColBERT + variant F; `docs/hyp002_results.json`; `python -m backend.run_hyp002 --reuse-colbert`)*
  | Cell | golden recall@10 | arch purity | router accuracy |
  |------|------------------|-------------|-----------------|
  | regex+mock/bge/jina | 0.833 | 0.650 | 0.333 |
  | embedding+mock/bge/jina | 0.833 | **0.833** | **0.833** |
  - **Router:** Embedding beats regex on arch purity (0.65→0.83) and classification (0.33→0.83) with no golden regression. Regex over-fires `trace` on symbol queries (`where is X defined`).
  - **Reranker:** BGE and **Jina v3** (`jinaai/jina-reranker-v3`) tie on all metrics; Jina v2 incompatible with current `transformers` (missing `create_position_ids_from_input_ids`). Added `einops` dep; v3 requires `trust_remote_code=True`.
  - **Architectural probes:** `arch01` (`council deliberation pipeline`) still 0% recall under embedding router — ColBERT finds wrong chunks; purity metric conflated with graph-off (0.0 purity = graph polluted top-10 before fix, or rerank miss).
  - **Conclusion:** Promote **embedding router** + variant **F** defaults. Jina v3 no gain on this set but adopted as default reranker per user preference (small eval set). Follow-up: fix `arch01` retrieval target.
- **status:** promoted to DEC-011

### DEC-011: Default embedding query router + Jina v3 reranker (variant F production)
- **date:** 2026-07-06 · **status:** accepted · **triggered_by:** HYP-002 results (`docs/hyp002_results.json`); user approval · **docs_updated:** `docs/decision_log.md`, `backend/rag/query_router.py`, `backend/rag/router_training.json`, `backend/config.py`, `backend/rag/rerank.py`, `backend/rag_lmstudio_provider.py` · **related:** `DEC-010`, `HYP-002`, `DEC-009` · **promotes:** `HYP-002`
- **decision:** Wire **production defaults** for DEC-010 variant F:
  - **Query router:** `QUERY_ROUTER=embedding` (default). `route_query()` lazy-loads `EmbeddingQueryRouter` from `backend/rag/router_training.json` (24 labeled queries). Fallback to `route_query_regex` on init failure or `QUERY_ROUTER=regex`.
  - **Reranker:** `RERANK_MODEL=jinaai/jina-reranker-v3` (default). `create_reranker()` sets `trust_remote_code=True` for Jina models. BGE remains available via env override.
  - Existing env toggles unchanged: `FUSION_MODE=rrf`, `GRAPH_MODE=append`.
- **rationale:** HYP-002 showed embedding router fixes regex trace over-match and architectural graph pollution without golden recall regression. Jina v3 tied BGE on golden/arch probes but user prefers Jina for likely out-of-sample code-rerank strength; eval set too small to differentiate.
- **impact:** `LMStudioRAGProvider` uses `create_reranker()`; `backend/run_hyp002.py` eval harness; `reset_routers()` for test isolation. **Supersedes** `DEC-009` default rerank model (BGE → Jina v3); BGE still via `RERANK_MODEL` env.
- **supersedes:** `DEC-009` default `RERANK_MODEL` choice (policy unchanged: local `sentence-transformers` cross-encoder)

### DIS-001: Local smoke test — ColBERT strong pre-rerank; Jina promotes docs/eval JSON
- **date:** 2026-07-07 · **status:** observed · **triggered_by:** post-DEC-011 smoke on `backend/` + `frontend/src/` + `docs/` (396 chunks) · **docs_updated:** `docs/decision_log.md` · **related:** `DEC-010`, `DEC-011`, `DEF-004`
- **finding:** Production variant F behaves as designed: embedding router sets `architectural` → `graph_append=False`; ColBERT+RRF finds correct code pre-rerank (`arena.py:run_full_arena`, `context_engine.py`, `main.py:send_message_stream`). **Jina v3 rerank** then promotes `docs/hyp002_results.json`, `docs/decision_log.md`, and `eval_*.py` above source files on broad queries — reranker trained on prose, not code AST chunks.
- **implication:** Graph pollution fixed; **rerank + index composition** are the remaining precision risks. Not a router regression.

### DEC-012: Default ColBERT to GPU with CPU fallback; pin torch CUDA wheel
- **date:** 2026-07-07 · **status:** accepted · **triggered_by:** local GPU index benchmark (~14× faster than CPU on RTX 3090 Ti); unpinned `torch 2.11+cu130` reported `cuda_available=False` on CUDA 12.5 driver · **docs_updated:** `docs/decision_log.md`, `backend/config.py`, `backend/rag/colbert.py`, `pyproject.toml`, `uv.lock`, `RAG_LMSTUDIO.md` · **related:** `DEC-005`, `DIS-001`
- **decision:** **`COLBERT_DEVICE=auto`** (default when unset): try `cuda`, fall back to `cpu`. Explicit overrides: `COLBERT_DEVICE=cuda|cpu`. Resolve once via `get_colbert_device()` in `backend/config.py`; log resolved device on auto. Pin **`torch==2.11.0`** from PyTorch **`cu126`** index (`pyproject.toml` / `uv.lock`) — satisfies `pylate`/`fast-plaid` and avoids the broken cu130 wheel on CUDA 12.5 hosts.
- **rationale:** CPU ColBERT encode dominated index rebuild (~0.28 s/chunk); GPU cut 396-chunk index from ~110 s to ~7.6 s. Unpinned torch pulled a cu130 build that failed CUDA init on the dev box. Auto-default keeps laptops/CI on CPU without env churn. `cu124` tops out at torch 2.6, below `fast-plaid`’s floor.
- **impact:** `build_semantic_index()` uses `get_colbert_device()`; `COLBERT_DEVICE` env doc updated. Re-run `uv lock` after pin. Users without NVIDIA GPU need no change.

### DEC-013: In-product stale index warning + one-click reindex
- **date:** 2026-07-07 · **status:** accepted · **triggered_by:** user question — how do users know the codebase needs another indexing pass? · **docs_updated:** `docs/decision_log.md`, `backend/rag/manifest.py`, `backend/rag_lmstudio_provider.py`, `backend/main.py`, `frontend/src/api.js`, `frontend/src/components/ChatInterface.jsx`, `frontend/src/components/ChatInterface.css`, `tests/unit/test_manifest_delta.py` · **related:** `DEC-008`, `DEC-012`
- **decision:** Surface index freshness in the chat UI:
  - **`GET /api/index_manifest`** now compares manifest against both the stored snapshot (`temp_repos/{id}`) and, when `repo_root` is configured, the **live git working tree** (`git_drift`).
  - Payload adds `needs_reindex`, `snapshot_stale`, `git_stale`, `git_drift`, `reasons`.
  - **`POST /api/conversations/{id}/reindex`** re-runs delta-aware indexing on the existing snapshot (ZIP workflow).
  - **ChatInterface** polls manifest on load/focus/60s; shows a banner when `needs_reindex` with counts + last-indexed time; **Reindex** button calls git reindex when `repo_root` is set, else snapshot reindex.
- **rationale:** Backend delta detection existed but was API-only; git users could edit files with `has_changes=false` on the snapshot. Users need an obvious in-product signal before trusting retrieval.
- **impact:** No query-time auto-reindex (user-triggered only). Git drift uses the same candidate path rules as `build_git_snapshot`.

### PIV-001: Agent control plane — agents drive, UI observes, humans await
- **date:** 2026-07-07 · **status:** accepted · **triggered_by:** product direction review; agent-orchestration vision for multi-model deliberation + CodeRAG · **docs_updated:** `docs/decision_log.md`, `docs/piv-001-agent-control-plane.md`, `docs/piv-001-checklist.md` · **related:** `DEC-001`, `DEC-007`, `DEC-010`, `DEC-011`, `DEC-013`, `DEF-003`, `DEF-004` · **doc:** [`docs/piv-001-agent-control-plane.md`](piv-001-agent-control-plane.md)
- **pivot:** Arena becomes an **agent control plane** (turn/step/resume APIs, structured `ArenaExecution`, index tools). UI becomes an **observatory**; humans enter via **`await_user`** checkpoints, not as default operator every turn. Disagreement (stage 1 + stage 2 rankings) stays first-class signal for drivers.
- **defers:** Full UI redesign, multi-agent supervisors, DEF-003 `expand_trace`, DEF-004 index hygiene — sequenced in `piv-001-checklist.md` Phases 0–3.

### DEF-004: Defer conditional rerank and index hygiene for eval/doc artifacts
- **date:** 2026-07-07 · **status:** active · **triggered_by:** `DIS-001` · **docs_updated:** `docs/decision_log.md` · **related:** `DEC-011`, `DEC-008`
- **decision:** Defer implementation. Interim guidance: exclude `docs/*_results*.json` from user indexes where possible; consider `RERANK_ENABLED=false` or BGE override if latency/precision hurt.
- **revisit_when:** (a) user indexes repos with large `docs/` or generated JSON, **or** (b) query-time Jina latency on CPU exceeds interactive budget (~30s/query observed at 396 chunks).
- **candidate fixes:** conditional rerank (skip CE when ColBERT margin high); demote `docs/` + `*.json` chunk types; per-file ColBERT upsert (DEC-008 follow-up) to avoid full re-encode on delta.