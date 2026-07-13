import { escapeHtml } from '../escape';
import { deAnonymizeText, renderMarkdown } from '../markdown';
import { preventFocusScroll } from '../scroll-anchor';
import type { AssistantMessage, CouncilStepId } from '../types';

let activeModelTab = 0;

function withViewportScroll(container: HTMLElement, render: () => void) {
  const top = container.scrollTop;
  render();
  container.scrollTop = top;
}

function bindModelTabs(container: HTMLElement, onSelect: (index: number) => void) {
  container.querySelectorAll('.model-tab').forEach((btn) => {
    preventFocusScroll(btn);
    btn.addEventListener('click', () => onSelect(Number((btn as HTMLElement).dataset.tab)));
  });
}

export function resetModelTab() {
  activeModelTab = 0;
}

export function renderCouncilViewport(
  container: HTMLElement,
  msg: AssistantMessage | null,
  step: CouncilStepId,
  isRunning: boolean
) {
  if (!msg) {
    container.innerHTML = '<p class="empty-state">Select a turn to inspect deliberation.</p>';
    return;
  }

  if (step === 'answers') {
    renderAnswers(container, msg, isRunning);
  } else if (step === 'rankings') {
    renderRankings(container, msg, isRunning);
  } else {
    renderVerdictViewport(container, msg, isRunning);
  }
}

type PipelineStep = { role?: string; label?: string; model?: string; response?: string };

function pipelineSteps(msg: AssistantMessage): PipelineStep[] {
  const steps = msg.metadata?.steps;
  return Array.isArray(steps) ? (steps as PipelineStep[]) : [];
}

function renderPipelineSteps(container: HTMLElement, msg: AssistantMessage, title: string) {
  const steps = pipelineSteps(msg);
  if (!steps.length) return false;
  activeModelTab = Math.min(activeModelTab, steps.length - 1);
  const tabs = steps
    .map((s, i) => {
      const label = s.label || s.role || `Step ${i + 1}`;
      const short = label.replace(/^draft_/i, '').replace(/_/g, ' ');
      return `<button type="button" class="model-tab ${i === activeModelTab ? 'on' : ''}" data-tab="${i}">${short}</button>`;
    })
    .join('');
  const cur = steps[activeModelTab];
  const modelLine = cur.model
    ? `<p class="review-hint"><strong>${cur.model.split('/').pop() || cur.model}</strong> · ${cur.role || cur.label || ''}</p>`
    : '';
  withViewportScroll(container, () => {
    container.innerHTML = `
      <h3>${title}</h3>
      <p class="review-hint">Mode pipeline (${steps.length} steps) — stored outside council stage1/2.</p>
      <div class="model-tabs">${tabs}</div>
      ${modelLine}
      <div class="markdown-content">${renderMarkdown(cur.response || '')}</div>
    `;
  });
  bindModelTabs(container, (index) => {
    activeModelTab = index;
    renderPipelineSteps(container, msg, title);
  });
  return true;
}

function renderAnswers(container: HTMLElement, msg: AssistantMessage, isRunning: boolean) {
  const responses = msg.stage1 || [];
  if (!responses.length && isRunning && msg.loading?.stage1) {
    container.innerHTML = '<h3>Stage 1 — Individual answers</h3><p class="review-hint">Collecting responses…</p>';
    return;
  }
  if (!responses.length) {
    if (renderPipelineSteps(container, msg, 'Pipeline — early steps')) return;
    container.innerHTML = '<h3>Stage 1 — Individual answers</h3><p class="empty-state">No responses recorded.</p>';
    return;
  }
  activeModelTab = Math.min(activeModelTab, responses.length - 1);
  const tabs = responses
    .map(
      (r, i) =>
        `<button type="button" class="model-tab ${i === activeModelTab ? 'on' : ''}" data-tab="${i}">${
          (r.model.split('/').pop() || r.model) + (msg.loading?.stage1 && i === responses.length - 1 ? ' …' : '')
        }</button>`
    )
    .join('');
  const cur = responses[activeModelTab];
  withViewportScroll(container, () => {
    container.innerHTML = `
      <h3>Stage 1 — Individual answers</h3>
      <div class="model-tabs">${tabs}</div>
      <div class="markdown-content">${renderMarkdown(cur.response || '')}</div>
    `;
  });
  bindModelTabs(container, (index) => {
    activeModelTab = index;
    renderAnswers(container, msg, isRunning);
  });
}

