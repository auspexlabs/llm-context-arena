# LLM Context Arena

**Multi-model deliberation with code context — a fork of Andrej Karpathy's [llm-council](https://github.com/karpathy/llm-council).**

All credit to [Karpathy](https://twitter.com/karpathy) for the original idea: put several frontier models in a room, let them answer independently, review each other anonymously, and have a chairman synthesize a final answer. That three-stage council is elegant and we kept it as the default mode.

This fork extends that foundation into an **arena** — same local-first vibe-coded spirit, more ways to make models argue, and machinery for grounding answers in your codebase.

## What changed in this fork

| Area | Addition |
|------|----------|
| **Modes** | Six orchestration strategies: Council, Round Robin, Fight, Stacks, Complex Iterative, Complex Questioning |
| **RAG** | Per-conversation repo indexing (ZIP or git snapshot) via LM Studio embeddings + FAISS *(being upgraded — see P1 below)* |
| **Context** | Per-model token budgets, chairman summarization when context is huge, manual file picker |
| **Directives** | Inline `@norag`, `@summarize`, `@tokenbudget`, `@cite`, `@lastchair`, and more |
| **UI** | Mode timeline, context panel, repo dropzone, streaming progress, light/dark theme |

**Roadmap:** Real code-aware RAG (AST chunking, proper reranking) is next. Bicameral Mind mode and cost tracking are planned.

**Repo:** [github.com/auspexlabs/llm-context-arena](https://github.com/auspexlabs/llm-context-arena) (private)

---

## Quick Start

```bash
uv sync
cd frontend && npm install && cd ..
cp .env.example .env   # add OPENROUTER_API_KEY
./start.sh             # backend :8001, frontend :5173
```

For RAG, run LM Studio with embedding models — see [RAG_LMSTUDIO.md](RAG_LMSTUDIO.md).

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
- **ZIP repo upload** per conversation - drop a codebase, get context-aware answers
- **FAISS vector indexing** with LM Studio embeddings (`nomic-embed-text-v1.5`)
- **Two-stage retrieval**: vector search → BGE reranker → neighbor chunk expansion
- **Git-based indexing**: build context from `git ls-tree` + working tree changes

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
- **Upload progress** with indexing feedback
- **Scroll-to-bottom** shortcut

---

## Configuration

### Arena Models

Edit `backend/config.py` or use the settings panel:

```python
ARENA_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

CHAIRMAN_MODEL = "openai/gpt-5.1"
```

### Environment

```bash
# Required
OPENROUTER_API_KEY=sk-or-v1-...

# LM Studio (for local RAG)
LMSTUDIO_BASE_URL=http://localhost:1234/v1
LMSTUDIO_EMBED_MODEL=text-embedding-nomic-embed-text-v1.5
LMSTUDIO_RERANK_MODEL=text-embedding-bge-reranker-large

# Retrieval tuning
RERANK_ENABLED=true
RETRIEVE_CANDIDATES=50
RERANK_TOP_K=20
CONTEXT_CHUNK_CAP=60
```

### Context Limits

| Model | Default Context | Env Override |
|-------|-----------------|--------------|
| `openai/gpt-5.1` | 400,000 | `CTX_LIMIT_GPT_5_1` |
| `google/gemini-3-pro-preview` | 1,048,576 | `CTX_LIMIT_GEMINI_3_PRO_PREVIEW` |
| `anthropic/claude-sonnet-4.5` | 1,000,000 | `CTX_LIMIT_CLAUDE_SONNET_4_5` |
| `x-ai/grok-4` | 256,000 | `CTX_LIMIT_GROK_4` |

Safety margin: 85% (`CONTEXT_SAFETY_MARGIN=0.85`)
Output allowance: 4000 tokens (`OUTPUT_TOKEN_ALLOWANCE=4000`)

---

## Tech Stack

- **Backend:** FastAPI, Python 3.10+, async httpx, OpenRouter API
- **Frontend:** React 19, Vite 7, react-markdown, react-dropzone
- **RAG:** LangChain, FAISS, LM Studio (OpenAI-compatible API)
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

- [RAG_LMSTUDIO.md](RAG_LMSTUDIO.md) - LM Studio setup and RAG details
- [PLAN.md](PLAN.md) - Feature roadmap and mode specifications
- [COUNCIL_OG_README.md](COUNCIL_OG_README.md) - Original Karpathy README

---

## Acknowledgments

**Massive thanks to [Andrej Karpathy](https://twitter.com/karpathy)** for [llm-council](https://github.com/karpathy/llm-council). The original 3-stage council (answer → anonymous peer review → chairman synthesis) is the spine of this project.

Karpathy's vibe code philosophy — minimal, readable, hackable — is alive here. This is still a Saturday hack project. Fork it, break it, make it yours.