import { api } from './api';
import { formatUsd, turnCostFromMessage } from './cost';
import { userQueryBefore } from './normalize';
import { buildBreadcrumb } from './breadcrumb';
import { renderInspector } from './inspector';
import { anchorOffsetIn, consumeScrollAnchor, restoreViewportScroll } from './scroll-anchor';
import { buildTurnContext } from './turn-context';
import {
  assistantMessages,
  getState,
  patch,
  selectConversation,
  selectTurn,
  setDeckView,
  setTheme,
  subscribe,
  updateConversations,
} from './store';
import type { DeckView } from './types';
import { startLivePoll } from './live-poll';
import { formatDuration, timelineStepTimer, totalElapsedMs } from './runtime';
import { syncRuntimeClock } from './runtime-clock';
import { isPendingTurnSelected } from './turns';
import { runTurnStream } from './stream';
import { resetModelTab } from './viewers/council';
import { renderDeckViewport } from './viewers/deck';
import './deck.css';

const TIMELINE: { id: DeckView; label: string }[] = [
  { id: 'context', label: 'Context' },
  { id: 'answers', label: '1 Answers' },
  { id: 'rankings', label: '2 Rankings' },
  { id: 'verdict', label: '3 Verdict' },
  { id: 'quality', label: 'Quality' },
];

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
  subscribe((scope) => {
    if (scope === 'viewport') renderViewportOnly();
    else render();
  });
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
  startLivePoll();
  syncRuntimeClock();
}

async function refreshConversations() {
  const convs = await api.listConversations();
  updateConversations(convs);
  const { conversationId } = getState();
  if (conversationId) {
    const conv = await api.getConversation(conversationId);
    selectConversation(conversationId, conv, { pinned: getState().sessionPinned });
  } else if (convs.length) {
    const conv = await api.getConversation(convs[0].id);
    selectConversation(convs[0].id, conv);
  }
}

function render() {
  renderRail();
  renderDeck();
  renderInspectorPanel();
  renderVerdict();
  renderFoot();
}

function renderViewportOnly() {
  const vp = els.deck.querySelector('#viewport') as HTMLElement | null;
  if (!vp) {
    renderDeck();
    return;
  }
  const scrollTop = vp.scrollTop;
  const anchor = consumeScrollAnchor();
  const anchorRelTop = anchor ? anchorOffsetIn(vp, anchor) : null;
  const s = getState();
  const assistants = assistantMessages(s.conversation);
  const msg = assistants[s.selectedTurnIndex] ?? null;
  const isLast = s.selectedTurnIndex === assistants.length - 1;
  const pendingSelected = isPendingTurnSelected(
    s.selectedTurnIndex,
    assistants.length,
    s.pendingTurn
  );
  const running = (s.isRunning && isLast) || pendingSelected;
  const now = s.runtimeTick || Date.now();
  renderDeckViewport(
    vp,
    s.deckView,
    s.conversation,
    msg,
    s.selectedTurnIndex,
    running,
    s.pendingTurn,
    s.activeAgentTurn,
    s.modeProgress,
    s.turnRuntime,
    now
  );
  requestAnimationFrame(() => restoreViewportScroll(vp, scrollTop, anchor, anchorRelTop));
}

