# PIV-002: Observatory UI — observation deck (greenfield)

**Status:** accepted (locked) · **date:** 2026-07-13 · **mock locked:** 2026-07-13  
**Parent:** [`piv-001-agent-control-plane.md`](piv-001-agent-control-plane.md) Phase 2  
**Checklist companion:** append items to [`piv-001-checklist.md`](piv-001-checklist.md) when implementation starts  
**Canonical mock:** [`mockups/observatory-deck.html`](mockups/observatory-deck.html) — visual + IA reference for PIV-002a implementation

---

## Decision log (locked for v1)

| Topic | Decision |
|-------|----------|
| **Approach** | Greenfield cutover — delete chat-first shell, not parallel `?legacy=1` |
| **Primary object** | **Turn** (execution), not message thread |
| **Layout** | Three-zone **observation deck**: Rail · Deck · Inspector |
| **Human input** | Default **watch**; **Take control** always visible (muted until engaged) |
| **Inspector** | **All three** visible by default: Context trace · Rankings · Quality |
| **Mobile** | Out of scope v1; stack must not foreclose responsive layout later |
| **Backend** | Keep **Python / FastAPI** orchestration (existing) |
| **Realtime** | **SSE** first (already in stack); WebSocket optional later for bidirectional agent control |
| **Visual reference** | Locked to `mockups/observatory-deck.html` — do not shrink typography or inspector width in implementation |

---

## Locked visual spec (from mock)

| Token | Value |
|-------|--------|
| Base font | **16px** / 1.45 |
| Rail width | **280px** |
| Inspector width | **420px** |
| Deck header | **17px** bold mode label; **15px** meta |
| Rail session/turn titles | **15px** semibold |
| Rail turn meta | **14px** (status, duration) |
| Inspector columns | **14px** body, **15px** labels, **13px** column headers |
| Step timeline pills | **15px** |
| Verdict lane | **15px** body; uppercase label |

**Palette (v1):** `--bg #0e1114` · `--surface #161b22` · `--accent #3dd6c6` (running) · `--ok #6bcf8e` (complete) · `--warn #f0b429` (verdict label)

### Complete turn presentation (locked)

**Rail item:**
```
Turn N
✓ complete · {duration}
${cost} · {tokens} tok · {model_count} models
```

**Deck:** all timeline steps show ✓; viewport shows “Review complete” + chairman excerpt; user clicks steps to inspect historical stages.

**Verdict lane:** always populated when `status: complete` — not empty placeholder.

**Inspector:** full context / rankings / quality (all three columns), not collapsed.

**Footer:** `Turn complete · watching idle` when nothing running; `Watching · SSE connected` when live.

Running vs complete is **real turn state** in production; mock toggle is dev-only preview.

---

## Problem statement

Current UI is a **chat room** (`ChatInterface.jsx` ~1100 lines, send-centric `App.jsx`). PIV-001 target is an **observation deck**: subscribe to deliberation, read disagreement as signal, intervene only at checkpoints or explicit override.

Incremental restyle fails because information architecture is wrong — stages are collapsible afterthoughts behind a textarea.

---

## Layout — observation deck

```
┌──────────┬────────────────────────────────────┬─────────────────┐
│  RAIL    │  DECK                              │  INSPECTOR      │
│  240px   │  flex                              │  320px          │
│          │                                    │                 │
│ Sessions │  Turn header (mode, status, agent) │ ┌─────┬─────┬──┐
│ Turns    │  Step timeline ─────────────────── │ │ Ctx │ Rnk │Q │
│          │  Primary viewport (one step)       │ └─────┴─────┴──┘
│          │  [await_user banner when paused]   │ (three columns
│          │  Verdict lane (chairman synthesis) │  or stacked
│          │  Take control ───────── (footer)   │  mini-panels)
└──────────┴────────────────────────────────────┴─────────────────┘
```

### Rail (~280px)

- Session list (conversations)
- Turns within session — status chip: `running` · `await_user` · `complete` · `failed`
- New session / mode picker (compact)
- **No** settings/catalog here → `/settings` or inspector gear

### Deck (center)

- **Turn header:** mode, `step_index/total`, agent id, cost/tokens, progress
- **Step timeline:** horizontal rail; click to focus; live pulse on active step
- **Viewport:** one step at a time — council answers, eval text, fight round, etc.
- **Await banner:** structured question + resume box (distinct styling from Take control)
- **Verdict lane:** chairman synthesis pinned — not buried in scrollback

### Inspector (~420px) — all three, always

| Column | Content |
|--------|---------|
| **Context** | RAG chunks, router class, directives, budget decision, index stale |
| **Rankings** | Aggregate order, parsed vs raw eval, label→model map |
| **Quality** | `execution_quality`, failure kinds, recommendations, observation flags |

