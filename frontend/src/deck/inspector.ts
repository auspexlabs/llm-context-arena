import { renderCostPanel, type CostPanelState, type CostSeriesId } from './cost-panel';
import { formatUsd, turnCostFromMessage } from './cost';
import { escapeHtml } from './escape';
import { executionTrace } from './execution-trace';
import { participantViews, renderAvatar } from './participants';
import { buildPulse } from './pulse';
import {
  assistantMessages,
  getState,
  setContextInjectionSelection,
  setContextPromptModel,
  setDeckView,
} from './store';
import type { AssistantMessage } from './types';

let participantsOpen = false;
let costState: CostPanelState = {
  selected: ['current', 'squad', 'memory'],
  breakdown: false,
  topN: 5,
};

function participantDialog(
  participants: ReturnType<typeof participantViews>,
  msg: AssistantMessage | undefined
) {
  if (!participantsOpen) return '';
  const arena = (msg?.metadata?.arena_models as string[] | undefined) || [];
  return `<div class="participant-backdrop" data-participant-close>
    <section class="participant-dialog" role="dialog" aria-modal="true" aria-label="Turn participants">
      <div class="participant-dialog-head">
        <div><p class="rail-eyebrow">Turn roster</p><h2>Participants</h2></div>
        <button type="button" class="participant-close" data-participant-close aria-label="Close participants">×</button>
      </div>
      <div class="participant-card-list">
        ${participants.map((participant) => {
          const arenaIndex = arena.indexOf(participant.model);
          return `<article class="participant-card tone-${participant.status}">
            ${renderAvatar(participant)}
            <div class="participant-card-main">
              <div class="participant-name"><b>${escapeHtml(participant.short)}</b>${participant.isChair ? '<span class="participant-role">Chair</span>' : ''}</div>
              <p class="participant-provider">${escapeHtml(participant.provider)} · ${escapeHtml(participant.statusLabel)}</p>
              <p class="participant-model-id">${escapeHtml(participant.model)}</p>
              <div class="participant-stats">
                <span>${participant.calls} calls</span>
                <span>${participant.tokens.toLocaleString()} tok</span>
                <span>${formatUsd(participant.costUsd)}</span>
                ${participant.durationMs ? `<span>${Math.round(participant.durationMs / 1000)}s</span>` : ''}
              </div>
              ${participant.roles.length ? `<p class="participant-roles">${participant.roles.map((role) => escapeHtml(role.replace(/_/g, ' '))).join(' · ')}</p>` : ''}
            </div>
            <button type="button" class="participant-open" data-participant-open="${participant.isChair ? 'chair' : arenaIndex}" ${!participant.isChair && arenaIndex < 0 ? 'disabled' : ''}>Inspect</button>
          </article>`;
        }).join('')}
      </div>
    </section>
  </div>`;
}

