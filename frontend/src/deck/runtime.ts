import type { AgentTurnSnapshot, AssistantMessage, TurnRuntime } from './types';

export type RuntimeStepId = 'stage1' | 'stage2' | 'stage3';

const STEP_ORDER: RuntimeStepId[] = ['stage1', 'stage2', 'stage3'];

const STEP_LABELS: Record<RuntimeStepId, string> = {
  stage1: '1 Answers',
  stage2: '2 Rankings',
  stage3: '3 Verdict',
};

export function createTurnRuntime(turnIndex: number, now = Date.now()): TurnRuntime {
  return {
    turnIndex,
    startedAt: now,
    currentStep: 'stage1',
    steps: {
      stage1: { startedAt: now, endedAt: null },
      stage2: { startedAt: null, endedAt: null },
      stage3: { startedAt: null, endedAt: null },
    },
  };
}

export function formatDuration(ms: number): string {
  if (ms < 0 || !Number.isFinite(ms)) return '—';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem ? `${m}m ${rem}s` : `${m}m`;
}

export function stepStatus(runtime: TurnRuntime, step: RuntimeStepId): 'pending' | 'live' | 'done' {
  const rec = runtime.steps[step];
  if (rec.endedAt != null) return 'done';
  if (runtime.currentStep === step) return 'live';
  if (rec.startedAt != null) return 'live';
  return 'pending';
}

export function stepElapsedMs(
  runtime: TurnRuntime,
  step: RuntimeStepId,
  now = Date.now()
): number | null {
  const rec = runtime.steps[step];
  const status = stepStatus(runtime, step);
  if (status === 'pending') return null;
  if (status === 'done' && rec.startedAt != null && rec.endedAt != null) {
    return rec.endedAt - rec.startedAt;
  }
  if (rec.startedAt != null) return now - rec.startedAt;
  return null;
}

export function totalElapsedMs(runtime: TurnRuntime, now = Date.now()): number {
  return now - runtime.startedAt;
}

function beginStep(runtime: TurnRuntime, step: RuntimeStepId, now: number): TurnRuntime {
  const next = structuredClone(runtime);
  next.currentStep = step;
  if (next.steps[step].startedAt == null) {
    next.steps[step].startedAt = now;
  }
  return next;
}

function completeStep(runtime: TurnRuntime, step: RuntimeStepId, now: number): TurnRuntime {
  const next = structuredClone(runtime);
  if (next.steps[step].startedAt == null) {
    next.steps[step].startedAt = runtime.startedAt;
  }
  next.steps[step].endedAt = now;
  return next;
}

export function runtimeOnStageStart(
  runtime: TurnRuntime | null,
  turnIndex: number,
  step: RuntimeStepId,
  now = Date.now()
): TurnRuntime {
  let r = runtime?.turnIndex === turnIndex ? runtime : createTurnRuntime(turnIndex, now);
  const idx = STEP_ORDER.indexOf(step);
  for (let i = 0; i < idx; i++) {
    const prev = STEP_ORDER[i];
    if (r.steps[prev].endedAt == null) {
      r = completeStep(r, prev, now);
    }
  }
  return beginStep(r, step, now);
}

export function runtimeOnStageComplete(
  runtime: TurnRuntime | null,
  turnIndex: number,
  step: RuntimeStepId,
  now = Date.now()
): TurnRuntime {
  let r = runtime?.turnIndex === turnIndex ? runtime : createTurnRuntime(turnIndex, now);
  r = runtimeOnStageStart(r, turnIndex, step, r.steps[step].startedAt ?? now);
  return completeStep(r, step, now);
}

export function runtimeFromAgentTurn(
  runtime: TurnRuntime | null,
  turnIndex: number,
  turn: AgentTurnSnapshot | null,
  now = Date.now()
): TurnRuntime | null {
  if (!turn) return runtime;
  let r = runtime?.turnIndex === turnIndex ? runtime : createTurnRuntime(turnIndex, now);
  if (turn.status === 'pending') {
    return runtimeOnStageStart(r, turnIndex, 'stage1', now);
  }
  if (turn.status === 'stage1_complete') {
    r = runtimeOnStageComplete(r, turnIndex, 'stage1', now);
    return beginStep(r, 'stage2', now);
  }
  if (turn.status === 'stage2_complete') {
    r = runtimeOnStageComplete(r, turnIndex, 'stage1', r.steps.stage1.endedAt ?? now);
    r = runtimeOnStageComplete(r, turnIndex, 'stage2', now);
    return beginStep(r, 'stage3', now);
  }
  return r;
}

export function runtimeFromAssistant(
  runtime: TurnRuntime | null,
  turnIndex: number,
  msg: AssistantMessage | null,
  isRunning: boolean,
  now = Date.now()
): TurnRuntime | null {
  if (!msg || !isRunning) return runtime;
  let r = runtime?.turnIndex === turnIndex ? runtime : createTurnRuntime(turnIndex, now);
  if (msg.loading?.stage1) {
    return runtimeOnStageStart(r, turnIndex, 'stage1', now);
  }
  if (msg.stage1?.length) {
    r = runtimeOnStageComplete(r, turnIndex, 'stage1', now);
  }
  if (msg.loading?.stage2) {
    return beginStep(r, 'stage2', now);
  }
  if (msg.stage2?.length) {
    r = runtimeOnStageComplete(r, turnIndex, 'stage2', now);
  }
  if (msg.loading?.stage3) {
    return beginStep(r, 'stage3', now);
  }
  if (msg.stage3?.response) {
    r = runtimeOnStageComplete(r, turnIndex, 'stage3', now);
  }
  return r;
}

export function renderStepTimersHtml(runtime: TurnRuntime, now = Date.now()): string {
  return STEP_ORDER.map((step) => {
    const status = stepStatus(runtime, step);
    const elapsed = stepElapsedMs(runtime, step, now);
    const timer =
      elapsed != null ? formatDuration(elapsed) : status === 'pending' ? '—' : '…';
    const cls = `runtime-step ${status}`;
    return `<div class="${cls}"><span class="runtime-step-label">${STEP_LABELS[step]}</span><span class="runtime-step-time">${timer}</span></div>`;
  }).join('');
}

export function timelineStepTimer(
  runtime: TurnRuntime | null,
  deckStep: 'answers' | 'rankings' | 'verdict',
  now = Date.now()
): string {
  if (!runtime) return '';
  const map: Record<string, RuntimeStepId> = {
    answers: 'stage1',
    rankings: 'stage2',
    verdict: 'stage3',
  };
  const step = map[deckStep];
  const elapsed = stepElapsedMs(runtime, step, now);
  if (elapsed == null) return '';
  return ` <span class="step-timer">${formatDuration(elapsed)}</span>`;
}