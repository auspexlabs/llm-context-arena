import { deAnonymizeText, renderMarkdown } from '../markdown';
import type { AssistantMessage, CouncilStepId } from '../types';

let activeModelTab = 0;

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

function renderAnswers(container: HTMLElement, msg: AssistantMessage, isRunning: boolean) {
  const responses = msg.stage1 || [];
  if (!responses.length && isRunning && msg.loading?.stage1) {
    container.innerHTML = '<h3>Stage 1 — Individual answers</h3><p class="review-hint">Collecting responses…</p>';
    return;
  }
  if (!responses.length) {
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
  container.innerHTML = `
    <h3>Stage 1 — Individual answers</h3>
    <div class="model-tabs">${tabs}</div>
    <div class="markdown-content">${renderMarkdown(cur.response || '')}</div>
  `;
  container.querySelectorAll('.model-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      activeModelTab = Number((btn as HTMLElement).dataset.tab);
      renderAnswers(container, msg, isRunning);
    });
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
      ? `<div class="parsed-ranking"><b>Extracted ranking</b><br>${cur.parsed_ranking.join('<br>')}</div>`
      : '';
  const agg =
    aggregate?.length
      ? `<div class="parsed-ranking"><b>Aggregate</b><br>${aggregate
          .map((a) => `${a.model}: avg ${a.average_rank ?? '?'}`)
          .join('<br>')}</div>`
      : '';

  container.innerHTML = `
    <h3>Stage 2 — Peer review</h3>
    <p class="review-hint">Evaluations used anonymous labels; model names shown bold below.</p>
    <div class="model-tabs">${tabs}</div>
    <div class="markdown-content">${renderMarkdown(raw)}</div>
    ${parsed}${agg}
  `;
  container.querySelectorAll('.model-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      activeModelTab = Number((btn as HTMLElement).dataset.tab);
      renderRankings(container, msg, isRunning);
    });
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