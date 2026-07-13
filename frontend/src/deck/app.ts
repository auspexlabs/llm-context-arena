import { api } from './api';
import { formatUsd, turnCostFromMessage } from './cost';
import {
  assistantMessages,
  getState,
  patch,
  selectConversation,
  setFocusedStep,
  setTheme,
  subscribe,
  updateConversations,
} from './store';
import type { CouncilStepId } from './types';
import { runTurnStream } from './stream';
import { resetModelTab, renderCouncilViewport } from './viewers/council';
import './deck.css';

const STEP_IDS: CouncilStepId[] = ['answers', 'rankings', 'verdict'];
const STEP_LABELS = ['1 Answers', '2 Rankings', '3 Verdict'];

let abortCtrl: AbortController | null = null;
let els: Record<string, HTMLElement> = {};

export function mountApp(root: HTMLElement) {
  root.innerHTML = `
    <div class="observatory">
      <aside class="rail" id="rail"></aside>
      <main class="deck" id="deck"></main>
      <aside class="insp" id="inspector"></aside>
      <div class="verdict-lane" id="verdict"></div>
      <footer class="foot" id="foot"></footer>
    </div>
  `;
  els = {
    rail: root.querySelector('#rail')!,
    deck: root.querySelector('#deck')!,
    inspector: root.querySelector('#inspector')!,
    verdict: root.querySelector('#verdict')!,
    foot: root.querySelector('#foot')!,
  };
  subscribe(render);
  void bootstrap();
}

async function bootstrap() {
  try {
    const settings = await api.getSettings();
    if (settings?.theme === 'dark' || settings?.theme === 'light') {
      setTheme(settings.theme);
    }
  } catch {
    setTheme('dark');
  }
  await refreshConversations();
}

async function refreshConversations() {
  const convs = await api.listConversations();
  updateConversations(convs);
  const { conversationId } = getState();
  if (conversationId) {
    const conv = await api.getConversation(conversationId);
    selectConversation(conversationId, conv);
  } else if (convs.length) {
    const conv = await api.getConversation(convs[0].id);
    selectConversation(convs[0].id, conv);
  }
}

function render() {
  renderRail();
  renderDeck();
  renderInspector();
  renderVerdict();
  renderFoot();
}

function renderRail() {
  const s = getState();
  const assistants = assistantMessages(s.conversation);
  const turnsHtml = assistants
    .map((msg, i) => {
      const isLast = i === assistants.length - 1;
      const status = s.isRunning && isLast ? 'running' : msg.stage3?.response ? 'complete' : 'idle';
      const cost = turnCostFromMessage(msg);
      const meta =
        status === 'running'
          ? `<span style="color:var(--accent)">● running</span>`
          : status === 'complete'
            ? `<span class="meta" style="color:var(--ok)">✓ complete</span>`
            : `<span class="meta">pending</span>`;
      return `
        <button type="button" class="turn-item ${status === 'complete' ? 'complete' : ''} ${i === s.selectedTurnIndex ? 'on' : ''}" data-turn="${i}">
          <div class="title">Turn ${i + 1}</div>
          <div class="meta">${meta}</div>
          ${status === 'complete' ? `<div class="cost">${formatUsd(cost.cost_usd)} · ${cost.total_tokens.toLocaleString()} tok</div>` : ''}
        </button>`;
    })
    .join('');

  els.rail.innerHTML = `
    <div class="rail-head">
      <h2>Sessions</h2>
      <button type="button" class="rail-btn" id="btn-settings">⚙</button>
    </div>
    ${s.conversations
      .map(
        (c) => `
      <button type="button" class="session ${c.id === s.conversationId ? 'on' : ''}" data-session="${c.id}">
        <div class="title">${c.title || 'Session'} · ${c.mode || 'council'}</div>
        <div class="meta">${c.message_count} messages</div>
      </button>`
      )
      .join('')}
    <h2 style="margin-top:16px">Turns</h2>
    ${turnsHtml || '<p class="meta">No turns yet — take control to start.</p>'}
    <button type="button" class="rail-btn" id="btn-new" style="margin-top:12px">+ New session</button>
  `;

  els.rail.querySelector('#btn-settings')?.addEventListener('click', () => openSettings());
  els.rail.querySelector('#btn-new')?.addEventListener('click', () => void createSession());
  els.rail.querySelectorAll('[data-session]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = (btn as HTMLElement).dataset.session!;
      const conv = await api.getConversation(id);
      selectConversation(id, conv);
      resetModelTab();
    });
  });
  els.rail.querySelectorAll('[data-turn]').forEach((btn) => {
    btn.addEventListener('click', () => {
      patch({ selectedTurnIndex: Number((btn as HTMLElement).dataset.turn) });
      resetModelTab();
    });
  });
}

