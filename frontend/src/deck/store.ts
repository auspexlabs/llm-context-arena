import { normalizeConversation } from './normalize';
import { executionSeverity, isSynthesisFailed } from './synthesis';
import type {
  AssistantMessage,
  Conversation,
  ConversationSummary,
  CouncilStepId,
  DeckState,
  DeckView,
  InspectorColumn,
  ModeProgress,
  TurnRuntime,
  SessionFacets,
  SessionFilters,
  SessionSummary,
  WorkspaceView,
} from './types';

const COUNCIL_STEPS: CouncilStepId[] = ['answers', 'rankings', 'verdict'];
export type RenderScope = 'full' | 'viewport' | 'background';

export function defaultDeckView(msg: AssistantMessage | null): DeckView {
  if (!msg) return 'answers';
  if (msg.stage3?.response) return 'verdict';
  if (msg.stage1?.length) return 'answers';
  if (msg.stage2?.length) return 'rankings';
  return 'answers';
}

export function inspectorColumnForView(view: DeckView): InspectorColumn {
  if (view === 'context' || view === 'answers') return 'context';
  if (view === 'rankings') return 'rankings';
  return 'quality';
}

export function councilStepFromView(view: DeckView): CouncilStepId | null {
  return COUNCIL_STEPS.includes(view as CouncilStepId) ? (view as CouncilStepId) : null;
}

const initial: DeckState = {
  workspaceView: 'turns',
  conversations: [],
  sessions: [],
  sessionFacets: {
    modes: [],
    callers: [],
    origins: [],
    statuses: [],
    qualities: [],
    squads: [],
  },
  sessionFilters: {},
  sessionSort: 'updated_desc',
  sessionNextCursor: null,
  sessionTotal: 0,
  sessionsLoading: false,
  sessionsError: null,
  conversationId: null,
  conversation: null,
  selectedTurnIndex: 0,
  focusedStep: 'answers',
  deckView: 'answers',
  inspectorColumn: 'context',
  ragListExpanded: false,
  ragChunksExpanded: [],
  contextPromptModel: -1,
  contextInjectionSelection: null,
  contextAdditivesExpanded: [],
  failuresExpanded: [],
  takeControl: false,
  isRunning: false,
  modeProgress: { current: 0, total: 0, label: '' },
  activeAgentTurn: null,
  pendingTurn: null,
  sessionPinned: false,
  newSessionIds: [],
  pollError: null,
  turnRuntime: null,
  runtimeTick: 0,
  theme: 'light',
  settingsOpen: false,
};

let state: DeckState = { ...initial };

const listeners = new Set<(scope: RenderScope) => void>();

export function getState(): DeckState {
  return state;
}

