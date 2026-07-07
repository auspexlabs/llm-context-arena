# RAG + LM Studio additions

This fork of Andrej Karpathy's **llm-council** adds local RAG and repo ZIP upload, now rebranded as **LLM Context Arena**. The upstream project is awesome; this document only covers the incremental pieces added here.

## What was added
- **Repo ZIP upload per conversation** (`POST /api/conversations/{id}/upload_repo`): unzips into `temp_repos/{id}`, AST-chunks content, and builds per-conversation indexes under `data/conversations/{id}_*`.
- **Git snapshot + reindex** (`POST /api/conversations/{id}/reindex_git`): copies tracked (and optionally untracked) files from a configured repo root, then indexes.
- **Snapshot reindex** (`POST /api/conversations/{id}/reindex`): delta-aware re-encode of the existing upload snapshot (no git, no re-upload).
- **CodeRAG pipeline**: tree-sitter chunking (Python, Rust, JS/TS/TSX, Go), entity index, code graph, hybrid retrieval, RRF fusion, cross-encoder rerank.
- **Semantic backends** (mutually exclusive, `SEMANTIC_BACKEND`):
  - `colbert` (default): learned PyLate ColBERT index (`{id}_colbert/`), GPU by default (`COLBERT_DEVICE=auto`)
  - `biencoder`: FAISS + LM Studio nomic embeddings (`{id}_faiss/`)
- **Rerank**: local `sentence-transformers` cross-encoder (default `jinaai/jina-reranker-v3`) — **not** LM Studio. Override with `RERANK_MODEL=BAAI/bge-reranker-base`.
- **Query router** (`QUERY_ROUTER=embedding`, default): embedding classifier over query intent (trace vs architectural vs symbol lookup, etc.); regex fallback via `QUERY_ROUTER=regex`.
- **Auto-context**: every user message is augmented with retrieved snippets via `ContextEngine` → `RAGProvider`.
- **Manual context**: file picker + @directives to force files/snippets; when manual context is supplied, RAG retrieval is skipped.
- **Manifest delta reindex**: compares `data/index_manifest.json` file entries; re-chunks changed files and rebuilds indexes on delta.
- **Index freshness UI**: polls `GET /api/index_manifest`, compares snapshot and live git repo (when `repo_root` is set), shows stale banner + reindex button.
- **UX niceties**: stop button, scroll-to-bottom, collapsible context panel, mode timeline, and a CLI (`python -m backend.cli_context`) to inspect what would be sent.

## LM Studio setup
LM Studio is required **only when using the bi-encoder path** (`SEMANTIC_BACKEND=biencoder`).

- Run LM Studio with the embedding model loaded:
  - Embedder: `text-embedding-nomic-embed-text-v1.5`
- Endpoint: `/v1/embeddings` via `langchain_openai.OpenAIEmbeddings`
- Configure in `.env`: `LMSTUDIO_BASE_URL`, `LMSTUDIO_EMBED_MODEL`

ColBERT (default) and Jina/BGE rerank run locally via `pylate` and `sentence-transformers` — no LM Studio rerank endpoint.

> **Deprecated:** `LMSTUDIO_RERANK_MODEL` is unwired (DEC-009). Use `RERANK_MODEL` instead.

## Environment variables

### LM Studio (bi-encoder path)
- `LMSTUDIO_BASE_URL` (default `http://localhost:1234/v1`)
- `LMSTUDIO_EMBED_MODEL` (default `text-embedding-nomic-embed-text-v1.5`)
- `LMSTUDIO_API_KEY` (ignored by LM Studio; default `lmstudio`)

### Semantic retrieval
- `SEMANTIC_BACKEND` — `colbert` (default) or `biencoder`
- `COLBERT_LEARNED` (default `true`), `COLBERT_MODEL` (default `colbert-ir/colbertv2.0`)
- `COLBERT_DEVICE` (default `auto`) — `auto` uses CUDA when available, else CPU; override with `cuda` or `cpu`

