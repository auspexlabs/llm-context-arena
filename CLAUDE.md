# CLAUDE.md - Technical Notes for Curia

This file contains technical details, architectural decisions, and important implementation notes for future development sessions.

## Project Overview

**Curia** (formerly LLM Context Arena) is a multi-mode deliberation system where multiple LLMs collaboratively answer user questions. The system supports various orchestration modes including Council (with anonymized peer review), Fight, Stacks, Round Robin, and Complex modes.

## Decision log

Architecture and policy decisions are recorded in `docs/decision_log.md` — an append-only,
[ADRLight](https://github.com/Indubitable-Industries/ADRLight)-style ledger. Record
decisions, deferrals, and hypotheses there as you make them, following the format at the
top of that file; append only, never rewrite past entries (status updates excepted).

## Architecture

### Backend Structure (`backend/`)

**`config.py`**
- Contains `ARENA_MODELS` (list of OpenRouter model identifiers)
- Contains `CHAIRMAN_MODEL` (model that synthesizes final answer)
- Uses environment variable `OPENROUTER_API_KEY` from `.env`
- Backend runs on **port 8001** (NOT 8000 - user had another app on 8000)
- Context budgeting settings: `MODEL_CONTEXT_LIMITS`, `CONTEXT_SAFETY_MARGIN`, `OUTPUT_TOKEN_ALLOWANCE`

**`openrouter.py`**
- `query_model()`: Single async model query
- `query_models_parallel()`: Parallel queries using `asyncio.gather()`
- Returns dict with 'content' and optional 'reasoning_details'
- Graceful degradation: returns None on failure, continues with successful responses

**`arena.py`** - The Core Logic
- `MODE_RUNNERS` registry mapping mode names to runner functions
- `run_full_arena()`: Main entry point dispatching to mode-specific runners
- `run_mode_council()`: Council mode (formerly baseline) - answers → rankings → chairman synthesis
- `run_mode_round_robin()`: Round-robin drafting mode
- `run_mode_fight()`: Adversarial critique/defense mode
- `run_mode_stacks()`: Pair-merge-judge mode
- `run_mode_complex_iterative()`: Extract/expand iterative mode
- `run_mode_complex_questioning()`: Self-questioning mode
- `parse_ranking_from_text()`: Extracts "FINAL RANKING:" section for council mode
- `calculate_aggregate_rankings()`: Computes average rank position across peer evaluations

**`storage.py`**
- JSON-based conversation storage in `data/conversations/`
- Each conversation: `{id, created_at, messages[]}`
- Assistant messages contain: `{role, stage1, stage2, stage3}`
- Note: metadata (label_to_model, aggregate_rankings) is NOT persisted to storage, only returned via API

**`main.py`**
- FastAPI app with CORS enabled for localhost:5173 and localhost:3000
- POST `/api/conversations/{id}/message` returns metadata in addition to stages
- Streaming endpoint with SSE for progress callbacks
- Settings API at `/api/settings` for runtime configuration
- Directive parsing and context budgeting logic

**`rag_lmstudio.py`**
- RAG pipeline with FAISS vector store
- LM Studio integration for embeddings and reranking
- Git-based repository indexing
- Two-stage retrieval: FAISS → reranker

### Frontend Structure (`frontend/src/`)

**`App.jsx`**
- Main orchestration: manages conversations list and current conversation
- Handles message sending and metadata storage
- Theme and repo root state management
- Important: metadata is stored in the UI state for display but not persisted to backend JSON

**`components/ChatInterface.jsx`**
- Multiline textarea (3 rows, resizable)
- Enter to send, Shift+Enter for new line
- Repo dropzone for ZIP uploads
- Manual context picker with file tree
- Mode progress bar and breadcrumbs
- Mode timeline visualization

**`components/Sidebar.jsx`**
- Conversation list with mode badges
- Mode selector dropdown for new conversations
- Settings panel for arena models and chairman configuration

**`components/Stage1.jsx`**
- Tab view of individual model responses
- ReactMarkdown rendering with markdown-content wrapper

**`components/Stage2.jsx`**
- **Critical Feature**: Tab view showing RAW evaluation text from each model
- De-anonymization happens CLIENT-SIDE for display (models receive anonymous labels)
- Shows "Extracted Ranking" below each evaluation so users can validate parsing
- Aggregate rankings shown with average position and vote count

**`components/Stage3.jsx`**
- Final synthesized answer from chairman
- Green-tinted background (#f0fff0) to highlight conclusion

**Styling (`*.css`)**
- Light/dark mode theme support
- Primary color: #4a90e2 (blue)
- Global markdown styling in `index.css` with `.markdown-content` class
- 12px padding on all markdown content to prevent cluttered appearance

## Arena Modes

### Council Mode (default)
The original 3-stage deliberation with anonymized peer review:
1. Stage 1: Parallel queries → individual responses
2. Stage 2: Anonymize → Parallel ranking queries → evaluations + parsed rankings
3. Stage 3: Chairman synthesis with full context

### Round Robin Mode
Sequential improvement of a shared draft through multiple passes.

### Fight Mode
Adversarial deliberation: answers → critiques → defenses → chairman synthesis.

### Stacks Mode
Pair-based merging: pair answers → merge → critiques → judge → defenses → chairman.

### Complex Iterative Mode
Extract/expand iterative chain before chairman synthesis.

### Complex Questioning Mode
Self-questioning: answers → self-questions → brief → muse → chairman.

## Key Design Decisions

### Stage 2 Prompt Format (Council Mode)
The Stage 2 prompt is very specific to ensure parseable output:
```
1. Evaluate each response individually first
2. Provide "FINAL RANKING:" header
3. Numbered list format: "1. Response C", "2. Response A", etc.
4. No additional text after ranking section
```

### De-anonymization Strategy
- Models receive: "Response A", "Response B", etc.
- Backend creates mapping: `{"Response A": "openai/gpt-5.1", ...}`
- Frontend displays model names in **bold** for readability
- Users see explanation that original evaluation used anonymous labels
- This prevents bias while maintaining transparency

### Error Handling Philosophy
- Continue with successful responses if some models fail (graceful degradation)
- Never fail the entire request due to single model failure
- Log errors but don't expose to user unless all models fail

### Context Budgeting
- Per-model token limits defined in `MODEL_CONTEXT_LIMITS`
- Safety margin (default 85%) and output token allowance
- Chairman summarization when context exceeds limits

## Important Implementation Details

### Relative Imports
All backend modules use relative imports (e.g., `from .config import ...`) not absolute imports. This is critical for Python's module system to work correctly when running as `python -m backend.main`.

### Port Configuration
- Backend: 8001 (changed from 8000 to avoid conflict)
- Frontend: 5173 (Vite default)
- Update both `backend/main.py` and `frontend/src/api.js` if changing

### Markdown Rendering
All ReactMarkdown components must be wrapped in `<div className="markdown-content">` for proper spacing. This class is defined globally in `index.css`.

### Model Configuration
Models are configurable via the settings panel. Defaults are in `backend/config.py`. Chairman can be same or different from arena members.

## Common Gotchas

1. **Module Import Errors**: Always run backend as `python -m backend.main` from project root, not from backend directory
2. **CORS Issues**: Frontend must match allowed origins in `main.py` CORS middleware
3. **Ranking Parse Failures**: If models don't follow format, fallback regex extracts any "Response X" patterns in order
4. **Missing Metadata**: Metadata is ephemeral (not persisted), only available in API responses

## Testing Notes

Use `test_openrouter.py` to verify API connectivity and test different model identifiers before adding to arena. The script tests both streaming and non-streaming modes.

## Data Flow Summary

```
User Query
    ↓
Mode Selection → Dispatch to MODE_RUNNERS[mode]
    ↓
Mode-specific pipeline (varies by mode)
    ↓
Chairman synthesis with full context
    ↓
Return: {stage1, stage2, stage3, metadata}
    ↓
Frontend: Display with tabs + validation UI
```

The entire flow is async/parallel where possible to minimize latency.