export function subscribe(fn: (scope?: RenderScope) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function patch(partial: Partial<DeckState>, scope: RenderScope = 'full') {
  state = { ...state, ...partial };
  listeners.forEach((fn) => fn(scope));
}

export function assistantMessages(conv: Conversation | null): AssistantMessage[] {
  if (!conv) return [];
  return conv.messages.filter((m): m is AssistantMessage => m.role === 'assistant');
}

export function selectedAssistant(state: DeckState): AssistantMessage | null {
  const list = assistantMessages(state.conversation);
  if (!list.length) return null;
  const idx = Math.min(state.selectedTurnIndex, list.length - 1);
  return list[idx] ?? null;
}

export function turnStatus(msg: AssistantMessage | null, isRunning: boolean, isLast: boolean): 'running' | 'complete' | 'idle' | 'failed' {
  if (!msg) return 'idle';
  if (isRunning && isLast) return 'running';
  if (isSynthesisFailed(msg) || executionSeverity(msg) === 'failed') return 'failed';
  if (msg.stage3?.response) return 'complete';
  if (msg.loading?.stage1 || msg.loading?.stage2 || msg.loading?.stage3) return 'running';
  return msg.stage1 ? 'complete' : 'idle';
}

export function setTheme(theme: 'light' | 'dark') {
  document.body.classList.toggle('theme-dark', theme === 'dark');
  patch({ theme });
}

export function setModeProgress(progress: Partial<ModeProgress>, scope: RenderScope = 'full') {
  patch({ modeProgress: { ...state.modeProgress, ...progress } }, scope);
}

/** Navigate deck + sync inspector highlight. */
export function setDeckView(view: DeckView) {
  const step = councilStepFromView(view);
  patch({
    deckView: view,
    focusedStep: step ?? state.focusedStep,
    inspectorColumn: inspectorColumnForView(view),
  });
}

/** @deprecated prefer setDeckView */
export function setFocusedStep(step: CouncilStepId) {
  setDeckView(step);
}

export function openInspectorColumn(col: InspectorColumn) {
  const view: DeckView =
    col === 'context' ? 'context' : col === 'rankings' ? 'rankings' : 'quality';
  setDeckView(view);
}

export function toggleRagList() {
  patch({ ragListExpanded: !state.ragListExpanded }, 'viewport');
}

export function toggleRagChunk(key: string) {
  const set = new Set(state.ragChunksExpanded);
  if (set.has(key)) set.delete(key);
  else set.add(key);
  patch({ ragChunksExpanded: [...set] }, 'viewport');
}

function resetTurnUi() {
  return {
    ragListExpanded: false,
    ragChunksExpanded: [] as string[],
    contextPromptModel: -1,
    contextInjectionSelection: null as string | null,
    contextAdditivesExpanded: [] as string[],
    failuresExpanded: [] as string[],
  };
}

export function setContextPromptModel(index: number) {
  const scope = state.deckView === 'context' ? 'viewport' : 'full';
  patch({ contextPromptModel: index, deckView: 'context', inspectorColumn: 'context' }, scope);
}

export function setContextInjectionSelection(key: string | null) {
  patch({ contextInjectionSelection: key }, 'viewport');
}

export function setContextAdditiveExpanded(key: string, open: boolean) {
  const expanded = new Set(state.contextAdditivesExpanded);
  if (expanded.has(key) === open) return;
  if (open) expanded.add(key);
  else expanded.delete(key);
  patch({ contextAdditivesExpanded: [...expanded] }, 'viewport');
}

export function expandAllRag(chunkKeys: string[]) {
  patch({ ragListExpanded: true, ragChunksExpanded: [...chunkKeys] }, 'viewport');
}

export function collapseAllRag() {
  patch({ ragListExpanded: false, ragChunksExpanded: [] }, 'viewport');
}

export function toggleFailureExpand(key: string) {
  const set = new Set(state.failuresExpanded);
  if (set.has(key)) set.delete(key);
  else set.add(key);
  patch({ failuresExpanded: [...set] }, 'viewport');
}

export function updateConversations(
  conversations: ConversationSummary[],
  scope: RenderScope = 'full'
) {
  patch({ conversations }, scope);
}

export function setWorkspaceView(view: WorkspaceView) {
  patch({ workspaceView: view });
}

export function setSessionQuery(filters: SessionFilters, sort = state.sessionSort) {
  patch({
    sessionFilters: filters,
    sessionSort: sort,
    sessions: [],
    sessionNextCursor: null,
    sessionTotal: 0,
    sessionsError: null,
  });
}

export function setSessionsLoading(loading: boolean) {
  patch({ sessionsLoading: loading }, 'background');
}

export function receiveSessionPage(
  items: SessionSummary[],
  facets: SessionFacets,
  nextCursor: string | null,
  total: number,
  append: boolean,
) {
  const merged = append
    ? [...state.sessions, ...items.filter((item) => !state.sessions.some((row) => row.id === item.id))]
    : items;
  patch({
    sessions: merged,
    sessionFacets: facets,
    sessionNextCursor: nextCursor,
    sessionTotal: total,
    sessionsLoading: false,
    sessionsError: null,
    ...(!append ? { conversations: items } : {}),
  });
}

export function refreshSessionHead(
  items: SessionSummary[],
  facets: SessionFacets,
  nextCursor: string | null,
  total: number,
) {
  const headIds = new Set(items.map((item) => item.id));
  const tail = state.sessions.filter((item) => !headIds.has(item.id));
  const merged = [...items, ...tail].slice(0, Math.max(total, items.length));
  patch({
    sessions: merged,
    conversations: items,
    sessionFacets: facets,
    sessionTotal: total,
    sessionNextCursor:
      state.sessions.length > items.length ? state.sessionNextCursor : nextCursor,
    sessionsError: null,
  }, 'background');
}

export function setSessionsError(message: string) {
  patch({ sessionsLoading: false, sessionsError: message });
}

export function selectConversation(id: string, conversation: Conversation, opts?: { pinned?: boolean }) {
  const normalized = normalizeConversation(conversation);
  const assistants = assistantMessages(normalized);
  const users = normalized.messages.filter((m) => m.role === 'user');
  const hasPending = users.length > assistants.length;
  const turnIdx = hasPending ? assistants.length : Math.max(0, assistants.length - 1);
  const view = hasPending ? 'answers' : defaultDeckView(assistants[turnIdx] ?? null);
  patch({
    conversationId: id,
    conversation: normalized,
    selectedTurnIndex: turnIdx,
    deckView: view,
    focusedStep: councilStepFromView(view) ?? 'answers',
    inspectorColumn: inspectorColumnForView(view),
    modeProgress: { current: 0, total: 0, label: '' },
    pendingTurn: hasPending
      ? {
          turnIndex: assistants.length,
          userQuery: (users[users.length - 1] as { content: string }).content,
          source: 'external',
        }
      : null,
    sessionPinned: opts?.pinned ?? false,
    newSessionIds: getState().newSessionIds.filter((sid) => sid !== id),
    turnRuntime: null,
    ...resetTurnUi(),
  });
}

export function setTurnRuntime(runtime: TurnRuntime | null) {
  patch({ turnRuntime: runtime });
}

export function selectTurn(index: number) {
  const assistants = assistantMessages(state.conversation);
  const msg = assistants[index] ?? null;
  const view = defaultDeckView(msg);
  patch({
    selectedTurnIndex: index,
    deckView: view,
    focusedStep: councilStepFromView(view) ?? 'answers',
    inspectorColumn: inspectorColumnForView(view),
    ...resetTurnUi(),
  });
}