### Fusion, graph, routing
- `QUERY_ROUTER` (default `embedding`) — `embedding` | `regex`
- `FUSION_MODE` (default `rrf`) — `rrf` | `max_score`
- `GRAPH_MODE` (default `append`) — `append` | `resort` (legacy eval path)

### Rerank + retrieval tuning
- `RERANK_MODEL` (default `jinaai/jina-reranker-v3`)
- `RERANK_ENABLED` (default `true`)
- `RETRIEVE_CANDIDATES` (default `50`), `RERANK_TOP_K` (default `20`)
- `CONTEXT_CHUNK_CAP` (default `60`)

### Indexing
- `INDEX_MANIFEST_PATH` (default `data/index_manifest.json`)
- `INDEX_INCLUDE_GLOBS`, `INDEX_EXCLUDE_GLOBS`, `INDEX_INCLUDE_UNTRACKED`

### Arena
- Model API key for completion (e.g., `OPENROUTER_API_KEY`), set in your shell or `.env` (not committed).

## Retrieval flow (query time, production defaults)
1. **Query router** — embedding classifier (or regex) sets graph/trace policy for this query
2. **Semantic** — ColBERT *or* FAISS bi-encoder top-`RETRIEVE_CANDIDATES`
3. **Entity seed** — symbol/path hits (separate ranked list)
4. **RRF fuse** (`FUSION_MODE=rrf`, `k=60`) → candidate pool
5. **Cross-encoder rerank** (Jina v3 default) on fused pool → answer slots
6. **README demotion** on answer slots
7. **Graph append-only** (`GRAPH_MODE=append`) — neighbors after answer slots, no re-sort (skipped for architectural queries)

## Index freshness
- `GET /api/index_manifest?conversation_id={id}` returns manifest + `changed_since_index`:
  - `needs_reindex` — true when user should reindex before trusting retrieval
  - `snapshot_stale` — `temp_repos/{id}` differs from last manifest
  - `git_stale` / `git_drift` — live repo root (from settings) differs from last index
- UI shows a banner when stale; **Reindex** calls `reindex_git` (if repo root set) or `reindex` (snapshot only).

## Running locally
1. `uv sync` from project root (installs ColBERT/PyTorch deps; GPU wheel via cu126 index).
2. For bi-encoder mode only: start LM Studio with the embedding model on `http://localhost:1234/v1`.
3. Backend: `uv run python -m backend.main` or `./start.sh` (port **8001**).
4. Frontend: `cd frontend && npm install && npm run dev` (port **5173**).
5. Visit the frontend, create/select a conversation, set **repo root** in Settings if using git workflow.
6. Drop a repo `.zip` or click **Reindex from git**. Status messages include chunk counts and timing.
7. Ask questions; retrieved context is prepended and shown in the UI ("Context used" with file names and line counts).

## Logging and observability
- Indexing logs: counts of files/chunks, skipped items, and embedding failures.
- Retrieval logs: number of docs, total characters, and source filenames.
- Upload response includes duration `(took Ns)`.
- Eval harnesses: `python -m backend.run_hyp001`, `python -m backend.run_hyp002` (see `docs/hyp*_results.json`).

## Deployment notes
- Keep secrets (e.g., `OPENROUTER_API_KEY`) in environment, not in code.
- Provide a `.env.example` and load environment in process manager/systemd.
- Run backend as a service after setting env vars; ensure LM Studio is reachable when `SEMANTIC_BACKEND=biencoder`.
- Frontend can be built with `npm run build` and served by any static host or Vite preview; respect `VITE_API_BASE` if backend is not on localhost.
- ColBERT GPU encode needs NVIDIA driver + CUDA; falls back to CPU automatically when unavailable.

## Attribution
Base project by **Andrej Karpathy** (llm-council). This document and the RAG/LM Studio additions describe the fork-specific features, now under the **LLM Context Arena** branding.