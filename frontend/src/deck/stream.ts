import { api } from './api';
import type { AssistantMessage, Conversation } from './types';
import { runtimeOnStageComplete, runtimeOnStageStart } from './runtime';
import { syncRuntimeClock } from './runtime-clock';
import { getState, patch, setDeckView, setModeProgress, setTurnRuntime } from './store';

function ensureAssistant(conv: Conversation): AssistantMessage {
  const last = conv.messages[conv.messages.length - 1];
  if (last?.role === 'assistant') return last;
  const assistant: AssistantMessage = {
    role: 'assistant',
    stage1: null,
    stage2: null,
    stage3: null,
    metadata: null,
    loading: { stage1: false, stage2: false, stage3: false },
  };
  conv.messages.push(assistant);
  return assistant;
}

function updateConversation(mutator: (conv: Conversation, assistant: AssistantMessage) => void) {
  const { conversation, conversationId } = getState();
  if (!conversation || !conversationId) return;
  const conv = structuredClone(conversation);
  const assistant = ensureAssistant(conv);
  mutator(conv, assistant);
  patch({ conversation: conv });
}

export async function runTurnStream(
  conversationId: string,
  content: string,
  signal: AbortSignal
): Promise<void> {
  const { conversation } = getState();
  if (!conversation) return;

  const conv = structuredClone(conversation);
  conv.messages.push({ role: 'user', content });
  conv.messages.push({
    role: 'assistant',
    stage1: null,
    stage2: null,
    stage3: null,
    metadata: null,
    loading: { stage1: false, stage2: false, stage3: false },
  });
  const turnIdx = conv.messages.filter((m) => m.role === 'assistant').length - 1;
  setDeckView('answers');
  const startedAt = Date.now();
  patch({
    conversation: conv,
    isRunning: true,
    selectedTurnIndex: turnIdx,
    turnRuntime: runtimeOnStageStart(null, turnIdx, 'stage1', startedAt),
    pendingTurn: null,
  });
  syncRuntimeClock();

  await api.sendMessageStream(
    conversationId,
    content,
    [],
    (eventType: string, event: { data?: unknown; metadata?: Record<string, unknown> }) => {
      switch (eventType) {
        case 'stage1_start': {
          const now = Date.now();
          setTurnRuntime(runtimeOnStageStart(getState().turnRuntime, turnIdx, 'stage1', now));
          updateConversation((_c, a) => {
            a.loading = { ...a.loading, stage1: true };
          });
          break;
        }
        case 'stage1_complete': {
          const now = Date.now();
          setTurnRuntime(runtimeOnStageComplete(getState().turnRuntime, turnIdx, 'stage1', now));
          updateConversation((_c, a) => {
            a.stage1 = event.data as AssistantMessage['stage1'];
            a.metadata = { ...(a.metadata || {}), ...(event.metadata || {}) };
            a.loading = { ...a.loading, stage1: false };
          });
          break;
        }
        case 'stage2_start': {
          const now = Date.now();
          setTurnRuntime(runtimeOnStageStart(getState().turnRuntime, turnIdx, 'stage2', now));
          updateConversation((_c, a) => {
            a.loading = { ...a.loading, stage2: true };
          });
          break;
        }
        case 'stage2_complete': {
          const now = Date.now();
          setTurnRuntime(runtimeOnStageComplete(getState().turnRuntime, turnIdx, 'stage2', now));
          updateConversation((_c, a) => {
            a.stage2 = event.data as AssistantMessage['stage2'];
            a.metadata = { ...(a.metadata || {}), ...(event.metadata || {}) };
            a.loading = { ...a.loading, stage2: false };
          });
          break;
        }
        case 'stage3_start': {
          const now = Date.now();
          setTurnRuntime(runtimeOnStageStart(getState().turnRuntime, turnIdx, 'stage3', now));
          updateConversation((_c, a) => {
            a.loading = { ...a.loading, stage3: true };
          });
          break;
        }
        case 'stage3_complete': {
          const now = Date.now();
          setTurnRuntime(runtimeOnStageComplete(getState().turnRuntime, turnIdx, 'stage3', now));
          updateConversation((_c, a) => {
            a.stage3 = event.data as AssistantMessage['stage3'];
            a.loading = { ...a.loading, stage3: false };
          });
          break;
        }
        case 'execution_complete':
          updateConversation((_c, a) => {
            const d = (event.data || {}) as Record<string, unknown>;
            a.metadata = {
              ...(a.metadata || {}),
              ...(d.steps ? { steps: d.steps } : {}),
              ...(d.cost ? { cost: d.cost } : {}),
              ...(d.model_failures ? { model_failures: d.model_failures } : {}),
              ...(d.execution_quality ? { execution_quality: d.execution_quality } : {}),
              mode: d.mode ?? a.metadata?.mode,
            };
          });
          break;
        case 'context_sources':
          updateConversation((_c, a) => {
            a.contextSources = event.data as unknown[];
          });
          break;
        case 'mode_progress':
        case 'step_complete': {
          const d = (event.data || {}) as Record<string, unknown>;
          setModeProgress({
            current: Number(d.step_index ?? d.completed ?? d.current ?? 0),
            total: Number(d.step_total ?? d.total ?? 0),
            label: String(d.label ?? d.role ?? ''),
            activeModel: (d.active_model ?? d.model) as string | null,
            state: d.state as string | undefined,
          });
          break;
        }
        default:
          break;
      }
    },
    signal
  );

  patch({ isRunning: false });
  syncRuntimeClock();
}