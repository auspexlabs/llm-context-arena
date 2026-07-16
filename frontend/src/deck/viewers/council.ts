import { escapeHtml } from '../escape';
import { executionTrace, tracePayload, traceRows, traceStepById } from '../execution-trace';
import { deAnonymizeText, renderMarkdown } from '../markdown';
import { preventFocusScroll } from '../scroll-anchor';
import { setDeckView } from '../store';
import type { AssistantMessage, CouncilStepId } from '../types';

let activeModelTab = 0;
let activeRankingTab = 0;
let activeFightPhase: 'answer' | 'critique' | 'defense' = 'answer';
let activeFightModel = 0;

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
  activeRankingTab = 0;
  activeFightPhase = 'answer';
  activeFightModel = 0;
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

type PipelineStep = { role?: string; label?: string; model?: string; response?: string; status?: string };

function pipelineSteps(msg: AssistantMessage): PipelineStep[] {
  const mode = String(msg.metadata?.mode || 'council');
  return traceRows(msg, mode, false).map(({ node, payload }) => ({
    role: node.role,
    label: node.role,
    model: node.model,
    response: String(payload?.response || payload?.ranking || ''),
    status: node.status,
  }));
}

function renderRoundRobinSteps(container: HTMLElement, msg: AssistantMessage) {
  const trace = executionTrace(msg, 'round_robin');
  if (!trace || trace.mode !== 'round_robin') return false;
  const drafts = trace.steps.filter((node) => node.kind === 'draft' && !node.terminal);
  if (!drafts.length) return false;
  activeModelTab = Math.min(activeModelTab, drafts.length - 1);
  const selected = drafts[activeModelTab];
  const payload = tracePayload(msg, selected);
  const predecessor = selected.predecessor_step_ids.length
    ? traceStepById(trace, selected.predecessor_step_ids[selected.predecessor_step_ids.length - 1])
    : null;
  const predecessorPayload = predecessor ? tracePayload(msg, predecessor) : null;
  const incoming = String(payload?.prior_draft || predecessorPayload?.response || '');
  const output = String(payload?.response || '');
  const tabs = drafts.map((node, index) => {
    const short = node.model.split('/').pop() || node.model || `Step ${index + 1}`;
    return `<button type="button" class="model-tab rr-step-tab tone-${node.status} ${index === activeModelTab ? 'on' : ''}" data-tab="${index}">
      <span>${index + 1}</span>${escapeHtml(short)}${node.status === 'failed' ? ' ✕' : ' ✓'}
    </button>`;
  }).join('');
  const received = predecessor
    ? `Received ${escapeHtml(predecessor.model.split('/').pop() || predecessor.model)} draft`
    : 'Started from question + injected context';
  const failure = selected.failure
    ? `<div class="rr-failure"><b>Step failed${selected.failure.status ? ` · HTTP ${selected.failure.status}` : ''}</b><span>${escapeHtml(selected.failure.failure_kind || selected.failure.message || 'No usable response')}</span></div>`
    : '';
  const inputBody = incoming
    ? `<div class="markdown-content">${renderMarkdown(incoming)}</div>`
    : '<p class="empty-state">No predecessor draft; this model starts the chain.</p>';
  const outputBody = output
    ? `<div class="markdown-content">${renderMarkdown(output)}</div>`
    : '<p class="empty-state">No draft was produced.</p>';

  withViewportScroll(container, () => {
    container.innerHTML = `
      <div class="rr-head">
        <div><p class="rail-eyebrow">Sequential mode</p><h3>Round Robin refinement</h3></div>
        <span class="rr-count">${trace.summary.drafts_succeeded}/${trace.summary.drafts_expected} drafts</span>
      </div>
      <p class="review-hint">Each numbered model receives the last successful draft. Failed steps do not replace the chain artifact.</p>
      <div class="model-tabs rr-sequence">${tabs}</div>
      <div class="rr-route"><span>Step ${activeModelTab + 1} of ${drafts.length}</span><b>${received}</b><span class="tone-${selected.status}">${selected.status}</span></div>
      ${failure}
      <div class="rr-compare">
        <section class="rr-draft-panel incoming"><h4>Incoming draft</h4>${inputBody}</section>
        <section class="rr-draft-panel outgoing"><h4>${selected.status === 'failed' ? 'Attempted output' : 'Revised draft'}</h4>${outputBody}</section>
      </div>
      ${msg.stage3?.response ? '<button type="button" class="rail-action rr-verdict-link" data-open-verdict>Open chair verdict →</button>' : ''}
    `;
  });
  bindModelTabs(container, (index) => {
    activeModelTab = index;
    renderRoundRobinSteps(container, msg);
  });
  container.querySelector('[data-open-verdict]')?.addEventListener('click', () => setDeckView('verdict'));
  return true;
}