export function renderInspector(
  root: HTMLElement,
  msg: AssistantMessage | undefined,
  turnIndex: number,
  mode: string
) {
  const state = getState();
  const participants = participantViews(msg, mode, state.modeProgress.activeModel);
  const trace = executionTrace(msg, mode);
  const arenaCount = participants.filter((participant) => !participant.isChair).length;
  const succeeded = trace?.summary.participant_succeeded ?? participants.filter(
    (participant) => !participant.isChair && participant.succeededSteps > 0
  ).length;
  const failures = trace?.summary.participant_failed ?? participants.filter(
    (participant) => !participant.isChair && participant.failedSteps > 0 && !participant.succeededSteps
  ).length;
  const pulse = buildPulse(msg, mode, state.isRunning, state.modeProgress);
  const summaries = state.conversations;
  const sessionTurns = assistantMessages(state.conversation).length;
  const sessionCost = assistantMessages(state.conversation).reduce(
    (sum, message) => sum + turnCostFromMessage(message).cost_usd,
    0
  );

  root.innerHTML = `
    <div class="rail-instruments">
      <section class="rail-panel participants-panel">
        <div class="rail-panel-head">
          <div><p class="rail-eyebrow">Roster</p><h2>Participants</h2></div>
          <span class="rail-panel-stat ${failures ? 'tone-bad' : ''}">${succeeded}/${arenaCount}</span>
        </div>
        <div class="rail-panel-body" data-rail-scroll="participants">
          <div class="avatar-stack">${participants.map((participant) => renderAvatar(participant, true)).join('')}</div>
          <p class="participant-summary">${arenaCount} arena model${arenaCount === 1 ? '' : 's'}${participants.some((participant) => participant.isChair) ? ' + chair' : ''}${failures ? ` · ${failures} failed` : ''}</p>
          <button type="button" class="rail-action" data-show-participants>Show participants</button>
        </div>
      </section>

      <section class="rail-panel pulse-panel tone-${pulse.tone}">
        <div class="rail-panel-head">
          <div><p class="rail-eyebrow">${escapeHtml(pulse.modeLabel)}</p><h2>Deliberation pulse</h2></div>
          <span class="pulse-dot"></span>
        </div>
        <div class="rail-panel-body" data-rail-scroll="pulse">
          <p class="pulse-label">${escapeHtml(pulse.signalLabel)}</p>
          <p class="pulse-value">${escapeHtml(pulse.signalValue)}</p>
          <p class="pulse-detail">${escapeHtml(pulse.detail)}</p>
          <p class="pulse-applicability">${escapeHtml(pulse.applicability)}</p>
          <button type="button" class="rail-action" data-pulse-view="${pulse.targetView}">${pulse.targetView === 'rankings' ? 'Inspect rankings' : pulse.targetView === 'quality' ? 'Open quality' : 'Inspect steps'}</button>
        </div>
      </section>

      <section class="rail-panel cost-panel">
        <div class="rail-panel-head">
          <div><p class="rail-eyebrow">Spend</p><h2>Cost</h2></div>
          <span class="rail-panel-stat">${formatUsd(sessionCost)}</span>
        </div>
        <div class="rail-panel-body" data-rail-scroll="cost">
          <p class="cost-session-meta">${sessionTurns} turn${sessionTurns === 1 ? '' : 's'} in current session</p>
          ${renderCostPanel(costState, state.conversation, summaries, msg)}
        </div>
      </section>
    </div>
    ${participantDialog(participants, msg)}
  `;

  const rerender = () => renderInspector(root, msg, turnIndex, mode);

  root.querySelector('[data-show-participants]')?.addEventListener('click', () => {
    participantsOpen = true;
    rerender();
  });
  root.querySelectorAll('[data-participant-close]').forEach((element) => {
    element.addEventListener('click', (event) => {
      if (event.currentTarget === event.target || (event.currentTarget as HTMLElement).classList.contains('participant-close')) {
        participantsOpen = false;
        rerender();
      }
    });
  });
  root.querySelectorAll('[data-participant-open]').forEach((element) => {
    element.addEventListener('click', () => {
      const target = (element as HTMLElement).dataset.participantOpen;
      participantsOpen = false;
      if (target === 'chair') setDeckView('verdict');
      else if (target != null && Number(target) >= 0) {
        setContextPromptModel(Number(target));
        setContextInjectionSelection(`arena-${Number(target)}`);
      }
      else setDeckView('answers');
    });
  });
  root.querySelector('[data-pulse-view]')?.addEventListener('click', (event) => {
    setDeckView((event.currentTarget as HTMLElement).dataset.pulseView as 'answers' | 'rankings' | 'quality');
  });
  root.querySelectorAll('[data-cost-series]').forEach((element) => {
    element.addEventListener('click', () => {
      const series = (element as HTMLElement).dataset.costSeries as CostSeriesId;
      const selected = costState.selected.includes(series)
        ? costState.selected.filter((item) => item !== series)
        : [...costState.selected, series];
      costState = {
        ...costState,
        selected,
        breakdown: selected.length === 1 ? costState.breakdown : false,
      };
      rerender();
    });
  });
  root.querySelector('[data-cost-break]')?.addEventListener('click', () => {
    if (costState.selected.length !== 1) return;
    costState = { ...costState, breakdown: !costState.breakdown };
    rerender();
  });
  root.querySelectorAll('[data-cost-top]').forEach((element) => {
    element.addEventListener('click', () => {
      costState = { ...costState, topN: Number((element as HTMLElement).dataset.costTop) };
      rerender();
    });
  });
}
