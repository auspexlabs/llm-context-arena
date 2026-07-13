import { escapeHtml } from '../escape';
import { formatDuration, renderStepTimersHtml, totalElapsedMs } from '../runtime';
import { agentTurnProgress } from '../turns';
import type { AgentTurnSnapshot, ModeProgress, PendingTurn, TurnRuntime } from '../types';

export function renderProgressViewport(
  container: HTMLElement,
  pending: PendingTurn,
  activeTurn: AgentTurnSnapshot | null,
  modeProgress: ModeProgress,
  turnRuntime: TurnRuntime | null,
  now = Date.now()
) {
  const prog = activeTurn ? agentTurnProgress(activeTurn) : modeProgress;
  const pct =
    prog.total > 0 ? Math.min(100, Math.round((prog.current / prog.total) * 100)) : 0;
  const indeterminate = !activeTurn && prog.current === 0;
  const query = pending.userQuery.slice(0, 600);
  const sourceLabel =
    pending.source === 'external' ? 'External agent (MCP / API)' : 'Local run';
  const total =
    turnRuntime && turnRuntime.turnIndex === pending.turnIndex
      ? formatDuration(totalElapsedMs(turnRuntime, now))
      : null;
  const stepTimers =
    turnRuntime && turnRuntime.turnIndex === pending.turnIndex
      ? renderStepTimersHtml(turnRuntime, now)
      : '';

  container.innerHTML = `
    <div class="progress-panel" data-scroll-anchor="progress">
      <div class="progress-head">
        <span class="running-badge">Turn ${pending.turnIndex + 1} in progress</span>
        <span class="meta">${sourceLabel}${total ? ` · ${total} elapsed` : ''}</span>
      </div>
      ${stepTimers ? `<div class="runtime-steps">${stepTimers}</div>` : ''}
      <p class="progress-query">${escapeHtml(query)}${pending.userQuery.length > 600 ? '…' : ''}</p>
      <div class="progress-track ${indeterminate ? 'indeterminate' : ''}" aria-hidden="true">
        <div class="progress-fill" style="width:${indeterminate ? '40' : pct}%"></div>
      </div>
      <p class="meta progress-stage">
        ${escapeHtml(prog.label || 'Council deliberation')}
        ${prog.total ? ` · step ${prog.current}/${prog.total}` : ''}
      </p>
      <p class="meta progress-hint">Results appear when the arena finishes. This view refreshes automatically.</p>
    </div>
  `;
}