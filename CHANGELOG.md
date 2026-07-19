# Changelog

## Unreleased — Curia rebrand (PIV-003)

### Breaking Changes
- GitHub repository: `llm-context-arena` → [`Auspex-Aerie/curia`](https://github.com/Auspex-Aerie/curia)
- Python package: `llm-context-arena` → `curia`
- MCP entry point: `curia-mcp` (preferred); `arena-mcp` deprecated alias
- MCP server id: `curia` (was `llm-context-arena`)
- Env vars: `CURIA_API_URL`, `CURIA_AGENT_ID`, `CURIA_MCP_*` preferred; `ARENA_*` client/MCP aliases retained for one release cycle

### Added
- Apache License 2.0 with an Auspex Labs attribution `NOTICE`
- GitHub Actions CI (unit tests + frontend build)

### Changed
- Replaced the remaining inherited implementation in the current source tree and established Apache-2.0 as the license from this transition forward. Historical revisions retain their historical terms; applicable attribution remains required, and future separately developed offerings cannot alter already-released terms.

## v0.2.0 - LLM Context Arena rebrand + multi-mode orchestration

### Breaking Changes
- Renamed project from "LLM Council" to "LLM Context Arena"
- `backend/council.py` → `backend/arena.py`
- `COUNCIL_MODELS` config → `ARENA_MODELS` (backwards compat alias available)
- Settings key `council_models` → `arena_models` (auto-migrated on load)

### New Features
- **Multi-mode orchestration**: 6 arena modes (council, round_robin, fight, stacks, complex_iterative, complex_questioning)
- **MODE_RUNNERS registry**: Extensible pattern for adding new orchestration modes
- **Context budgeting**: Per-model token limits with chairman summarization for long contexts
- **Directive system**: @norag, @summarize, @tokenbudget, @cite directives in prompts
- **Git-based indexing**: Reindex from local git repository with configurable globs
- **Mode timeline UI**: Visual timeline of mode execution steps
- **Progress callbacks**: SSE streaming with step-by-step progress updates

### Improvements
- Settings panel for runtime model configuration
- Light/dark theme support
- Mode badges and descriptions in UI
- Breadcrumb trail for mode execution progress

## v0.1.0 - Initial RAG + manual context release
- Local LM Studio retrieval: embed with `text-embedding-nomic-embed-text-v1.5`, rerank with `text-embedding-bge-reranker-large`, neighbor expansion, and configurable caps.
- Manual context controls: repo tree picker, `@file:` / `@token` directives, and manual context that bypasses RAG when present.
- Context clarity: collapsible panel with unique file/line summary, scores, and manual vs RAG tags; manual full files summarized.
- UX helpers: stop button to abort streaming, scroll-to-bottom shortcut, and clearer upload/indexing feedback.
- CLI tooling: `python -m backend.cli_context` to preview what context would be sent for a query (with optional manual files).
