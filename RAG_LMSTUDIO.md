# RAG + LM Studio additions

This fork of Andrej Karpathy's **llm-council** adds local RAG and repo ZIP upload, now rebranded as **LLM Context Arena**. The upstream project is awesome; this document only covers the incremental pieces added here.

## What was added
- **Repo ZIP upload per conversation** (`/api/conversations/{id}/upload_repo`): unzips into `temp_repos/{id}`, AST-chunks content, and builds per-conversation indexes under `data/conversations/{id}_*`.
- **CodeRAG pipeline**: tree-sitter chunking (Python, Rust, JS/TS/TSX, Go), entity index, code graph, hybrid retrieval, and cross-encoder rerank.
- **Semantic backends** (mutually exclusive, `SEMANTIC_BACKEND`):
  - `colbert` (default): learned PyLate ColBERT index (`{id}_colbert/`)
  - `biencoder`: FAISS + LM Studio nomic embeddings (`{id}_faiss/`)
- **Rerank**: local `sentence-transformers` BGE cross-encoder (`RERANK_MODEL`, default `BAAI/bge-reranker-base`) — **not** LM Studio.
- **Auto-context**: every user message is augmented with retrieved snippets via `ContextEngine` → `RAGProvider`.
- **Manual context**: file picker + @directives to force files/snippets; when manual context is supplied, RAG retrieval is skipped.
- **Manifest delta reindex**: compares `data/index_manifest.json` file entries; re-chunks changed files and rebuilds indexes on delta. `GET /api/index_manifest` exposes `changed_since_index` per conversation.
- **Git-based indexing**: reindex from a local git repository with configurable include/exclude globs.
- **UX niceties**: stop button, scroll-to-bottom, collapsible context panel, mode timeline, and a CLI (`python -m backend.cli_context`) to inspect what would be sent.

## LM Studio setup
LM Studio is required **only when using the bi-encoder path** (`SEMANTIC_BACKEND=biencoder`).

- Run LM Studio with the embedding model loaded:
  - Embedder: `text-embedding-nomic-embed-text-v1.5`
- Endpoint: `/v1/embeddings` via `langchain_openai.OpenAIEmbeddings`
- Configure in `.env`: `LMSTUDIO_BASE_URL`, `LMSTUDIO_EMBED_MODEL`

ColBERT (default) and BGE rerank run locally via `pylate` and `sentence-transformers` — no LM Studio rerank endpoint.

> **Deprecated:** `LMSTUDIO_RERANK_MODEL` is unwired (DEC-009). Use `RERANK_MODEL` instead.

## Environment variables

### LM Studio (bi-encoder path)
- `LMSTUDIO_BASE_URL` (default `http://localhost:1234/v1`)
- `LMSTUDIO_EMBED_MODEL` (default `text-embedding-nomic-embed-text-v1.5`)
- `LMSTUDIO_API_KEY` (ignored by LM Studio; default `lmstudio`)

### Semantic retrieval
- `SEMANTIC_BACKEND` — `colbert` (default) or `biencoder`
- `COLBERT_LEARNED` (default `true`), `COLBERT_MODEL`, `COLBERT_DEVICE`

### Rerank + retrieval tuning
- `RERANK_MODEL` (default `BAAI/bge-reranker-base`)
- `RERANK_ENABLED` (default `true`)
- `RETRIEVE_CANDIDATES` (default `50`), `RERANK_TOP_K` (default `20`)
- `CONTEXT_CHUNK_CAP` (default `60`)

### Indexing
- `INDEX_MANIFEST_PATH` (default `data/index_manifest.json`)
- `INDEX_INCLUDE_GLOBS`, `INDEX_EXCLUDE_GLOBS`, `INDEX_INCLUDE_UNTRACKED`

### Arena
- Model API key for completion (e.g., `OPENROUTER_API_KEY`), set in your shell or `.env` (not committed).

## Retrieval flow (query time)
1. **Semantic**: ColBERT *or* FAISS bi-encoder (per `SEMANTIC_BACKEND`)
2. **Union** with entity-seed hits from query symbols/paths
3. **Rerank**: BGE cross-encoder (`CrossEncoderReranker`)
4. README demotion + graph expansion (1-hop / trace multi-hop)

## Running locally
1. For bi-encoder mode: start LM Studio with the embedding model on `http://localhost:1234/v1`. ColBERT-only runs skip this step.
2. Backend: `source .venv/bin/activate` then `uvicorn backend.main:app --reload --port 8001`.
3. Frontend: `nvm use` (uses `.nvmrc`, Node 22+) then `cd frontend && npm install && npm run dev`.
4. Visit the frontend (Vite dev server) and create/select a conversation.
5. Drop a repo `.zip` into the dropzone. The status message will include chunk counts and elapsed time.
6. Ask questions; retrieved context is prepended and also shown in the UI ("Context used" with file names and line counts).

## Logging and observability
- Indexing logs: counts of files/chunks, skipped items, and embedding failures.
- Retrieval logs: number of docs, total characters, and source filenames.
- Upload response includes duration `(took Ns)`.

## Deployment notes
- Keep secrets (e.g., `OPENROUTER_API_KEY`) in environment, not in code.
- Provide a `.env.example` and load environment in process manager/systemd.
- Run backend as a service (systemd or similar) after setting env vars; ensure LM Studio is reachable when `SEMANTIC_BACKEND=biencoder`.
- Frontend can be built with `npm run build` and served by any static host or Vite preview; respect `VITE_API_BASE` if backend is not on localhost.

## Attribution
Base project by **Andrej Karpathy** (llm-council). This document and the RAG/LM Studio additions describe the fork-specific features, now under the **LLM Context Arena** branding.