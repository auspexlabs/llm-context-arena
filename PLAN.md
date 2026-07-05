## Council Feature Plan

### Threading / Concurrency
- Keep one request = one coroutine chain; no thread pools needed. Round Robin, stacks, and iterative modes run as a linear state machine per turn.
- Avoid background timers; use explicit stages. If we need parallel fan-out (baseline, Fight), rely on existing parallel model calls only.
- Shared context objects should be immutable per stage; copy forward what each stage needs (prevents bleed between modes).

### Command Directives (low/med lift)
- Parsing order: normalize to lowercase, process left-to-right; store directives in request metadata; strip from model input.
- `@norag` / `@raw`: hard-stop retrieval; only manual context + user text go through. Implementation: set `skip_rag=True`; bypass retriever; mark in trace/UI.
- `@summarize`: force summarize-first path even if under budget. Implementation: set `force_summarize=True`; route through Chairman summarizer.
- `@tokenbudget <n>`: set per-turn cap (user + RAG/manual + system + expected output). If `n` < system minimum, warn and clamp. Implementation: parse int; set `budget_override=n`; validation error returns a user-visible warning and ignores directive.
- `@trace`/`@debug`: attach retrieval details (files, byte ranges, scores, manual vs RAG flag) to response metadata/UI. Implementation: include trace payload in response JSON and render toggle in UI; keep off by default.
- `@short` / `@detailed`: set an instruction tag; prepend brief guidance to prompts. Implementation: add `length_hint` flag; prepend instruction string to all agent/chairman prompts.
- `@cite`: require citations when RAG/manual present. Implementation: add cite instruction to prompts; downstream UI may check for bracket pattern but do not block responses.
- `@noexecute`: block tool calls/side effects for this turn. Implementation: set `tools_allowed=False`; skip tool runner; include note in trace.
- `@reset`: clear conversation state, keep system prompt; log reset event. Implementation: flush stored history for this convo; return confirmation message instead of running the council.
- Optional plumbing: `@temp <0-1>`, `@maxtokens <n>`, `@safe`/`@relaxed` if multiple safety tiers exist. Implementation: override per-call model params; clamp values; invalid → warning.
- Precedence: `@norag/@raw` wins over auto-RAG; `@tokenbudget` overrides defaults; `@summarize` forces summarizer even if budget ok; `@reset` short-circuits all processing.

### Summarize-First and Token Budget
- Budget formula (per turn): system prompt + user text + manual context + RAG chunks + expected output allowance. Cap from default or `@tokenbudget`.
- If over cap or `@summarize`: Chairman runs a summarize pass.
  - Inputs: user text, manual context, RAG chunks, mode, length hint, cite flag.
  - Output: compressed context bundle + a short summary of the user ask; include provenance list (file:line ranges).
  - Panel prompt gets: user text (untouched), compressed context, note that context was summarized, cite requirement if applicable.
- UI: badge “Summarized context” + token count pre/post; keep original context stored for audit.
- Guardrail: if still over cap after summarization, drop lowest-ranked chunks or ask user to reduce input; log truncation in trace.
- Multi-round guardrails: each stage/hop runs the same budget check using the minimum context window of participating models. After each round, recompute budget before proceeding; if over, summarize the transcript so far (or skip the smallest-window model for that hop and log it).
- Safety margin: target 80–85% of the minimum context window to account for tokenizer variance.

### Pasted Content Handling
- Classification: small (< configurable threshold) stays inline as user text; large becomes a “manual attachment” with its own name/hash and is excluded from the main user text string.
- Budget treatment: attachments count toward the same token budget as RAG/manual files; subtract their size before adding RAG. If budget is exceeded, summarize or chunk-retrieve from the attachment instead of injecting it raw.
- Storage: per-conversation cache (memory or temp file) with a manifest entry (name, hash, size). Allow “pin” to persist across turns; otherwise “one-shot” for that message only.
- Usage modes:
  - Inline injection (small).
  - Summarize-then-inject (large; default).
  - Attach-and-retrieve: build a tiny per-convo index over the paste and retrieve relevant snippets on demand.
- Safety: summarization risk depends on content (spec). Provide a toggle: “use full text” vs “summarize first.” If the user forces full text, warn about token impact; if summarizing, keep provenance and expose the summary in the context panel.
- UI: show pasted attachments alongside RAG/manual context with size, how it was used (inline/summarized/retrieved), and a token cost estimate; allow remove/replace.

### RAG / Codebase Source
- Replace zip build with Git + working tree walk:
  - Baseline file list: `git ls-tree -r --name-only HEAD`.
  - Overlay working tree changes: `git status --porcelain` to pick up modified/untracked; include untracked if allowed.
  - Allow include/exclude globs (e.g., node_modules, dist, .git ignored).