function renderRail() {
  const s = getState();
  const assistants = assistantMessages(s.conversation);
  const messages = s.conversation?.messages || [];
  const assistantTurnsHtml = assistants
    .map((msg, i) => {
      const isLast = i === assistants.length - 1;
      const status = s.isRunning && isLast ? 'running' : msg.stage3?.response ? 'complete' : 'idle';
      const cost = turnCostFromMessage(msg);
      const query = userQueryBefore(messages, i);
      const queryPreview = query ? query.slice(0, 48) + (query.length > 48 ? '…' : '') : '';
      const meta =
        status === 'running'
          ? `<span style="color:var(--accent)">● running</span>`
          : status === 'complete'
            ? `<span class="meta" style="color:var(--ok)">✓ complete</span>`
            : `<span class="meta">pending</span>`;
      return `
        <button type="button" class="turn-item ${status === 'complete' ? 'complete' : ''} ${i === s.selectedTurnIndex ? 'on' : ''}" data-turn="${i}">
          <div class="title">Turn ${i + 1}${queryPreview ? ` · ${queryPreview.replace(/</g, '')}` : ''}</div>
          <div class="meta">${meta}</div>
          ${status === 'complete' ? `<div class="cost">${formatUsd(cost.cost_usd)} · ${cost.total_tokens.toLocaleString()} tok</div>` : ''}
        </button>`;
    })
    .join('');

  const pending = s.pendingTurn;
  const pendingHtml =
    pending && isPendingTurnSelected(pending.turnIndex, assistants.length, pending)
      ? `
        <button type="button" class="turn-item on running" data-turn="${pending.turnIndex}">
          <div class="title">Turn ${pending.turnIndex + 1} · ${pending.userQuery.slice(0, 40).replace(/</g, '')}${pending.userQuery.length > 40 ? '…' : ''}</div>
          <div class="meta"><span style="color:var(--accent)">● running</span> · external${s.turnRuntime?.turnIndex === pending.turnIndex ? ` · ${formatDuration(totalElapsedMs(s.turnRuntime, s.runtimeTick || Date.now()))}` : ''}</div>
        </button>`
      : pending
        ? `
        <button type="button" class="turn-item running" data-turn="${pending.turnIndex}">
          <div class="title">Turn ${pending.turnIndex + 1} · ${pending.userQuery.slice(0, 40).replace(/</g, '')}${pending.userQuery.length > 40 ? '…' : ''}</div>
          <div class="meta"><span style="color:var(--accent)">● running</span> · external${s.turnRuntime?.turnIndex === pending.turnIndex ? ` · ${formatDuration(totalElapsedMs(s.turnRuntime, s.runtimeTick || Date.now()))}` : ''}</div>
        </button>`
        : '';

  const turnsHtml = assistantTurnsHtml + pendingHtml;

  const sessionTitle = s.conversation?.title || 'No session';
  const sessionMode = s.conversation?.mode || 'council';
  const pollNote = s.pollError
    ? `<p class="meta poll-err">Live refresh: ${s.pollError.replace(/</g, '')}</p>`
    : '<p class="meta poll-ok">Live refresh on</p>';

  els.rail.innerHTML = `
    <div class="rail-head">
      <h2>Observatory</h2>
      <button type="button" class="rail-btn" id="btn-settings">⚙</button>
    </div>
    ${pollNote}
    <div class="rail-turns">
      <div class="rail-turns-head">
        <h2>Turns</h2>
        <span class="meta">${sessionTitle} · ${sessionMode}</span>
      </div>
      ${turnsHtml || '<p class="meta">No turns yet — take control to start.</p>'}
    </div>
    <button type="button" class="rail-btn" id="btn-new">+ New session</button>
    <div class="rail-sessions">
      <h2>Sessions</h2>
      ${s.conversations
        .map(
          (c) => `
        <button type="button" class="session ${c.id === s.conversationId ? 'on' : ''} ${s.newSessionIds.includes(c.id) ? 'new' : ''}" data-session="${c.id}">
          <div class="title">${c.title || 'Session'} · ${c.mode || 'council'}${s.newSessionIds.includes(c.id) ? ' <span class="new-badge">new</span>' : ''}</div>
          <div class="meta">${c.message_count} messages</div>
        </button>`
        )
        .join('')}
    </div>
  `;

  els.rail.querySelector('#btn-settings')?.addEventListener('click', () => openSettings());
  els.rail.querySelector('#btn-new')?.addEventListener('click', () => void createSession());
  els.rail.querySelectorAll('[data-session]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = (btn as HTMLElement).dataset.session!;
      const conv = await api.getConversation(id);
      selectConversation(id, conv, { pinned: true });
      resetModelTab();
    });
  });
  els.rail.querySelectorAll('[data-turn]').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectTurn(Number((btn as HTMLElement).dataset.turn));
      resetModelTab();
    });
  });
}

