import type { AgentTurnSnapshot, Conversation, PendingTurn } from './types';

function assistantCount(conv: Conversation): number {
  return conv.messages.filter((m) => m.role === 'assistant').length;
}

const ACTIVE_TURN_STATUSES = new Set([
  'pending',
  'stage1_complete',
  'stage2_complete',
  'await_user',
]);

const STAGE_LABELS: Record<string, string> = {
  stage1: 'Stage 1 · Answers',
  stage2: 'Stage 2 · Rankings',
  stage3: 'Stage 3 · Verdict',
  resume: 'Awaiting resume',
};

/** Orphan trailing user message — MCP send_message persists user first, assistant when done. */
export function detectPendingTurn(conv: Conversation | null): PendingTurn | null {
  if (!conv?.messages?.length) return null;
  const nAssistants = assistantCount(conv);
  const users = conv.messages.filter((m) => m.role === 'user');
  if (users.length <= nAssistants) return null;
  const last = conv.messages[conv.messages.length - 1];
  if (last.role !== 'user') return null;
  return {
    turnIndex: nAssistants,
    userQuery: last.content,
    source: 'external',
  };
}

export function findActiveAgentTurn(turns: AgentTurnSnapshot[]): AgentTurnSnapshot | null {
  return turns.find((t) => ACTIVE_TURN_STATUSES.has(t.status)) ?? null;
}

export function agentTurnProgress(turn: AgentTurnSnapshot | null): {
  current: number;
  total: number;
  label: string;
} {
  if (!turn) return { current: 0, total: 3, label: 'Deliberation' };
  const total = turn.step_total || 3;
  let current = turn.step_index;
  if (turn.status === 'pending') current = 0;
  else if (turn.status === 'stage1_complete') current = 1;
  else if (turn.status === 'stage2_complete') current = 2;
  else if (turn.status === 'complete') current = total;

  const label =
    STAGE_LABELS[turn.next_step || ''] ||
    (turn.status === 'pending' ? 'Stage 1 · Answers' : turn.status.replace(/_/g, ' '));

  return { current, total, label };
}

export function isPendingTurnSelected(
  selectedTurnIndex: number,
  assistantCount: number,
  pending: PendingTurn | null
): boolean {
  return !!pending && selectedTurnIndex === pending.turnIndex && selectedTurnIndex >= assistantCount;
}