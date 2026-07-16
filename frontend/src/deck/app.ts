import { api } from './api';
import { escapeHtml } from './escape';
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
  receiveSessionPage,
  setDeckView,
  setSessionQuery,
  setSessionsError,
  setSessionsLoading,
  setTheme,
  setWorkspaceView,
  subscribe,
} from './store';
import type { DeckView } from './types';
import { startLivePoll } from './live-poll';
import { formatDuration, timelineStepTimer, totalElapsedMs } from './runtime';
import { syncRuntimeClock } from './runtime-clock';
import { isSynthesisFailed } from './synthesis';
import { isPendingTurnSelected } from './turns';
import { runTurnStream } from './stream';
import { resetModelTab } from './viewers/council';
import { renderDeckViewport } from './viewers/deck';
import { parseDeckLocation, pushDeckLocation, replaceDeckLocation } from './session-url';
import { renderSessionsPage } from './sessions-view';
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
let locationReady = false;
let pushNextLocation = false;
let locationSuspended = false;

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
    else if (scope === 'background') renderPreservingScroll();
    else render();
  });
  window.addEventListener('popstate', () => void applyBrowserLocation());
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
  const target = parseDeckLocation(window.location.search);
  patch({ workspaceView: target.page });
  await loadSessionPage(false);
  const firstId = target.conversationId || getState().sessions[0]?.id;
  if (firstId) {
    try {
      await openConversation(firstId, {
        pinned: Boolean(target.conversationId),
        turnIndex: target.turnIndex,
        deckView: target.deckView,
        preservePage: target.page === 'sessions',
      });
    } catch {
      const fallback = getState().sessions[0]?.id;
      if (fallback && fallback !== firstId) await openConversation(fallback, { preservePage: target.page === 'sessions' });
    }
  }
  setWorkspaceView(target.page);
  locationReady = true;
  render();
  startLivePoll();
  syncRuntimeClock();
}

async function refreshConversations() {
  await loadSessionPage(false);
  const { conversationId } = getState();
  if (conversationId) {
    const conv = await api.getConversation(conversationId);
    selectConversation(conversationId, conv, { pinned: getState().sessionPinned });
  } else if (getState().sessions.length) {
    const first = getState().sessions[0];
    const conv = await api.getConversation(first.id);
    selectConversation(first.id, conv);
  }
}

async function loadSessionPage(append: boolean) {
  const s = getState();
  if (s.sessionsLoading || (append && !s.sessionNextCursor)) return;
  setSessionsLoading(true);
  try {
    const page = await api.listSessions({
      limit: 50,
      cursor: append ? s.sessionNextCursor : null,
      filters: s.sessionFilters,
      sort: s.sessionSort,
    });
    receiveSessionPage(
      page.items || [],
      page.facets || { modes: [], callers: [], origins: [], statuses: [], qualities: [], squads: [] },
      page.next_cursor || null,
      Number(page.total || 0),
      append,
    );
  } catch (error) {
    setSessionsError(error instanceof Error ? error.message : 'Failed to load sessions');
  }
}

async function openConversation(
  id: string,
  options: {
    pinned?: boolean;
    turnIndex?: number | null;
    deckView?: DeckView | null;
    preservePage?: boolean;
    pushHistory?: boolean;
  } = {},
) {
  const conv = await api.getConversation(id);
  locationSuspended = true;
  try {
    selectConversation(id, conv, { pinned: options.pinned ?? true });
    const assistants = assistantMessages(getState().conversation);
    if (options.turnIndex != null && assistants.length) {
      selectTurn(Math.min(options.turnIndex, assistants.length - 1));
    }
    if (options.deckView) setDeckView(options.deckView);
    if (!options.preservePage) setWorkspaceView('turns');
    resetModelTab();
  } finally {
    locationSuspended = false;
  }
  if (options.pushHistory) pushNextLocation = true;
  render();
}

async function applyBrowserLocation() {
  const target = parseDeckLocation(window.location.search);
  if (target.page === 'sessions') {
    setWorkspaceView('sessions');
    return;
  }
  if (target.conversationId) {
    await openConversation(target.conversationId, {
      pinned: true,
      turnIndex: target.turnIndex,
      deckView: target.deckView,
    });
  } else {
    setWorkspaceView('turns');
  }
}