function renderDeck() {
  const s = getState();
  const assistants = assistantMessages(s.conversation);
  const msg = assistants[s.selectedTurnIndex] ?? null;
  const isLast = s.selectedTurnIndex === assistants.length - 1;
  const pendingSelected = isPendingTurnSelected(
    s.selectedTurnIndex,
    assistants.length,
    s.pendingTurn
  );
  const running = (s.isRunning && isLast) || pendingSelected;
  const complete = !!msg?.stage3?.response;
  const turnCtx = buildTurnContext(s.conversation, msg, s.selectedTurnIndex);
  const statusLabel = running ? 'running' : complete ? 'complete' : 'idle';
  const now = s.runtimeTick || Date.now();
  const runtimeForTurn =
    s.turnRuntime?.turnIndex === s.selectedTurnIndex ? s.turnRuntime : null;

  const stepsHtml = TIMELINE.map(({ id, label }) => {
    let cls = 'step-btn';
    if (s.deckView === id) cls += ' on';
    if (id === 'context' && turnCtx.contextChunkCount > 0) cls += ' done';
    else if (running) {
      if (id === 'answers' && msg?.stage1?.length) cls += ' done';
      else if (id === 'rankings' && msg?.loading?.stage2) cls += ' live';
      else if (id === 'rankings' && msg?.stage2?.length) cls += ' done';
      else if (id === 'verdict' && msg?.loading?.stage3) cls += ' live';
    } else if (id === 'quality' && (msg?.metadata?.model_failures as unknown[] | undefined)?.length) {
      cls += ' done';
    } else if (complete && id !== 'context' && id !== 'quality') {
      cls += ' done';
    }
    const timer =
      running && id !== 'context' && id !== 'quality'
        ? timelineStepTimer(runtimeForTurn, id, now)
        : '';
    return `<button type="button" class="${cls}" data-deck-view="${id}">${label}${timer}</button>`;
  }).join('');

  const turnStrip = assistants
    .map(
      (_, i) =>
        `<button type="button" class="turn-chip ${i === s.selectedTurnIndex ? 'on' : ''}" data-turn-chip="${i}">Turn ${i + 1}</button>`
    )
    .join('');

  const bc = buildBreadcrumb(turnCtx, s.selectedTurnIndex, statusLabel);
  const userQuery = userQueryBefore(s.conversation?.messages || [], s.selectedTurnIndex);
  const bannerQuery = userQuery || s.pendingTurn?.userQuery || '';
  const totalElapsed =
    running && runtimeForTurn ? formatDuration(totalElapsedMs(runtimeForTurn, now)) : '';
  const runningBanner =
    running && bannerQuery
      ? `<div class="running-banner">
          <span class="running-badge">Turn ${s.selectedTurnIndex + 1} running${totalElapsed ? ` · ${totalElapsed}` : ''}</span>
          <p class="running-query">${bannerQuery.replace(/</g, '&lt;')}</p>
          ${s.modeProgress.label ? `<p class="meta">${s.modeProgress.label}${s.modeProgress.activeModel ? ` · ${String(s.modeProgress.activeModel).split('/').pop()}` : ''}</p>` : ''}
          ${pendingSelected ? '<p class="meta">External agent run — polling for completion</p>' : ''}
        </div>`
      : '';

  els.deck.innerHTML = `
    <div class="hdr breadcrumb">${bc}
      ${running && s.modeProgress.total ? ` · step ${s.modeProgress.current}/${s.modeProgress.total}` : ''}
    </div>
    ${runningBanner}
    ${assistants.length > 1 ? `<div class="turn-strip">${turnStrip}</div>` : ''}
    <div class="timeline">${stepsHtml}</div>
    <div class="viewport" id="viewport"></div>
  `;

  els.deck.querySelectorAll('[data-deck-view]').forEach((btn) => {
    btn.addEventListener('click', () => {
      setDeckView((btn as HTMLElement).dataset.deckView as DeckView);
      resetModelTab();
    });
  });
  els.deck.querySelectorAll('[data-turn-chip]').forEach((btn) => {
    btn.addEventListener('click', () => {
      selectTurn(Number((btn as HTMLElement).dataset.turnChip));
      resetModelTab();
    });
  });
  els.deck.querySelectorAll('[data-bc-context]').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      setDeckView('context');
      resetModelTab();
    });
  });
  els.deck.querySelectorAll('[data-bc-quality]').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      setDeckView('quality');
    });
  });

  const vp = els.deck.querySelector('#viewport') as HTMLElement;
  renderDeckViewport(
    vp,
    s.deckView,
    s.conversation,
    msg,
    s.selectedTurnIndex,
    running,
    s.pendingTurn,
    s.activeAgentTurn,
    s.modeProgress,
    s.turnRuntime,
    now
  );
}

function renderInspectorPanel() {
  const s = getState();
  const msg = assistantMessages(s.conversation)[s.selectedTurnIndex];
  renderInspector(els.inspector, msg, s.selectedTurnIndex, s.conversation?.mode || 'council');
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
  const on = s.deckView === 'verdict' ? ' on' : '';
  els.verdict.className = `verdict-lane clickable${on}`;
  const excerpt = text.length > 400 ? `${text.slice(0, 400)}…` : text;
  els.verdict.innerHTML = `<button type="button" class="verdict-hit" id="verdict-hit"><span class="label">Verdict</span><div class="body">${excerpt.replace(/</g, '&lt;')}</div><span class="insp-hint">Open full synthesis →</span></button>`;
  els.verdict.querySelector('#verdict-hit')?.addEventListener('click', () => setDeckView('verdict'));
}

function renderFoot() {
  const s = getState();
  const external = s.pendingTurn && !s.isRunning;
  const note = s.isRunning
    ? 'Arena running — see your message in the banner above · Answers tab updates live'
    : external
      ? 'External deliberation in progress — deck refreshes every few seconds'
      : s.takeControl
        ? 'You are driving — Run turn sends the next message'
        : 'Turn complete · Take control to send another';

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
  setDeckView('answers');
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
  selectConversation(conv.id, full, { pinned: true });
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