- Manifest: store file path, size, mtime, hash (fast hash of content) to skip unchanged during reindex. Location: `data/index_manifest.json`.
- Diff view: `git diff --name-only HEAD` + untracked to show “changed since last index” in CLI/UI.
- Chunking: language-aware splitter where possible; fall back to line windows; cache chunk hashes.
- Failure fallback: if Git unavailable, fall back to current ZIP flow with a warning.
- CLI: `python -m backend.cli_context --reindex --from-head --include-untracked` to rebuild; expose last index time in UI.

### Modes (state machines)
- **Baseline (current)**: All answer with RAG/manual → vote → Chairman bases on top vote, merges non-conflicts. Prompt nudge: “use top-ranked as spine; integrate unique insights when consistent.”
- **Round Robin (sequential)**: A1 sees prompt+RAG, replies → A2 sees last reply + original context, edits/extends → A3 ... → Chairman finalizes. UI shows “turn N of M.” No parallel calls.
- **Fight**: All answer with RAG → everyone critiques peers (one pass) → each defends once → Chairman writes full debate summary; no voting. Prompts emphasize pointed critique and defense brevity.
- **Stacks**: Two answer with RAG → Chairman merges with “optionality” bias (do not drop ideas) → two critics attack → Chairman judges against original context → original two defend → Chairman final report without original context, includes both sides. Store original context only for judge step.
- **Complex Iterative (Extract/Expand alternating)**: Agent1 Extracts (summary + suggested next prompt) with RAG → Agent2 Expands → Agent3 Extracts → Agent4 Expands (configurable length) → Chairman final. Each step sees only prior step’s summary/suggested prompt/response plus original context on its first turn. Prompt tags: `mode=extract` vs `mode=expand`.
- **Complex Questioning**: All answer with RAG → all review others and question their own replies → Chairman summarizes → feed summary back (no original context) → agents muse → Chairman final. Ensure provenance note that second muse round lacks original context.
- Mode plumbing: mode stored on conversation; stage runner drives per-turn prompts and visible transcript; tag each response with role (answer, critique, defense, muse).
- Safety: max turns per mode to prevent runaway loops; guard token budgets at each hop (using min-context and safety margin).

### Conversation Type Selector
- On “New Conversation,” present a required “Type” selector mapped to modes (Baseline, Round Robin, Fight, Stacks, Complex Iterative, Complex Questioning). Default to Baseline.
- Persist the chosen mode in conversation metadata; the runner uses it for the entire thread (unless explicitly changed via a future mode-switch control).
- UI shows mode badge on the chat; warn if a mode change is requested mid-thread (either disallow or start a new conversation).
- Setting dependencies: per-mode token guardrails and turn limits enforced from mode metadata.

### Prompt Sketches (templates)
- Baseline answer (per agent, with directives):
```
System: You are Agent {i}. Answer the user. Use provided context; if missing, say so. {cite_flag} {length_hint}
Context: {context_summaries_or_chunks}
User: {user_prompt}
```
- Baseline ranking (existing pattern): keep “FINAL RANKING” format; add: “Prefer responses that cite context and flag gaps.”
- Chairman final (baseline): “Use top-ranked as spine; integrate non-conflicting strengths; cite sources; be concise if @short.”

- Round Robin:
```
System: You are Agent {i}, turn {t}/{T}. You see the latest draft. Improve accuracy/clarity; keep useful detail. Cite if using context.
Original context: {context}
Latest draft: {prior_text}
User: {user_prompt}
```
Chairman: “Produce final answer using last draft as base; fix errors, resolve contradictions.”

- Fight:
  - Answer: same as baseline answer.
  - Critique prompt:
```
System: Critique peers. Point out errors, missing context, risks. Be specific and brief. Cite when possible.
Your answer: {self_answer}
Peers: {answers}
```
  - Defense prompt:
```
System: Defend your answer against critiques. Fix errors if valid; note remaining disagreements.
Your answer: {self_answer}
Critiques of you: {critiques}
```
  - Chairman: “Summarize the debate: consensus, disagreements, key risks. No vote; deliver best combined answer with citations.”

- Stacks:
  - Pair answers: baseline answer prompt.
  - Chairman merge:
```
System: Merge two answers. Preserve optionality; do not drop viable options. Combine concisely; cite.
A: {a1}  B: {a2}
```
  - Critics (other two):
```
System: Critique merged answer. Attack weak spots; missing context; feasibility. Be concise; cite.
Merged: {merged}
```
  - Chairman judge (with original context): “Judge merged answer vs critiques using original context; note what holds and what fails; cite.”
  - Defenses by original two: “Defend merged answer vs critiques; fix valid issues briefly.”
  - Chairman final (no original context now): “Produce final report; present both sides; note judgment rationale; cite from earlier context references.”

- Complex Iterative (Extract/Expand alternating):
  - Extract prompt:
```
System: Extract: Summarize intent + constraints; list key facts from context; propose the next prompt to progress. Cite facts.
Context: {context}  User: {user_prompt}
```
  - Expand prompt:
```
System: Expand: Elaborate on the prior extract; extend with actionable detail; improve the suggested prompt. Keep it concise; cite if needed.
Prev summary: {summary}  Prev suggested prompt: {suggested}
```
  - Repeat extract/expand alternation; Chairman final: “Use latest extract/expand chain to answer; ensure consistency with cited context.”

- Complex Questioning:
  - Initial answer: baseline answer.
  - Question self through others:
```
System: Re-read your answer through peers’ lenses. Identify where you may be wrong, missing context, or overconfident. Update your position; cite.
Your answer: {self}  Peers: {others}
```
  - Chairman summary: “Summarize convergences/divergences; produce a concise brief.”
  - Muse round (no original context): “Consider the brief alone; add reflections or corrections; avoid inventing new facts.”
  - Chairman final: “Produce final answer based on debate and muse round; cite from earlier context.”

- Summarizer (Chairman) for budget:
```
System: Summarize user ask and context into a compact bundle for other agents. Keep key facts, decisions, constraints. List provenance (file:lines).
User: {user_prompt}
Context: {chunks}
```

- Length hints: `@short` → “Answer in <= ~5 sentences unless code is needed.” `@detailed` → “Be thorough; include steps and rationale.”
- Citations: “When using provided context, add inline citations like [file:line] where relevant.”

### Settings Panel (GUI)
- Fields: council models list, Chairman model, temp, max tokens, max output tokens, RAG on/off, top-k, rerank toggle, budget cap, default mode, safety tier, traces on/off, summarize-first default, cite default, tool execution allowed, include-untracked for indexing.
- UX: mark “applies immediately” vs “requires restart” (model/provider changes). Provide reset-to-defaults and per-field inline help.
- Persistence: write to existing config file (or `data/config.json`); validate types/ranges; show errors inline.
- Actions: “Save”, “Save & restart backend”, “Discard”. Restart calls a backend endpoint to restart the server (or asks user to run script if not supported).
- Surface last index time and “changed since last index” indicator; button to reindex (calls backend job).
- Log/debug panel: show recent apply events and validation errors.

#### Settings Field / Restart Matrix (examples)
- Hot (no restart): temp, max tokens, max output tokens, RAG on/off, top-k, rerank toggle, budget cap, default mode, safety tier, traces, summarize-first default, cite default, tool execution allowed, include-untracked flag (for next index), mode selector default.
- Restart likely: provider/API key changes, model list/Chairman model, embedding/rerank models, server bind/port, storage paths. If restart endpoint unavailable, prompt user to restart manually.

### Directive Schema (wire format)
- Accepted inline syntax (case-insensitive, any order):
  - `@norag`, `@raw`
  - `@summarize`
  - `@tokenbudget <int>`
  - `@trace` / `@debug`
  - `@short` / `@detailed`
  - `@cite`
  - `@noexecute`
  - `@reset`
  - Optional: `@temp <float 0-1>`, `@maxtokens <int>`, `@safe`/`@relaxed`
- Parsing: split on whitespace, collect directives with params; strip from user text; store into request metadata; precedence rules from above section.
- Error handling: invalid value → respond with a short validation message and skip the invalid directive; continue with valid ones.

### Model Context Limits (current council)
- Use the minimum context window across participating models for budgeting each hop. Keep a safety margin (80–85% target).
- Known (from local SDK metadata):
  - `openai/gpt-5.1`: ~400k input tokens, ~128k output tokens (OpenAI profile).
- Unknown in this repo (pull from provider/OpenRouter `/models` or docs; set conservative placeholders until fetched):
  - `google/gemini-3-pro-preview`: TBD (fetch and record).
  - `anthropic/claude-sonnet-4.5`: TBD (fetch and record).
  - `x-ai/grok-4`: TBD (fetch and record).
- Implementation: add `MODEL_CONTEXT_LIMITS` map in config; populate with confirmed numbers; runtime picks `min_input` for budget. If a model lacks data, either exclude it from multi-round hops or default to a conservative cap (e.g., 100k) and note in trace.

### Rollout Phases
- Phase 1: Directives (`@norag/@raw`, `@summarize`, budget cap, `@trace`, length hints, `@noexecute`, `@reset`, optional temp/max tokens); Chairman summarizer path; UI badges and trace output.
- Phase 2: Git-head indexing + manifest + “changed since last index” surface; CLI/UI hooks.
- Phase 3: Modes shipped gradually (Round Robin, Fight, Stacks, Complex Iterative, Complex Questioning) behind mode selector and transcript tags; per-mode guardrails.
- Phase 4: Settings panel with hot vs restart fields, save/restart flow, reindex button, and log view.