function render() {
  const sessionsPage = getState().workspaceView === 'sessions';
  document.querySelector('.observatory')?.classList.toggle('sessions-page', sessionsPage);
  renderRail();
  if (sessionsPage) {
    renderSessions();
    els.inspector.innerHTML = '';
    els.verdict.innerHTML = '';
    els.foot.innerHTML = '';
  } else {
    renderDeck();
    renderInspectorPanel();
    renderVerdict();
    renderFoot();
  }
  if (locationReady && !locationSuspended) {
    if (pushNextLocation) pushDeckLocation(getState());
    else replaceDeckLocation(getState());
    pushNextLocation = false;
  }
}

function renderPreservingScroll() {
  const scroll = {
    viewport: (els.deck.querySelector('#viewport') as HTMLElement | null)?.scrollTop ?? 0,
    sessions: (els.deck.querySelector('.sessions-table-scroll') as HTMLElement | null)?.scrollTop ?? 0,
    railTurns: (els.rail.querySelector('.rail-turns') as HTMLElement | null)?.scrollTop ?? 0,
    railSessions: (els.rail.querySelector('.rail-sessions') as HTMLElement | null)?.scrollTop ?? 0,
    inspector: (els.inspector.querySelector('.insp-body.on') as HTMLElement | null)?.scrollTop ?? 0,
    verdict: els.verdict.scrollTop,
  };
  render();
  const viewport = els.deck.querySelector('#viewport') as HTMLElement | null;
  const sessions = els.deck.querySelector('.sessions-table-scroll') as HTMLElement | null;
  const railTurns = els.rail.querySelector('.rail-turns') as HTMLElement | null;
  const railSessions = els.rail.querySelector('.rail-sessions') as HTMLElement | null;
  const inspector = els.inspector.querySelector('.insp-body.on') as HTMLElement | null;
  if (viewport) viewport.scrollTop = scroll.viewport;
  if (sessions) sessions.scrollTop = scroll.sessions;
  if (railTurns) railTurns.scrollTop = scroll.railTurns;
  if (railSessions) railSessions.scrollTop = scroll.railSessions;
  if (inspector) inspector.scrollTop = scroll.inspector;
  els.verdict.scrollTop = scroll.verdict;
}