On narrow widths (future): inspector collapses to tabs; v1 desktop-only.

---

## Human control model

### 1. `await_user` (protocol checkpoint)

Backend pauses turn with structured `await_prompt`. UI shows banner; resume posts to `POST .../turns/{id}/resume`. **Next step is known** — no branch picker.

### 2. Take control (override)

Always visible, muted until toggled. Engaging it:

- Enables send / context picker / cancel (today’s powers, scoped)
- Visual mode shift (accent border, “YOU ARE DRIVING” strip)
- Does **not** silently hijack agent turns — explicit toggle

### 3. Workflow branches (future-deep, design now)

When human takes control **outside** `await_user`, next step may be **ambiguous**. Proposed model:

```yaml
WorkflowOffer:
  turn_id: ...
  offered_by: chairman | supervisor
  options:
    - id: retry_stage2
      label: Re-run peer review with narrower context
      action: advance(step=stage2, context_delta=...)
    - id: switch_mode_fight
      label: Escalate to Fight mode
      action: fork_turn(mode=fight, carry_hypothesis=...)
    - id: human_answer
      label: Provide missing fact and resume
      action: resume(reply=...)
```

**Chairman adjudicates** among `WorkflowOffer.options` — UI renders as card list; human picks one. Backend needs `WorkflowOffer` on turn record (Phase 2b). v1 can stub UI with chairman-only “suggested next steps” from `execution_quality.recommendations`.

---

## Stack choices

Goals: **static client**, **highly visual**, **performant**, **3D-ready later**, Python orchestration, not clunky.

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Orchestration** | Python 3 + FastAPI (keep) | Arena, RAG, MCP already here |
| **Math / hot paths** | Rust **later** via WASM modules | Embeddings, graph ops, token math — not blocking UI v1 |
| **Client** | **Vite + vanilla TS** (or **Preact** if components hurt) | Static bundle, no SSR tax, small runtime; avoids “React bro” SPA weight |
| **Styling** | CSS modules or single `deck.css` + CSS variables | No Tailwind ceremony; full visual control |
| **Realtime** | **SSE** (`/events`, existing stream patterns) | One-way watch fits observatory; local HTTP fine |
| **3D future** | **Three.js / WebGPU** as optional canvas layer | Framework-agnostic; mount in deck viewport for graph/trace viz |
| **State** | Thin store (~100 lines) or nanostores | Turn-centric; avoid Redux |

**Rejected for v1:** Next.js, heavy component libraries, Electron wrapper, rewriting backend in Rust.

**Mobile later:** CSS grid regions collapse rail→drawer, inspector→bottom sheet; no native-only APIs in v1.

---

## Data flow (target)

```
Agent or human (Take control) → POST /turns
UI → GET /conversations/{id}/events (SSE) or poll /turns/{id}
Deck renders TurnState.steps[focused]
Inspector binds TurnState.metadata (quality, context, rankings)
await_user → banner → POST /resume
```

Decouple all SSE from “send message” — `App.jsx` pattern is retired.

---

## Component map (new frontend)

```
src/
  deck/
    App.ts              # mount, theme, routing (/ , /settings)
    rail/SessionRail.ts
    deck/TurnDeck.ts
    deck/StepTimeline.ts
    deck/StepViewport.ts   # delegates to mode viewers
    deck/AwaitBanner.ts
    deck/VerdictLane.ts
    deck/TakeControl.ts
    inspector/Inspector.ts # 3-column
    viewers/               # port logic from Stage1/2/3, RoundTrack
  api.ts
  store/turnStore.ts
```

Delete after cutover: `ChatInterface.jsx`, chat-centric `App.jsx` paths.

---

## Phasing

### PIV-002a — Shell + cutover (no new backend)

- Deck layout + fake/static turn data
- Port Stage1/2/3 viewers into viewport
- Wire existing sync message flow temporarily (bridge) OR poll completed turns only

### PIV-002b — Watch-first backend

- `GET /events` SSE
- Read-only default; Take control toggle
- `await_user` + `resume`

### PIV-002c — Workflow offers

- `WorkflowOffer` on turn
- Chairman next-step cards when Take control engaged outside await

---

## Success criteria

- Open deck → see active turn timeline without scrolling a chat thread
- Inspector shows context + rankings + quality without expand/collapse
- Agent-driven turn visible in real time with Send disabled until Take control
- `await_user` pause/resume works without chat metaphor
- Stack bundle stays lean; 60fps step transitions on typical squad size

---

## Open questions

1. Settings/catalog: dedicated `/settings` route vs modal?
2. WorkflowOffer schema — chairman generates at end of stage vs dedicated micro-call?
3. Preact vs vanilla TS — decide at PIV-002a kickoff based on viewer port cost