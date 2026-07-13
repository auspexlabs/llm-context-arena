import type { AssistantMessage, Conversation, Message } from './types';

/** Map persisted API snake_case onto deck message shape. */
export function normalizeAssistantMessage(raw: Record<string, unknown>): AssistantMessage {
  const ctx = raw.contextSources ?? raw.context_sources;
  return {
    role: 'assistant',
    stage1: (raw.stage1 as AssistantMessage['stage1']) ?? null,
    stage2: (raw.stage2 as AssistantMessage['stage2']) ?? null,
    stage3: (raw.stage3 as AssistantMessage['stage3']) ?? null,
    metadata: (raw.metadata as Record<string, unknown>) ?? null,
    contextSources: Array.isArray(ctx) ? ctx : null,
    loading: raw.loading as AssistantMessage['loading'],
  };
}

export function normalizeConversation(raw: Conversation): Conversation {
  return {
    ...raw,
    messages: (raw.messages || []).map((m) =>
      m.role === 'assistant'
        ? normalizeAssistantMessage(m as unknown as Record<string, unknown>)
        : m
    ) as Message[],
  };
}

export function userQueryBefore(
  messages: Message[],
  assistantIndex: number
): string {
  const assistantsSeen = messages.filter((m) => m.role === 'assistant');
  const target = assistantsSeen[assistantIndex];
  if (!target) return '';
  const idx = messages.indexOf(target);
  for (let i = idx - 1; i >= 0; i--) {
    if (messages[i].role === 'user') return (messages[i] as { content: string }).content;
  }
  return '';
}