import { escapeHtml } from './escape';
import { formatUsd } from './cost';
import { formatDuration } from './runtime';
import { absoluteSessionUrl, sessionHref } from './session-url';
import type { DeckState, SessionFilters, SessionSummary } from './types';

export interface SessionViewActions {
  openSession: (id: string) => void;
  changeQuery: (filters: SessionFilters, sort: DeckState['sessionSort']) => void;
  loadMore: () => void;
}

let localSearch = '';
let observer: IntersectionObserver | null = null;

function formatDate(value: string | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

function shortModel(value: string): string {
  return value.split('/').pop() || value;
}

function filterText(session: SessionSummary): string {
  return [
    session.id,
    session.title,
    session.last_caller,
    session.originator,
    session.origin,
    session.mode,
    session.squad_name,
    session.repository,
    session.status,
    session.latest_quality,
  ]
    .join(' ')
    .toLocaleLowerCase();
}

function sessionRow(session: SessionSummary): string {
  const href = sessionHref(session.id);
  const quality = session.latest_quality === 'unknown' ? '' : session.latest_quality;
  const statusTone = ['failed', 'degraded'].includes(session.status) ? 'bad' : session.status;
  const models = session.arena_models.length
    ? `${session.arena_models.length} models${session.chairman_model ? ` + ${shortModel(session.chairman_model)} chair` : ''}`
    : 'Squad not recorded';
  const repository = session.repository
    ? `<span class="session-cell-sub" title="${escapeHtml(session.repository)}">${escapeHtml(session.repository.split('/').filter(Boolean).pop() || session.repository)}</span>`
    : '';
  return `<tr data-session-row data-search="${escapeHtml(filterText(session))}">
    <td class="session-title-cell">
      <a class="session-title-link" href="${href}" data-open-session="${escapeHtml(session.id)}">${escapeHtml(session.title || 'New Conversation')}</a>
      <span class="session-id-line">
        <a href="${href}" data-open-session="${escapeHtml(session.id)}"><code>${escapeHtml(session.id)}</code></a>
        <button type="button" class="session-copy" data-copy-id="${escapeHtml(session.id)}">Copy ID</button>
        <button type="button" class="session-copy" data-copy-link="${escapeHtml(session.id)}">Copy link</button>
      </span>
      ${repository}
    </td>
    <td>
      <time datetime="${escapeHtml(session.updated_at)}">${escapeHtml(formatDate(session.updated_at))}</time>
      <span class="session-cell-sub">Created ${escapeHtml(formatDate(session.created_at))}</span>
    </td>
    <td>
      <strong>${escapeHtml(session.last_caller || 'unknown')}</strong>
      <span class="session-cell-sub">${escapeHtml(session.origin || 'unknown')} · started by ${escapeHtml(session.originator || 'unknown')}</span>
    </td>
    <td>
      <strong>${escapeHtml(session.mode || 'council')}</strong>
      <span class="session-cell-sub">${escapeHtml(session.squad_name || models)}</span>
    </td>
    <td class="session-number-cell">
      <strong>${session.turn_count.toLocaleString()}</strong>
      <span class="session-cell-sub">${session.message_count.toLocaleString()} messages</span>
    </td>
    <td>
      <span class="session-status tone-${escapeHtml(statusTone)}">${escapeHtml(session.status)}</span>
      ${quality ? `<span class="session-cell-sub">Quality: ${escapeHtml(quality)}</span>` : ''}
      ${session.failure_count ? `<span class="session-cell-sub tone-bad">${session.failure_count} model failure${session.failure_count === 1 ? '' : 's'}</span>` : ''}
      ${session.duration_ms ? `<span class="session-cell-sub">${escapeHtml(formatDuration(session.duration_ms))} execution</span>` : ''}
    </td>
    <td class="session-number-cell">
      <strong>${formatUsd(session.total_cost_usd)}</strong>
      <span class="session-cell-sub">${session.total_tokens.toLocaleString()} tok · ${session.total_calls.toLocaleString()} calls</span>
    </td>
  </tr>`;
}

function options(values: string[], active: string | undefined, allLabel: string): string {
  return [
    `<option value="">${escapeHtml(allLabel)}</option>`,
    ...values.map(
      (value) => `<option value="${escapeHtml(value)}"${value === active ? ' selected' : ''}>${escapeHtml(value)}</option>`
    ),
  ].join('');
}

function applyLocalFilter(container: HTMLElement): void {
  const query = localSearch.trim().toLocaleLowerCase();
  let matched = 0;
  container.querySelectorAll<HTMLElement>('[data-session-row]').forEach((row) => {
    const visible = !query || (row.dataset.search || '').includes(query);
    row.hidden = !visible;
    if (visible) matched += 1;
  });
  const count = container.querySelector<HTMLElement>('[data-session-match-count]');
  if (count) {
    const loaded = container.querySelectorAll('[data-session-row]').length;
    count.textContent = query
      ? `${matched} matching · ${loaded} loaded`
      : `${loaded} loaded`;
  }
}

async function copyValue(button: HTMLElement, value: string): Promise<void> {
  await navigator.clipboard.writeText(value);
  const previous = button.textContent;
  button.textContent = 'Copied';
  window.setTimeout(() => {
    button.textContent = previous;
  }, 1200);
}

export function renderSessionsPage(
  container: HTMLElement,
  state: DeckState,
  actions: SessionViewActions,
): void {
  observer?.disconnect();
  const filters = state.sessionFilters;
  const activeFilters = Object.values(filters).filter(Boolean).length;
  const rows = state.sessions.map(sessionRow).join('');
  container.innerHTML = `<section class="sessions-page-shell">
    <header class="sessions-page-head">
      <div>
        <p class="session-eyebrow">Observatory memory</p>
        <h1>Sessions</h1>
        <p class="meta">Search what is loaded instantly. Filter controls re-query the catalog.</p>
      </div>
      <div class="sessions-summary">
        <strong>${state.sessionTotal.toLocaleString()}</strong>
        <span>sessions in query</span>
      </div>
    </header>
    <div class="sessions-search-row">
      <label class="sessions-search">
        <span>Search loaded sessions</span>
        <input type="search" value="${escapeHtml(localSearch)}" placeholder="Title, ID, caller, mode, squad, repository…" data-session-search autocomplete="off">
      </label>
      <span class="meta" data-session-match-count>${state.sessions.length} loaded</span>
    </div>
    <div class="session-filters">
      <label>Mode<select data-session-filter="mode">${options(state.sessionFacets.modes, filters.mode, 'All modes')}</select></label>
      <label>Caller<select data-session-filter="caller">${options(state.sessionFacets.callers, filters.caller, 'All callers')}</select></label>
      <label>Status<select data-session-filter="status">${options(state.sessionFacets.statuses, filters.status, 'All statuses')}</select></label>
      <label>Quality<select data-session-filter="quality">${options(state.sessionFacets.qualities, filters.quality, 'All quality')}</select></label>
      <label>Squad<select data-session-filter="squad">${options(state.sessionFacets.squads, filters.squad, 'All squads')}</select></label>
      <label>Sort<select data-session-sort>
        <option value="updated_desc"${state.sessionSort === 'updated_desc' ? ' selected' : ''}>Recent activity</option>
        <option value="created_desc"${state.sessionSort === 'created_desc' ? ' selected' : ''}>Recently created</option>
        <option value="cost_desc"${state.sessionSort === 'cost_desc' ? ' selected' : ''}>Highest cost</option>
      </select></label>
      <button type="button" class="session-filter-clear" data-session-clear${activeFilters ? '' : ' disabled'}>Clear${activeFilters ? ` (${activeFilters})` : ''}</button>
    </div>
    ${state.sessionsError ? `<div class="session-error">${escapeHtml(state.sessionsError)}</div>` : ''}
    <div class="sessions-table-scroll">
      <table class="sessions-table">
        <thead><tr>
          <th>Session</th><th>Activity</th><th>Caller</th><th>Configuration</th><th>Turns</th><th>Outcome</th><th>Cost</th>
        </tr></thead>
        <tbody>${rows || `<tr><td colspan="7" class="sessions-empty">${state.sessionsLoading ? 'Loading sessions…' : 'No sessions match these filters.'}</td></tr>`}</tbody>
      </table>
      <div class="session-load-sentinel" data-session-sentinel>
        ${state.sessionsLoading ? 'Loading more…' : state.sessionNextCursor ? 'Scroll to load more' : state.sessions.length ? 'End of session history' : ''}
      </div>
    </div>
  </section>`;

  const search = container.querySelector<HTMLInputElement>('[data-session-search]');
  search?.addEventListener('input', () => {
    localSearch = search.value;
    applyLocalFilter(container);
  });
  if (search && localSearch) {
    search.setSelectionRange(localSearch.length, localSearch.length);
  }

  container.querySelectorAll<HTMLSelectElement>('[data-session-filter]').forEach((select) => {
    select.addEventListener('change', () => {
      const key = select.dataset.sessionFilter as keyof SessionFilters;
      const next = { ...state.sessionFilters };
      if (select.value) next[key] = select.value;
      else delete next[key];
      actions.changeQuery(next, state.sessionSort);
    });
  });
  container.querySelector<HTMLSelectElement>('[data-session-sort]')?.addEventListener('change', (event) => {
    actions.changeQuery(
      state.sessionFilters,
      (event.currentTarget as HTMLSelectElement).value as DeckState['sessionSort'],
    );
  });
  container.querySelector('[data-session-clear]')?.addEventListener('click', () => {
    actions.changeQuery({}, state.sessionSort);
  });
  container.querySelectorAll<HTMLElement>('[data-open-session]').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      actions.openSession(link.dataset.openSession!);
    });
  });
  container.querySelectorAll<HTMLElement>('[data-copy-id]').forEach((button) => {
    button.addEventListener('click', () => void copyValue(button, button.dataset.copyId!));
  });
  container.querySelectorAll<HTMLElement>('[data-copy-link]').forEach((button) => {
    button.addEventListener('click', () => void copyValue(button, absoluteSessionUrl(button.dataset.copyLink!)));
  });

  const sentinel = container.querySelector<HTMLElement>('[data-session-sentinel]');
  if (sentinel && state.sessionNextCursor && !state.sessionsLoading) {
    observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) actions.loadMore();
    }, { root: container.querySelector('.sessions-table-scroll'), rootMargin: '240px' });
    observer.observe(sentinel);
  }
  applyLocalFilter(container);
}