function renderPipelineSteps(container: HTMLElement, msg: AssistantMessage, title: string) {
  const steps = pipelineSteps(msg);
  if (!steps.length) return false;
  activeModelTab = Math.min(activeModelTab, steps.length - 1);
  const tabs = steps
    .map((s, i) => {
      const label = s.label || s.role || `Step ${i + 1}`;
      const short = label.replace(/^draft_/i, '').replace(/_/g, ' ');
      return `<button type="button" class="model-tab tone-${s.status || 'pending'} ${i === activeModelTab ? 'on' : ''}" data-tab="${i}">${short}${s.status === 'failed' ? ' ✕' : ''}</button>`;
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

function renderFightSteps(container: HTMLElement, msg: AssistantMessage) {
  const trace = executionTrace(msg, 'fight');
  if (!trace || trace.mode !== 'fight') return false;
  const debate = trace.steps.filter((node) => !node.terminal);
  if (!debate.length) return false;

  const phases: Array<{ id: 'answer' | 'critique' | 'defense'; label: string; route: string }> = [
    { id: 'answer', label: 'Opening', route: 'Grounded question → opening position' },
    { id: 'critique', label: 'Critique', route: 'Peer openings (own excluded) → critique' },
    { id: 'defense', label: 'Defense', route: 'Own opening + peer critiques (own excluded) → defense' },
  ];
  const phaseNodes = debate.filter((node) => node.kind === activeFightPhase);
  if (!phaseNodes.length) {
    activeFightPhase = phases.find((phase) => debate.some((node) => node.kind === phase.id))?.id || 'answer';
  }
  const selectedNodes = debate.filter((node) => node.kind === activeFightPhase);
  activeFightModel = Math.min(activeFightModel, Math.max(0, selectedNodes.length - 1));
  const selected = selectedNodes[activeFightModel];
  if (!selected) return false;
  const payload = tracePayload(msg, selected);
  const parents = selected.predecessor_step_ids
    .map((id) => traceStepById(trace, id))
    .filter((node): node is NonNullable<typeof node> => Boolean(node));
  const phase = phases.find((item) => item.id === activeFightPhase)!;

  const phaseTabs = phases.map((item) => {
    const nodes = debate.filter((node) => node.kind === item.id);
    const succeeded = nodes.filter((node) => node.status === 'succeeded').length;
    return `<button type="button" class="fight-phase-tab ${item.id === activeFightPhase ? 'on' : ''}" data-fight-phase="${item.id}">
      <span>${escapeHtml(item.label)}</span><b>${succeeded}/${nodes.length}</b>
    </button>`;
  }).join('');
  const modelTabs = selectedNodes.map((node, index) => {
    const short = node.model.split('/').pop() || node.model;
    return `<button type="button" class="model-tab tone-${node.status} ${index === activeFightModel ? 'on' : ''}" data-fight-model="${index}">
      ${escapeHtml(short)}${node.status === 'failed' ? ' ✕' : ''}
    </button>`;
  }).join('');
  const inputArtifacts = parents.length
    ? parents.map((node) => `<span class="fight-artifact tone-${node.status}">${escapeHtml(node.kind)} · ${escapeHtml(node.model.split('/').pop() || node.model)}</span>`).join('')
    : '<span class="fight-artifact source">question + RAG event</span>';
  const failure = selected.failure
    ? `<div class="rr-failure"><b>Step failed${selected.failure.status ? ` · HTTP ${selected.failure.status}` : ''}</b><span>${escapeHtml(selected.failure.failure_kind || selected.failure.message || 'No usable response')}</span></div>`
    : '';
  const response = String(payload?.response || '');
  const body = response
    ? `<div class="markdown-content">${renderMarkdown(response)}</div>`
    : '<p class="empty-state">No response was produced for this step.</p>';

  withViewportScroll(container, () => {
    container.innerHTML = `
      <div class="rr-head">
        <div><p class="rail-eyebrow">Adversarial mode</p><h3>Fight debate</h3></div>
        <span class="rr-count">${trace.summary.arena_succeeded_steps}/${trace.summary.arena_steps} debate steps</span>
      </div>
      <p class="review-hint">Openings are attacked by peers, then each model defends or revises its own position. Agreement is not inferred.</p>
      <div class="fight-phase-tabs">${phaseTabs}</div>
      <div class="model-tabs">${modelTabs}</div>
      <div class="fight-route">
        <strong>${escapeHtml(phase.route)}</strong>
        <span class="tone-${selected.status}">${selected.status}</span>
      </div>
      <div class="fight-artifacts" aria-label="Input artifacts">${inputArtifacts}</div>
      ${failure}
      ${body}
      <button type="button" class="ctx-link fight-context-link" data-open-fight-context>Inspect injected workflow →</button>
    `;
  });
  container.querySelectorAll('[data-fight-phase]').forEach((button) => {
    preventFocusScroll(button);
    button.addEventListener('click', () => {
      activeFightPhase = (button as HTMLElement).dataset.fightPhase as typeof activeFightPhase;
      activeFightModel = 0;
      renderFightSteps(container, msg);
    });
  });
  container.querySelectorAll('[data-fight-model]').forEach((button) => {
    preventFocusScroll(button);
    button.addEventListener('click', () => {
      activeFightModel = Number((button as HTMLElement).dataset.fightModel);
      renderFightSteps(container, msg);
    });
  });
  container.querySelector('[data-open-fight-context]')?.addEventListener('click', () => setDeckView('context'));
  return true;
}

function renderAnswers(container: HTMLElement, msg: AssistantMessage, isRunning: boolean) {
  const responses = msg.stage1 || [];
  if (!responses.length && isRunning && msg.loading?.stage1) {
    container.innerHTML = '<h3>Stage 1 — Individual answers</h3><p class="review-hint">Collecting responses…</p>';
    return;
  }
  if (!responses.length) {
    if (renderRoundRobinSteps(container, msg)) return;
    if (renderFightSteps(container, msg)) return;
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
    if (renderRoundRobinSteps(container, msg)) return;
    if (renderFightSteps(container, msg)) return;
    if (renderPipelineSteps(container, msg, 'Pipeline — deliberation steps')) return;
    container.innerHTML = '<h3>Stage 2 — Peer review</h3><p class="empty-state">No rankings recorded.</p>';
    return;
  }
  const aggregateTab = aggregate?.length ? rankings.length : -1;
  activeRankingTab = Math.min(activeRankingTab, aggregateTab >= 0 ? aggregateTab : rankings.length - 1);
  const tabs = rankings
    .map(
      (r, i) =>
        `<button type="button" class="model-tab ${i === activeRankingTab ? 'on' : ''}" data-tab="${i}">${
          r.model.split('/').pop() || r.model
        }</button>`
    )
    .join('') + (aggregateTab >= 0
      ? `<button type="button" class="model-tab aggregate-tab ${activeRankingTab === aggregateTab ? 'on' : ''}" data-tab="${aggregateTab}">Aggregate</button>`
      : '');
  const showingAggregate = activeRankingTab === aggregateTab;
  const cur = showingAggregate ? null : rankings[activeRankingTab];
  const raw = cur ? deAnonymizeText(cur.ranking || '', labelToModel) : '';
  const parsed = cur?.parsed_ranking?.length
    ? `<div class="parsed-ranking"><b>This model's extracted ballot</b><br>${cur.parsed_ranking.map(escapeHtml).join('<br>')}</div>`
    : '';
  const aggregateBody = showingAggregate && aggregate?.length
    ? `<div class="aggregate-ranking" aria-label="Final aggregate ranking">
        <p class="review-hint">Final council-wide order calculated from all ${rankings.length} peer ballots. Lower average is better.</p>
        ${aggregate.map((entry, index) => {
          const model = String(entry.model || 'unknown');
          const short = model.split('/').pop() || model;
          const average = entry.avg_rank ?? entry.average_rank ?? '?';
          const votes = entry.votes ?? '?';
          const positions = Array.isArray(entry.rank_positions) ? entry.rank_positions.join(' · ') : '—';
          return `<div class="aggregate-ranking-row">
            <span class="aggregate-position">#${index + 1}</span>
            <strong title="${escapeHtml(model)}">${escapeHtml(short)}</strong>
            <span>avg ${escapeHtml(String(average))}</span>
            <span>${escapeHtml(String(votes))} votes</span>
            <span class="meta">positions ${escapeHtml(positions)}</span>
          </div>`;
        }).join('')}
      </div>`
    : '';

  withViewportScroll(container, () => {
    container.innerHTML = `
      <h3>Stage 2 — Peer review</h3>
      <p class="review-hint">Evaluations used anonymous labels; model names shown bold below.</p>
      <div class="model-tabs">${tabs}</div>
      ${showingAggregate ? aggregateBody : `<div class="markdown-content">${renderMarkdown(raw)}</div>${parsed}`}
    `;
  });
  bindModelTabs(container, (index) => {
    activeRankingTab = index;
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
