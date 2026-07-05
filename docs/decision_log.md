# Decision Log

Append-only decision ledger for `llm-context-arena`, in the style of
[ADRLight](https://github.com/Indubitable-Industries/ADRLight). One file, one
causal history. We record *decisions, deferrals, hypotheses, discoveries, and
incidents* — not tasks (those live in `PLAN.md` / issue trackers).

## How to use this ledger

- **Append-only.** Never delete or rewrite a past entry. The only edit allowed on
  an old entry is a **status update** (e.g. `accepted` → `superseded by DEC-007`).
- **Seven independent ID spaces**, each zero-padded and monotonic: `DEC`, `DEF`,
  `HYP`, `DIS`, `INC`, `OUT`, `BOT`. The ledger allocates IDs — even an external incident
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
- **date:** 2026-07-05 · **status:** open · **triggered_by:** `DEC-001` Phase 3 gate · **docs_updated:** `docs/decision_log.md` · **related:** `agentdocs/plans/coderag_pro_plan.md`
- **question:** After Phase 1–2, is bi-encoder + cross-encoder rerank + 1-hop graph sufficient for our golden code queries, or does ColBERT (token-level late interaction) materially improve recall@10?
- **observation:** Coderag plan centers ColBERT for “exact file/object retrieval”; current nomic bi-encoder misses symbols that never appear in natural-language phrasing.
- **interventions:** Build a 15–20 query golden set from real arena conversations (auth flow, “where is X defined”, cross-file call chains). Measure recall@10 after Phase 1, then Phase 2.
- **test matrix:** (A) bi-encoder + rerank only; (B) + entity seed; (C) + 1-hop graph; (D) ColBERT index on same chunks.
- **results:** *(pending P1 Phase 1–2 completion)*

### DEC-002: Ship CodeRAG Phases 1–3 (pre-ColBERT)
- **date:** 2026-07-05 · **status:** accepted · **triggered_by:** `DEC-001` · **docs_updated:** `docs/decision_log.md`, `backend/rag/`, `backend/rag_lmstudio_provider.py`, `backend/rag_lmstudio.py`, `backend/rag_provider.py`, `backend/dependencies.py`, `pyproject.toml`, `tests/unit/test_*.py`, `tests/fixtures/` · **related:** `HYP-001`
- **decision:** Implement and land **Phases 1–3** of `DEC-001` in a new `backend/rag/` package, with `LMStudioRAGProvider` as the concrete `RAGProvider` and `rag_lmstudio.py` as a thin backward-compatible facade. ColBERT / late-interaction retrieval remains **gated** on `HYP-001` golden-query metrics — not shipped in this change.
  - **Phase 1:** Tree-sitter Python chunking (line-window fallback); `CodeChunk` metadata + `path:line_start-line_end` citations; FAISS bi-encoder retrieval; injectable `CrossEncoderReranker` (BGE via `sentence-transformers` when enabled); hybrid symbol/path seeding.
  - **Phase 2:** `EntityIndex` (def/class → location); `CodeGraph` (NetworkX) with static reference edges; always-on 1-hop expansion; README demotion.
  - **Phase 3:** Multi-hop `trace_expand` for trace-style queries; pattern edges from `patterns.yaml`.
- **rationale:** Replaces character-split + cosine-on-embeddings “rerank” with syntactically aware chunks and a proper rerank stage — the 80% win per `DEC-001`. Phases 1–3 are testable without LM Studio (injectable embedder/reranker mocks). ColBERT deferred until baseline recall@10 is measured.
- **impact:** 89 unit tests green; new deps (`tree-sitter`, `tree-sitter-python`, `networkx`, `sentence-transformers`, `pyyaml`). `main.py` still calls `rag_lmstudio` facade — `ContextEngine` wiring is a follow-up.
- **supersedes:** pre-DEC-002 `rag_lmstudio.py` monolith implementation