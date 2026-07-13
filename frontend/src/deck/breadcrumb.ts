import { squadHealth, squadHealthLabel } from './squad-health';
import type { TurnContextSnapshot } from './turn-context';

export function buildBreadcrumb(
  ctx: TurnContextSnapshot,
  turnIndex: number,
  status: 'running' | 'complete' | 'idle'
): string {
  const statusCls = status === 'running' ? 'status-run' : status === 'complete' ? 'status-done' : 'status-idle';
  const parts = [
    `<b>${ctx.mode}</b>`,
    `Turn ${turnIndex + 1}`,
    `<span class="bc-status ${statusCls}">${status}</span>`,
  ];

  if (ctx.mode === 'council' && ctx.squadSize > 0) {
    const health = squadHealth(ctx.respondedCount, ctx.squadSize);
    const label = squadHealthLabel(ctx.respondedCount, ctx.squadSize);
    const cls = health === 'bad' ? 'bc-squad bad' : health === 'warn' ? 'bc-squad warn' : 'bc-squad';
    const clickable = health !== 'ok' ? ' bc-link' : '';
    parts.push(`<span class="${cls}${clickable}" data-bc-quality="1">${label}</span>`);
    parts.push(`<span class="bc-ctx bc-link" data-bc-context="1">shared prompt</span>`);
  }

  if (ctx.contextChunkCount > 0) {
    const tok = ctx.contextTokens != null ? ` · ~${ctx.contextTokens.toLocaleString()} ctx tok` : '';
    parts.push(`<span class="bc-ctx bc-link" data-bc-context="1">${ctx.contextChunkCount} RAG chunks${tok}</span>`);
  }

  return parts.join(' · ');
}