function renderViewportOnly() {
  if (getState().workspaceView === 'sessions') {
    renderSessions();
    return;
  }
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
      const status = s.isRunning && isLast ? 'running' : isSynthesisFailed(msg) ? 'failed' : msg.stage3?.response ? 'complete' : 'idle';
      const cost = turnCostFromMessage(msg);
      const query = userQueryBefore(messages, i);
      const queryPreview = query ? query.slice(0, 48) + (query.length > 48 ? '…' : '') : '';
      const meta =
        status === 'running'
          ? `<span style="color:var(--accent)">● running</span>`
          : status === 'failed'
            ? `<span class="meta" style="color:var(--warn,#e6a23c)">✗ chairman failed</span>`
            : status === 'complete'
              ? `<span class="meta" style="color:var(--ok)">✓ complete</span>`
              : `<span class="meta">pending</span>`;
      return `
        <button type="button" class="turn-item ${status === 'complete' ? 'complete' : ''} ${i === s.selectedTurnIndex ? 'on' : ''}" data-turn="${i}">
          <span class="turn-number">${i + 1}</span>
          <span class="turn-card-body">
            <span class="turn-query">${queryPreview ? escapeHtml(queryPreview) : 'Untitled turn'}</span>
            <span class="turn-card-meta">${meta}${status === 'complete' ? ` · ${formatUsd(cost.cost_usd)} · ${cost.total_tokens.toLocaleString()} tok` : ''}</span>
            <span class="turn-stage-track" aria-label="Turn stage progress">
              <i class="done"></i><i class="${msg.stage2?.length ? 'done' : ''}"></i><i class="${msg.stage3?.response ? 'done' : ''}"></i>
            </span>
          </span>
        </button>`;
    })
    .join('');

  const pending = s.pendingTurn;
  const pendingHtml =
    pending && isPendingTurnSelected(pending.turnIndex, assistants.length, pending)
      ? `
        <button type="button" class="turn-item on running" data-turn="${pending.turnIndex}">
          <span class="turn-number">${pending.turnIndex + 1}</span><span class="turn-card-body"><span class="turn-query">${escapeHtml(pending.userQuery.slice(0, 40))}${pending.userQuery.length > 40 ? '…' : ''}</span><span class="turn-card-meta"><span style="color:var(--accent)">● running</span> · external${s.turnRuntime?.turnIndex === pending.turnIndex ? ` · ${formatDuration(totalElapsedMs(s.turnRuntime, s.runtimeTick || Date.now()))}` : ''}</span><span class="turn-stage-track"><i class="live"></i><i></i><i></i></span></span>
        </button>`
      : pending
        ? `
        <button type="button" class="turn-item running" data-turn="${pending.turnIndex}">
          <span class="turn-number">${pending.turnIndex + 1}</span><span class="turn-card-body"><span class="turn-query">${escapeHtml(pending.userQuery.slice(0, 40))}${pending.userQuery.length > 40 ? '…' : ''}</span><span class="turn-card-meta"><span style="color:var(--accent)">● running</span> · external${s.turnRuntime?.turnIndex === pending.turnIndex ? ` · ${formatDuration(totalElapsedMs(s.turnRuntime, s.runtimeTick || Date.now()))}` : ''}</span><span class="turn-stage-track"><i class="live"></i><i></i><i></i></span></span>
        </button>`
        : '';

  const turnsHtml = assistantTurnsHtml + pendingHtml;

  const sessionTitle = s.conversation?.title || 'No session';
  const sessionMode = s.conversation?.mode || 'council';
  const pollNote = s.pollError
    ? `<p class="meta poll-err">Live refresh: ${escapeHtml(s.pollError)}</p>`
    : '<p class="meta poll-ok">Live refresh on</p>';

  els.rail.innerHTML = `
    <div class="rail-head">
      <h2>Observatory</h2>
      <button type="button" class="rail-btn" id="btn-settings">⚙</button>
    </div>
    ${pollNote}
    <nav class="workspace-tabs" aria-label="Observatory pages">
      <button type="button" class="workspace-tab ${s.workspaceView === 'turns' ? 'on' : ''}" data-workspace="turns">Turns</button>
      <button type="button" class="workspace-tab ${s.workspaceView === 'sessions' ? 'on' : ''}" data-workspace="sessions">Sessions <span>${s.sessionTotal || s.conversations.length}</span></button>
    </nav>
    <button type="button" class="rail-btn" id="btn-new">+ New session</button>
    ${s.workspaceView === 'turns' ? `<div class="rail-turns">
        <div class="rail-turns-head">
          <h2>Current session</h2>
          <strong>${escapeHtml(sessionTitle)}</strong>
          <span class="meta">${escapeHtml(sessionMode)} · <code>${escapeHtml(s.conversationId || '—')}</code></span>
        </div>
        ${turnsHtml || '<p class="meta">No turns yet — take control to start.</p>'}
      </div>` : `<div class="sessions-rail-note"><strong>Session memory</strong><p>Use the full-width catalog to search, filter, compare cost, and reopen work by conversation ID.</p></div>`}
  `;

  els.rail.querySelector('#btn-settings')?.addEventListener('click', () => openSettings());
  els.rail.querySelector('#btn-new')?.addEventListener('click', () => void createSession());
  els.rail.querySelectorAll('[data-workspace]').forEach((button) => {
    button.addEventListener('click', () => {
      pushNextLocation = true;
      setWorkspaceView((button as HTMLElement).dataset.workspace as 'turns' | 'sessions');
    });
  });
  els.rail.querySelectorAll('[data-turn]').forEach((btn) => {
    btn.addEventListener('click', () => {
      pushNextLocation = true;
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
  const complete = !!msg?.stage3?.response && !isSynthesisFailed(msg);
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
    } else if (
      id === 'quality' &&
      (msg?.metadata?.execution_quality ||
        (msg?.metadata?.model_failures as unknown[] | undefined)?.length ||
        ((msg?.stage1?.length || 0) < ((msg?.metadata?.arena_models as string[] | undefined)?.length || 0)))
    ) {
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
          <p class="running-query">${escapeHtml(bannerQuery)}</p>
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
      pushNextLocation = true;
      setDeckView((btn as HTMLElement).dataset.deckView as DeckView);
      resetModelTab();
    });
  });
  els.deck.querySelectorAll('[data-turn-chip]').forEach((btn) => {
    btn.addEventListener('click', () => {
      pushNextLocation = true;
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

function renderSessions() {
  const s = getState();
  renderSessionsPage(els.deck, s, {
    openSession: (id) => void openConversation(id, { pinned: true, pushHistory: true }),
    changeQuery: (filters, sort) => {
      setSessionQuery(filters, sort);
      void loadSessionPage(false);
    },
    loadMore: () => void loadSessionPage(true),
  });
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
  els.verdict.innerHTML = `<button type="button" class="verdict-hit" id="verdict-hit"><span class="label">Verdict</span><div class="body">${escapeHtml(excerpt)}</div><span class="insp-hint">Open full synthesis →</span></button>`;
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
  await openConversation(conv.id, { pinned: true, pushHistory: true });
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