function renderDeck() {
  const s = getState();
  const assistants = assistantMessages(s.conversation);
  const msg = assistants[s.selectedTurnIndex] ?? null;
  const isLast = s.selectedTurnIndex === assistants.length - 1;
  const running = s.isRunning && isLast;
  const complete = !!msg?.stage3?.response;
  const mode = s.conversation?.mode || 'council';

  const stepsHtml = STEP_IDS.map((id, i) => {
    let cls = 'step-btn';
    if (s.focusedStep === id) cls += ' on';
    if (running) {
      if (id === 'answers' && msg?.stage1) cls += ' done';
      else if (id === 'rankings' && msg?.loading?.stage2) cls += ' live';
      else if (id === 'rankings' && msg?.stage2) cls += ' done';
      else if (id === 'verdict' && msg?.loading?.stage3) cls += ' live';
    } else if (complete) {
      cls += ' done';
    }
    return `<button type="button" class="${cls}" data-step="${id}">${STEP_LABELS[i]}</button>`;
  }).join('');

  const statusCls = running ? 'status-run' : complete ? 'status-done' : '';
  const statusLabel = running ? 'running' : complete ? 'complete' : 'idle';

  els.deck.innerHTML = `
    <div class="hdr"><b>${mode}</b> · Turn ${s.selectedTurnIndex + 1} · <span class="${statusCls}">${statusLabel}</span>
      ${running && s.modeProgress.total ? ` · step ${s.modeProgress.current}/${s.modeProgress.total}` : ''}
    </div>
    <div class="timeline">${stepsHtml}</div>
    <div class="viewport" id="viewport"></div>
  `;

  els.deck.querySelectorAll('[data-step]').forEach((btn) => {
    btn.addEventListener('click', () => {
      setFocusedStep((btn as HTMLElement).dataset.step as CouncilStepId);
      resetModelTab();
    });
  });

  const vp = els.deck.querySelector('#viewport') as HTMLElement;
  renderCouncilViewport(vp, msg, s.focusedStep, running);
}

function renderInspector() {
  const s = getState();
  const msg = assistantMessages(s.conversation)[s.selectedTurnIndex];
  const meta = msg?.metadata || {};
  const ctx = msg?.contextSources as unknown[] | undefined;
  const eq = meta.execution_quality as Record<string, unknown> | undefined;
  const agg = meta.aggregate_rankings as Record<string, unknown>[] | undefined;

  const ctxHtml = ctx?.length
    ? `<p><b>RAG</b>${ctx.length} sources</p>`
    : '<p>No context trace</p>';
  const rankHtml = agg?.length
    ? agg.map((a, i) => `<p><b>#${i + 1}</b> ${String(a.model || '').split('/').pop()}</p>`).join('')
    : '<p>—</p>';
  const qHtml = eq
    ? `<p><b>${eq.severity || 'ok'}</b></p><p>${eq.acceptable ? 'acceptable' : 'review needed'}</p>`
    : '<p>—</p>';

  els.inspector.innerHTML = `
    <div class="insp-h"><div class="on">Context</div><div class="on">Rankings</div><div class="on">Quality</div></div>
    <div class="insp-b">
      <div class="col">${ctxHtml}<p class="meta">mode: ${String(meta.mode || s.conversation?.mode || '')}</p></div>
      <div class="col">${rankHtml}</div>
      <div class="col">${qHtml}</div>
    </div>
  `;
}

