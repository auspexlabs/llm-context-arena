import { escapeHtml } from '../escape';
import { agentTurnProgress } from '../turns';
import type { AgentTurnSnapshot, PendingTurn } from '../types';
import type { ModeProgress } from '../types';

export function renderProgressViewport(
  container: HTMLElement,
  pending: PendingTurn,
  activeTurn: AgentTurnSnapshot | null,
  modeProgress: ModeProgress
) {
  const prog = activeTurn ? agentTurnProgress(activeTurn) : modeProgress;
  const pct =
    prog.total > 0 ? Math.min(100, Math.round((prog.current / prog.total) * 100)) : 0;
  const indeterminate = !activeTurn && prog.current === 0;
  const query = pending.userQuery.slice(0, 600);
  const sourceLabel =
    pending.source === 'external' ? 'External agent (MCP / API)' : 'Local run';

  container.innerHTML = `
    <div class="progress-panel" data-scroll-anchor="progress">
      <div class="progress-head">
        <span class="running-badge">Turn ${pending.turnIndex + 1} in progress</span>
        <span class="meta">${sourceLabel}</span>
      </div>
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