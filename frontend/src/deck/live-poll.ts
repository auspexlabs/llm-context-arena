import { api } from './api';
import { normalizeConversation } from './normalize';
import { createTurnRuntime, runtimeFromAgentTurn } from './runtime';
import { syncRuntimeClock } from './runtime-clock';
import {
  agentTurnProgress,
  detectPendingTurn,
  findActiveAgentTurn,
} from './turns';
import type { AgentTurnSnapshot, ConversationSummary } from './types';
import {
  getState,
  patch,
  selectConversation,
  setModeProgress,
  updateConversations,
} from './store';

const POLL_MS = 4000;
let timer: ReturnType<typeof setInterval> | null = null;
let knownIds = new Set<string>();
let bootstrapped = false;

function markNewSessions(convs: ConversationSummary[]): string[] {
  const fresh: string[] = [];
  for (const c of convs) {
    if (!knownIds.has(c.id)) fresh.push(c.id);
    knownIds.add(c.id);
  }
  return fresh;
}

async function pollConversation(id: string) {
  const [conv, turnPayload] = await Promise.all([
    api.getConversation(id),
    api.listTurns(id).catch(() => ({ turns: [] as AgentTurnSnapshot[] })),
  ]);
  const normalized = normalizeConversation(conv);
  const turns = (turnPayload.turns || []) as AgentTurnSnapshot[];
  const activeTurn = findActiveAgentTurn(turns);
  const pending = detectPendingTurn(normalized);
  const { isRunning, selectedTurnIndex, turnRuntime } = getState();

  const externalRunning = !!pending && !isRunning;
  if (externalRunning) {
    const prog = activeTurn
      ? agentTurnProgress(activeTurn)
      : { current: 0, total: 3, label: 'Council deliberation' };
    setModeProgress({ ...prog, state: 'poll' });
  } else if (!isRunning && getState().modeProgress.state === 'poll') {
    setModeProgress({ current: 0, total: 0, label: '' });
  }

  const assistants = normalized.messages.filter((m) => m.role === 'assistant').length;
  let turnIdx = selectedTurnIndex;
  if (pending && selectedTurnIndex >= assistants) {
    turnIdx = pending.turnIndex;
  } else if (assistants > 0) {
    turnIdx = Math.min(selectedTurnIndex, assistants - 1);
  }

  let runtime = turnRuntime;
  if (pending && !isRunning) {
    const pIdx = pending.turnIndex;
    if (!runtime || runtime.turnIndex !== pIdx) {
      runtime = createTurnRuntime(pIdx);
    }
    runtime = runtimeFromAgentTurn(runtime, pIdx, activeTurn) ?? runtime;
  } else if (!pending && !isRunning) {
    runtime = null;
  }

  patch({
    conversation: normalized,
    selectedTurnIndex: turnIdx,
    activeAgentTurn: activeTurn,
    pendingTurn: pending
      ? { ...pending, startedAt: pending.startedAt ?? runtime?.startedAt }
      : null,
    turnRuntime: runtime,
    pollError: null,
  });
  syncRuntimeClock();

  return { pending, activeTurn, assistants };
}

async function tick() {
  try {
    const convs = await api.listConversations();
    updateConversations(convs);

    let fresh: string[] = [];
    if (!bootstrapped) {
      convs.forEach((c: ConversationSummary) => knownIds.add(c.id));
      bootstrapped = true;
    } else {
      fresh = markNewSessions(convs);
    }
    if (fresh.length) {
      const prev = getState().newSessionIds;
      patch({ newSessionIds: [...new Set([...prev, ...fresh])] });
      const newest = fresh[0];
      if (!getState().sessionPinned && newest) {
        const conv = await api.getConversation(newest);
        selectConversation(newest, conv);
        patch({ newSessionIds: [newest] });
      }
    }

    const { conversationId } = getState();
    if (conversationId) {
      const { pending, assistants } = await pollConversation(conversationId);
      if (!pending && assistants > 0) {
        const ids = getState().newSessionIds.filter((id) => id !== conversationId);
        if (ids.length !== getState().newSessionIds.length) {
          patch({ newSessionIds: ids });
        }
      }
    }
  } catch (e) {
    patch({ pollError: e instanceof Error ? e.message : 'Poll failed' });
  }
}

export function startLivePoll() {
  if (timer) return;
  void tick();
  timer = setInterval(() => void tick(), POLL_MS);
}

export function stopLivePoll() {
  if (timer) clearInterval(timer);
  timer = null;
}

export function resetPollBaseline() {
  knownIds = new Set();
  bootstrapped = false;
}