function renderRankings(container: HTMLElement, msg: AssistantMessage, isRunning: boolean) {
  const rankings = msg.stage2 || [];
  const meta = msg.metadata || {};
  const labelToModel = meta.label_to_model as Record<string, string> | undefined;
  const aggregate = meta.aggregate_rankings as Record<string, unknown>[] | undefined;

  if (!rankings.length && isRunning && msg.loading?.stage2) {
    container.innerHTML = '<h3>Stage 2 — Peer review</h3><p class="review-hint">Collecting evaluations…</p>';
    return;
  }
  if (!rankings.length) {
    if (renderPipelineSteps(container, msg, 'Pipeline — deliberation steps')) return;
    container.innerHTML = '<h3>Stage 2 — Peer review</h3><p class="empty-state">No rankings recorded.</p>';
    return;
  }
  activeModelTab = Math.min(activeModelTab, rankings.length - 1);
  const tabs = rankings
    .map(
      (r, i) =>
        `<button type="button" class="model-tab ${i === activeModelTab ? 'on' : ''}" data-tab="${i}">${
          r.model.split('/').pop() || r.model
        }</button>`
    )
    .join('');
  const cur = rankings[activeModelTab];
  const raw = deAnonymizeText(cur.ranking || '', labelToModel);
  const parsed =
    cur.parsed_ranking?.length
      ? `<div class="parsed-ranking"><b>Extracted ranking</b><br>${cur.parsed_ranking.map(escapeHtml).join('<br>')}</div>`
      : '';
  const agg =
    aggregate?.length
      ? `<div class="parsed-ranking"><b>Aggregate</b><br>${aggregate
          .map((a) => `${escapeHtml(String(a.model ?? ''))}: avg ${a.avg_rank ?? a.average_rank ?? '?'}`)
          .join('<br>')}</div>`
      : '';

  withViewportScroll(container, () => {
    container.innerHTML = `
      <h3>Stage 2 — Peer review</h3>
      <p class="review-hint">Evaluations used anonymous labels; model names shown bold below.</p>
      <div class="model-tabs">${tabs}</div>
      <div class="markdown-content">${renderMarkdown(raw)}</div>
      ${parsed}${agg}
    `;
  });
  bindModelTabs(container, (index) => {
    activeModelTab = index;
    renderRankings(container, msg, isRunning);
  });
}

function renderVerdictViewport(container: HTMLElement, msg: AssistantMessage, isRunning: boolean) {
  const stage3 = msg.stage3;
  if (!stage3?.response && isRunning && msg.loading?.stage3) {
    container.innerHTML = '<h3>Stage 3 — Chairman synthesis</h3><p class="review-hint">Chairman deliberating…</p>';
    return;
  }
  if (!stage3?.response) {
    container.innerHTML = `
      <h3>Review in progress</h3>
      <p class="review-hint">Verdict appears when stage 3 completes. Select earlier steps to inspect answers and rankings.</p>
    `;
    return;
  }
  if (msg.stage3 && msg.stage1 && msg.stage2) {
    container.innerHTML = `
      <h3>Review complete</h3>
      <p class="review-hint">All stages finished. Inspect chairman synthesis below or revisit earlier steps.</p>
      <p><strong>Chairman:</strong> ${stage3.model.split('/').pop() || stage3.model}</p>
      <div class="markdown-content">${renderMarkdown(stage3.response)}</div>
    `;
    return;
  }
  container.innerHTML = `
    <h3>Stage 3 — Chairman synthesis</h3>
    <div class="markdown-content">${renderMarkdown(stage3.response)}</div>
  `;
}