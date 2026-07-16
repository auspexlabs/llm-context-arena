import { escapeHtml } from '../escape';
import { executionTrace } from '../execution-trace';
import {
  classifyFailureKind,
  failureKey,
  failureKindExplain,
  failureVerbatim,
  failuresByKind,
  privacyFailureShare,
  rerunSuggestions,
  type ModelFailure,
} from '../failures';
import { getState, patch, toggleFailureExpand } from '../store';
import { preventFocusScroll, setScrollAnchor } from '../scroll-anchor';
import type { AssistantMessage } from '../types';

function bindRerunButtons(container: HTMLElement, userQuery: string) {
  container.querySelectorAll('[data-rerun]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const prefix = (btn as HTMLElement).dataset.rerun || '';
      const ta = document.getElementById('query') as HTMLTextAreaElement | null;
      if (!ta) return;
      ta.value = prefix + userQuery;
      patch({ takeControl: true });
      ta.focus();
    });
  });
}

export function renderQualityViewport(
  container: HTMLElement,
  msg: AssistantMessage | null,
  userQuery = ''
) {
  if (!msg) {
    container.innerHTML = '<p class="empty-state">No quality data for this turn.</p>';
    return;
  }

  const s = getState();
  const meta = msg.metadata || {};
  const eq = meta.execution_quality as Record<string, unknown> | undefined;
  const failures = (meta.model_failures as ModelFailure[]) || [];
  const obs = (meta.observation_pending as Record<string, unknown>[]) || [];
  const arena = (meta.arena_models as string[]) || [];
  const mode = String(meta.mode || 'council');
  const trace = executionTrace(msg, mode);
  const responded = trace?.summary.participant_succeeded ?? (msg.stage1 || []).length;
  const privacyShare = privacyFailureShare(failures);
  const kinds = failuresByKind(failures);
  const suggestions = rerunSuggestions(failures);
  const inferredPartial = !eq && arena.length > 0 && responded < arena.length;

  const eqHtml = eq
    ? `<p><strong>Severity:</strong> ${escapeHtml(String(eq.severity || 'ok'))}</p>
       <p><strong>Acceptable:</strong> ${eq.acceptable ? 'yes' : 'review needed'}</p>
       ${eq.summary ? `<p>${escapeHtml(String(eq.summary))}</p>` : ''}`
    : failures.length
      ? '<p class="review-hint">Execution quality not stored — inferring from model failures.</p>'
      : inferredPartial
        ? '<div class="quality-banner tone-warn"><strong>Execution quality metadata is missing.</strong> This turn is inferred degraded because fewer models responded than the recorded squad size.</div>'
      : '<p class="review-hint">No execution_quality recorded.</p>';

  const squadHtml =
    arena.length > 0
      ? `<p><strong>Squad:</strong> ${responded} / ${arena.length} produced usable output</p>`
      : '';

  const traceHtml = trace
    ? `<div class="quality-trace-stats">
        <span><b>${trace.summary.succeeded_steps}</b> succeeded</span>
        <span><b>${trace.summary.failed_steps}</b> failed</span>
        ${mode === 'round_robin' ? `<span><b>${trace.summary.successful_refinements}</b> completed refinement calls</span><span><b>${trace.summary.handoff_deliveries}</b> deliveries</span>` : ''}
      </div>`
    : '';

  const privacyBanner =
    privacyShare >= 0.5 && failures.length > 0
      ? `<div class="quality-banner tone-bad">
          <strong>Data-policy blocks (${Math.round(privacyShare * 100)}% of failures):</strong>
          Often the <strong>“may train on your data”</strong> toggles (free and paid are separate) — not content length. Fix at
          <a href="https://openrouter.ai/settings/privacy" target="_blank" rel="noopener">OpenRouter privacy settings</a>,
          or switch to paid / non-<code>:free</code> models that fit your policy.
        </div>`
      : kinds.context_exceeded
        ? `<div class="quality-banner tone-warn">
            <strong>Context exceeded:</strong> at least one model hit its context window.
            Reduce retrieved chunks, raise the budget, or use a larger-window model. Retrieved code must not be LLM-summarized.
          </div>`
        : '';

  const kindHtml = Object.keys(kinds).length
    ? `<ul class="kind-explainer">${Object.entries(kinds)
        .map(
          ([k, n]) =>
            `<li><strong>${escapeHtml(k.replace(/_/g, ' '))}</strong> (${n}) — ${escapeHtml(failureKindExplain(k))}</li>`
        )
        .join('')}</ul>`
    : '';

  const rerunHtml = suggestions.length
    ? `<div class="rerun-suggestions">
        <h4 class="ctx-heading">Suggested recovery</h4>
        ${suggestions
          .map(
            (sg) =>
              `<button type="button" class="rerun-btn" data-rerun="${escapeHtml(sg.directive)}">${escapeHtml(sg.label)}</button>
               <p class="meta">${escapeHtml(sg.reason)}</p>`
          )
          .join('')}
      </div>`
    : '';

  const failHtml = failures.length
    ? failures
        .map((f, i) => {
          const key = failureKey(f, i);
          const open = s.failuresExpanded.includes(key);
          const kind = classifyFailureKind(f).replace(/_/g, ' ');
          const short = String(f.message || kind).slice(0, 80);
          const verbatim = failureVerbatim(f);
          return `
            <button type="button" class="fail-row ${open ? 'open' : ''}" data-fail-idx="${i}" data-scroll-anchor="${key.replace(/"/g, '')}">
              <span class="fail-head">${open ? '▾' : '▸'} <strong>${escapeHtml(String(f.model || '?').split('/').pop() || '')}</strong> · ${escapeHtml(kind)}</span>
              <span class="fail-preview">${escapeHtml(short)}${(f.message || '').length > 80 ? '…' : ''}</span>
            </button>
            ${open ? `<pre class="ctx-pre fail-verbatim">${escapeHtml(verbatim)}</pre>` : ''}`;
        })
        .join('')
    : '<p class="meta">No model failures logged.</p>';

  const obsHtml = obs.length
    ? `<ul class="quality-list">${obs
        .map((o) => `<li>${escapeHtml(String(o.model_id || o.model || '?'))} — ${escapeHtml(String(o.reason || o.kind || 'pending'))}</li>`)
        .join('')}</ul>`
    : '<p class="meta">No pending observations.</p>';

  container.innerHTML = `
    <h3>Execution quality</h3>
    ${privacyBanner}
    <section class="ctx-panel ctx-panel-quality">${eqHtml}${squadHtml}${traceHtml}${kindHtml}${rerunHtml}</section>
    <section class="ctx-panel ctx-panel-quality">
      <h3 class="ctx-heading">Model failures</h3>
      <p class="ctx-sub">Expand for verbatim provider response</p>
      ${failHtml}
    </section>
    <section class="ctx-panel ctx-panel-quality">
      <h3 class="ctx-heading">Observations</h3>
      ${obsHtml}
    </section>
  `;

  container.querySelectorAll('[data-fail-idx]').forEach((btn) => {
    preventFocusScroll(btn);
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const i = Number((btn as HTMLElement).dataset.failIdx);
      const key = failureKey(failures[i], i);
      setScrollAnchor(key);
      toggleFailureExpand(key);
    });
  });

  bindRerunButtons(container, userQuery);
}
