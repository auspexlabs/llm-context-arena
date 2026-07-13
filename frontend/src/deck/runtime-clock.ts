import { getState, patch } from './store';

const TICK_MS = 1000;
let timer: ReturnType<typeof setInterval> | null = null;

function shouldTick(): boolean {
  const s = getState();
  if (s.isRunning) return true;
  if (s.pendingTurn && !s.isRunning) return true;
  return false;
}

function tick() {
  if (!shouldTick()) {
    stopRuntimeClock();
    return;
  }
  patch({ runtimeTick: Date.now() }, 'full');
}

export function startRuntimeClock() {
  if (timer) return;
  tick();
  timer = setInterval(tick, TICK_MS);
}

export function stopRuntimeClock() {
  if (timer) clearInterval(timer);
  timer = null;
}

export function syncRuntimeClock() {
  if (shouldTick()) startRuntimeClock();
  else stopRuntimeClock();
}