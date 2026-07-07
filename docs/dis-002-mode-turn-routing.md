# DIS-002: Advanced mode turn routing is structurally broken

**Status:** remediated by DEC-014 · **date:** 2026-07-07  
**Ledger stub:** `docs/decision_log.md` → `DIS-002`, `DEC-014`  
**Blocks:** ~~`PIV-001` agent control plane~~ unblocked for Phase 1  
**Fix checklist:** [`piv-001-checklist.md`](piv-001-checklist.md) (all DIS-002 items checked)

---

## Summary

Backend **mode runners implement multi-turn protocols correctly** in `arena.py` (`run_mode_fight`, `run_mode_stacks`, etc.) and return rich `metadata.steps`. The **API + UI still assume Council shape** (`stage1` = parallel answers → optional `stage2` rankings → `stage3` chair). Advanced modes **stuff the entire playthrough into `stage1`**, stream **one blob after the full run**, and render it through **Council-only components**. RoundTrack grouping exists but is **starved of live steps** and **decoupled from Stage1 tabs** during execution.

This is not polish — it is a **contract mismatch** between orchestration and presentation.

---

## Root cause

`run_full_arena()` always returns `(stage1_results, stage2_results, stage3_result, metadata)` but non-council runners use:

```python
return steps, [], stage3_result, {"mode": "...", "steps": steps + [chair]}
```

`main.py` maps that tuple to Council SSE events unchanged:

1. `stage1_start` at message begin
2. `mode_progress` during run (partial)
3. **`stage1_complete` only after entire runner finishes** — user stares at “Stage 1” through critiques, merges, muse, chair
4. `stage2_*` skipped (empty)
5. `stage3_complete` for chairman

The UI binds `msg.stage1` → `<Stage1 title="Individual Responses" />` for **every mode**.

---

## Deficiency matrix

| Mode | Backend turns | Returned as | Live timeline | Stage1 UI | Stage2 UI |
|------|---------------|-------------|---------------|-----------|-----------|
| **council** | answers → rankings → chair | Correct split | Partial (answers emit `step`) | OK | OK |
| **fight** | answer×N → critique×N → defense×N → chair | **All steps → stage1** | **Empty** (`emit_steps=False`, no `step` on critique/defense) | Wrong (12+ “answer” tabs) | Never |
| **stacks** | pair → merge → critique → judge → defense → chair | **All → stage1** | **Empty** | Wrong | Never |
| **round_robin** | draft×N×passes → chair | **drafts → stage1** | **Empty** (no `step` in progress) | Wrong labels | Never |
| **complex_iterative** | extract/expand×2 → chair | **All → stage1** | **Empty** | Wrong | Never |
| **complex_questioning** | answer → self-Q → brief → muse → chair | **All → stage1** | Partial (some steps emit) | Wrong | Never |

---

## Specific bugs

### 1. Stage1 gate on entire mode duration (streaming)

`send_message_stream` (`main.py`) awaits `runner_task` **before** `stage1_complete`. For Fight, “Stage 1 loading” covers the **whole debate**, not answers only.

### 2. `stage1` overload

Fight/Stacks return `steps` (answers + critiques + defenses + …) as `stage1_results`. `Stage1.jsx` renders them as peer “individual responses” with model-only tabs — duplicate model names, wrong semantics.

### 3. Live step starvation

`App.jsx` only appends to `liveSteps` when `event.data.step` is set. Fight/Stacks disable `emit_steps` in `stage1_collect_responses`; most `mode_progress` payloads omit `step`. Timeline during run is blank for those modes.

### 4. Progress counter inconsistency

- Council / stage1_collect: `completed` (and parallel gather **does not increment** `completed` per model — all tasks report `progress_offset+1` on finish)
- Round Robin / Fight mid-pipeline: `current`
- Frontend merges via `completed ?? current` but bar label math uses `currentModeProgress.current` which may stay 0

### 5. RoundTrack ↔ Stage1 index desync

`RoundTrack` `onSelectStep` uses `step.raw.__idx` but `__idx` is only injected in post-hoc timeline render, not in persisted `metadata.steps`. Clicking a round card often fails to focus the right tab.

### 6. Mode-specific UI is partial

- Fight has a truncated `fight-transcript` (160 chars) **in addition to** broken Stage1
- Stacks / Round Robin / Complex modes: **no** dedicated transcript — only RoundTrack after complete
- `baseline` mode in UI/RoundTrack maps to council grouping but is **not** in `MODE_RUNNERS` (falls through to `run_mode_council` — OK) while old conversations may show `baseline` label inconsistently

### 7. Council `metadata.steps` rankings stub

Council packs a empty `rankings` step into `metadata.steps`; real ranking text lives only in `stage2`. RoundTrack “Round 2 – Rankings” is empty while Stage2 has the data.

### 8. Agent/control-plane implication

No stable **turn boundary** in API responses. An agent cannot call “advance to critique round” — everything is one opaque `stage1` array after completion. PIV-001 step API **depends on fixing this contract first**.

---

## Target contract (fix direction)

Replace Council-shaped envelope with mode-aware execution model:

```json
{
  "execution": {
    "mode": "fight",
    "status": "running",
    "step_index": 4,
    "step_total": 13,
    "current_step": { "role": "critique", "model": "...", "response": "..." },
    "steps": [ ... append-only ... ]
  },
  "stage3": { ... chair when complete ... },
  "stage2": { ... only council: rankings ... }
}
```

SSE should emit **`step_complete`** per turn (not hold `stage1_complete` until the end). UI should:

- **Hide** generic Stage1/Stage2 for non-council modes
- **Drive** RoundTrack + role-grouped panels from `execution.steps`
- **Council** keeps Stage1 + Stage2 + Stage3 as today

---

## Recommended fix order

1. **Streaming:** emit per-step events; defer `stage1_complete` to council-only (or rename events to `step_complete`)
2. **Return shape:** runners return `execution_steps` separate from council `stage1`/`stage2`
3. **Progress:** unify `step_index` / `step_total`; fix parallel stage1 counter; always attach `step` payload
4. **UI:** mode router in `ChatInterface` — council stages vs RoundTrack-first for advanced modes
5. **RoundTrack:** stable step IDs; fix `__idx` for focus sync
6. **Then** PIV-001 turn/advance API on the corrected contract