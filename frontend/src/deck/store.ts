import type { AssistantMessage, Conversation, ConversationSummary, CouncilStepId, DeckState, ModeProgress } from './types';

const initial: DeckState = {
  conversations: [],
  conversationId: null,
  conversation: null,
  selectedTurnIndex: 0,
  focusedStep: 'answers',
  takeControl: false,
  isRunning: false,
  modeProgress: { current: 0, total: 0, label: '' },
  theme: 'light',
  settingsOpen: false,
};

let state: DeckState = { ...initial };
const listeners = new Set<() => void>();

export function getState(): DeckState {
  return state;
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function patch(partial: Partial<DeckState>) {
  state = { ...state, ...partial };
  listeners.forEach((fn) => fn());
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

export function turnStatus(msg: AssistantMessage | null, isRunning: boolean, isLast: boolean): 'running' | 'complete' | 'idle' {
  if (!msg) return 'idle';
  if (isRunning && isLast) return 'running';
  if (msg.stage3?.response) return 'complete';
  if (msg.loading?.stage1 || msg.loading?.stage2 || msg.loading?.stage3) return 'running';
  return msg.stage1 ? 'complete' : 'idle';
}

export function setTheme(theme: 'light' | 'dark') {
  document.body.classList.toggle('theme-dark', theme === 'dark');
  patch({ theme });
}

export function setModeProgress(progress: Partial<ModeProgress>) {
  patch({ modeProgress: { ...state.modeProgress, ...progress } });
}

export function setFocusedStep(step: CouncilStepId) {
  patch({ focusedStep: step });
}

export function updateConversations(conversations: ConversationSummary[]) {
  patch({ conversations });
}

export function selectConversation(id: string, conversation: Conversation) {
  const assistants = assistantMessages(conversation);
  patch({
    conversationId: id,
    conversation,
    selectedTurnIndex: Math.max(0, assistants.length - 1),
    focusedStep: 'answers',
    modeProgress: { current: 0, total: 0, label: '' },
  });
}