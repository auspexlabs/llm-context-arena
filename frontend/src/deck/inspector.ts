import { escapeHtml } from './escape';
import { failuresByKind, type ModelFailure } from './failures';
import { squadHealth } from './squad-health';
import { buildTurnContext } from './turn-context';
import { getState, openInspectorColumn, setContextPromptModel } from './store';
import type { AssistantMessage } from './types';

function headCell(id: 'context' | 'rankings' | 'quality', label: string, active: boolean) {
  return `<button type="button" class="insp-head${active ? ' on' : ''}" data-insp-col="${id}">${label}</button>`;
}

export function renderInspector(
  root: HTMLElement,
  msg: AssistantMessage | undefined,
  turnIndex: number,
  _mode: string
) {
  const s = getState();
  const meta = msg?.metadata || {};
  const ctx = buildTurnContext(s.conversation, msg ?? null, turnIndex);
  const eq = meta.execution_quality as Record<string, unknown> | undefined;
  const agg = meta.aggregate_rankings as Record<string, unknown>[] | undefined;
  const failures = (meta.model_failures as ModelFailure[]) || [];
  const health = squadHealth(ctx.respondedCount, ctx.squadSize);

  const ctxBody = `
    ${ctx.userQuery ? `<p class="insp-lead">${escapeHtml(ctx.userQuery.slice(0, 72))}${ctx.userQuery.length > 72 ? '…' : ''}</p>` : '<p class="meta">—</p>'}
    ${ctx.contextChunkCount ? `<p class="insp-kicker">${ctx.contextChunkCount} RAG chunks</p>` : '<p class="meta">No RAG</p>'}
    <div class="insp-model-btns">
      ${ctx.modelPrompts.length > 1
        ? `<button type="button" class="insp-mini" data-ctx-model="-1">Shared prompt</button>`
        : ''}
      ${ctx.modelPrompts
        .map((m, i) => {
          const short = m.model.split('/').pop() || m.model;
          return `<button type="button" class="insp-mini" data-ctx-model="${i}">${escapeHtml(short)}</button>`;
        })
        .join('')}
    </div>`;

  const rankBody = agg?.length
    ? agg
        .slice(0, 5)
        .map((a, i) => {
          const rank = a.avg_rank ?? a.average_rank;
          return `<p><b>#${i + 1}</b> ${escapeHtml(String(a.model || '').split('/').pop() || '')}${rank != null ? ` · ${rank}` : ''}</p>`;
        })
        .join('')
    : '<p class="meta">—</p>';

  const failKinds = failuresByKind(failures);
  const kindSummary = Object.entries(failKinds)
    .map(([k, n]) => `${k.replace(/_/g, ' ')}: ${n}`)
    .join('<br>');

  const qBody = eq
    ? `<p><b>${escapeHtml(String(eq.severity || 'ok'))}</b></p>
       <p>${eq.acceptable ? 'acceptable' : 'review'}</p>
       ${failures.length ? `<p class="insp-kicker ${health === 'bad' ? 'tone-bad' : health === 'warn' ? 'tone-warn' : ''}">${failures.length} failure(s)</p>` : ''}
       ${kindSummary ? `<p class="meta">${kindSummary}</p>` : ''}`
    : failures.length
      ? `<p class="insp-kicker tone-bad">${failures.length} failure(s)</p>${kindSummary ? `<p class="meta">${kindSummary}</p>` : ''}`
      : ctx.squadSize > 0 && ctx.respondedCount < ctx.squadSize
        ? `<p class="insp-kicker tone-warn">Quality metadata missing</p><p class="meta">${ctx.respondedCount} / ${ctx.squadSize} responded</p>`
      : '<p class="meta">—</p>';

  const col = s.inspectorColumn;

  root.innerHTML = `
    <div class="insp-grid">
      <div class="insp-heads">
        ${headCell('context', 'Context', col === 'context')}
        ${headCell('rankings', 'Rankings', col === 'rankings')}
        ${headCell('quality', 'Quality', col === 'quality')}
      </div>
      <div class="insp-bodies">
        <div class="insp-body${col === 'context' ? ' on' : ''}" data-insp-body="context">${ctxBody}</div>
        <div class="insp-body${col === 'rankings' ? ' on' : ''}" data-insp-body="rankings">${rankBody}<p class="insp-hint">Peer review →</p></div>
        <div class="insp-body${col === 'quality' ? ' on' : ''}" data-insp-body="quality">${qBody}<p class="insp-hint">Full report →</p></div>
      </div>
    </div>
  `;

  root.querySelectorAll('[data-insp-col]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      openInspectorColumn((btn as HTMLElement).dataset.inspCol as 'context' | 'rankings' | 'quality');
    });
  });

  root.querySelectorAll('[data-insp-body]').forEach((el) => {
    el.addEventListener('click', () => {
      openInspectorColumn((el as HTMLElement).dataset.inspBody as 'context' | 'rankings' | 'quality');
    });
  });

  root.querySelectorAll('[data-ctx-model]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      setContextPromptModel(Number((btn as HTMLElement).dataset.ctxModel));
    });
  });
}