function renderVerdict() {
  const s = getState();
  const msg = assistantMessages(s.conversation)[s.selectedTurnIndex];
  const text = msg?.stage3?.response;
  if (!text) {
    els.verdict.className = 'verdict-lane empty';
    els.verdict.innerHTML = '<span class="label">Verdict</span> — synthesis after stage 3';
    return;
  }
  els.verdict.className = 'verdict-lane';
  const excerpt = text.length > 400 ? `${text.slice(0, 400)}…` : text;
  els.verdict.innerHTML = `<span class="label">Verdict</span><div class="body">${excerpt.replace(/</g, '&lt;')}</div>`;
}

function renderFoot() {
  const s = getState();
  const note = s.isRunning ? 'Watching · SSE connected' : s.takeControl ? 'You are driving' : 'Turn complete · watching idle';

  els.foot.innerHTML = `
    <span class="foot-note">${note}</span>
    <div class="composer ${s.takeControl ? 'on' : ''}" id="composer">
      <textarea id="query" rows="2" placeholder="Hypothesis or question for the arena…"></textarea>
      <button type="button" id="btn-send">Run turn</button>
    </div>
    <button type="button" class="tc ${s.takeControl ? 'on' : ''}" id="btn-tc">Take control</button>
  `;

  els.foot.querySelector('#btn-tc')?.addEventListener('click', () => {
    patch({ takeControl: !getState().takeControl });
  });
  els.foot.querySelector('#btn-send')?.addEventListener('click', () => void submitQuery());
}

async function submitQuery() {
  const s = getState();
  if (!s.conversationId || !s.takeControl) return;
  const ta = document.getElementById('query') as HTMLTextAreaElement | null;
  const content = ta?.value.trim();
  if (!content) return;
  if (ta) ta.value = '';
  abortCtrl?.abort();
  abortCtrl = new AbortController();
  try {
    await runTurnStream(s.conversationId, content, abortCtrl.signal);
    await refreshConversations();
  } catch (e) {
    console.error(e);
    patch({ isRunning: false });
  }
}

async function createSession() {
  const conv = await api.createConversation('council');
  await refreshConversations();
  const full = await api.getConversation(conv.id);
  selectConversation(conv.id, full);
}

function openSettings() {
  const backdrop = document.createElement('div');
  backdrop.className = 'settings-backdrop';
  backdrop.innerHTML = `
    <div class="settings-panel">
      <h2>Settings</h2>
      <label>Theme<select id="set-theme"><option value="dark">Dark</option><option value="light">Light</option></select></label>
      <label>Arena squad<select id="set-squad"><option value="normal">normal</option></select></label>
      <div style="display:flex;gap:8px;margin-top:16px">
        <button type="button" class="rail-btn" id="set-save">Save</button>
        <button type="button" class="rail-btn" id="set-close">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(backdrop);
  api.getSettings().then((data) => {
    const theme = backdrop.querySelector('#set-theme') as HTMLSelectElement;
    const squad = backdrop.querySelector('#set-squad') as HTMLSelectElement;
    if (theme && data?.theme) theme.value = data.theme;
    (data?.available_squads || []).forEach((sq: { name: string; label: string }) => {
      const opt = document.createElement('option');
      opt.value = sq.name;
      opt.textContent = sq.label || sq.name;
      squad?.appendChild(opt);
    });
    if (squad && data?.arena_squad) squad.value = data.arena_squad;
  });
  backdrop.querySelector('#set-close')?.addEventListener('click', () => backdrop.remove());
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) backdrop.remove();
  });
  backdrop.querySelector('#set-save')?.addEventListener('click', async () => {
    const theme = (backdrop.querySelector('#set-theme') as HTMLSelectElement).value;
    const squad = (backdrop.querySelector('#set-squad') as HTMLSelectElement).value;
    setTheme(theme as 'light' | 'dark');
    await api.applySquad(squad);
    await api.updateSettings({ theme });
    backdrop.remove();
  });
}