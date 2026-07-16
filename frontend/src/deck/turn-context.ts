import { executionTrace, tracePayload, traceStepById } from './execution-trace';
import { userQueryBefore } from './normalize';
import type { AssistantMessage, Conversation, ExecutionTrace, Message, TraceStepStatus } from './types';

export interface RagChunk {
  chunk_id?: string;
  citation?: string;
  source?: string;
  doc_id?: string;
  content?: string;
  score?: number;
  line_start?: number;
  line_end?: number;
  est_tokens?: number;
}

export interface ModelPromptEntry {
  index: number;
  model: string;
  promptPreview: string | null;
  promptFull: string | null;
  contextTokens: number | null;
  stepId: string | null;
  role: string | null;
  kind: string | null;
  status: TraceStepStatus | null;
  ordinal: number | null;
  predecessorStepIds: string[];
  predecessorModel: string | null;
  priorDraft: string | null;
  orchestrationText: string | null;
  parsedRanking: string[];
}

export interface AggregateRankingEntry {
  model: string;
  avgRank: number | null;
  votes: number | null;
  rankPositions: number[];
}

export interface TurnContextSnapshot {
  userQuery: string;
  mode: string;
  squadSize: number;
  respondedCount: number;
  contextChunkCount: number;
  contextTokens: number | null;
  sharedPromptPreview: string | null;
  modelPrompts: ModelPromptEntry[];
  chairPromptPreview: string | null;
  chairPromptFull: string | null;
  chairOrchestrationText: string | null;
  chairPriorDraft: string | null;
  aggregateRankings: AggregateRankingEntry[];
  ragChunks: RagChunk[];
  executionTrace: ExecutionTrace | null;
}

export function ragChunksFromMessage(msg: AssistantMessage | null): RagChunk[] {
  if (!msg) return [];
  const raw = msg.contextSources;
  if (!Array.isArray(raw)) return [];
  return raw as RagChunk[];
}

function modelPromptsFromStage1(stage1: AssistantMessage['stage1']): ModelPromptEntry[] {
  return (stage1 || []).map((r, index) => {
    const row = r as {
      model?: string;
      prompt_preview?: string;
      prompt_full?: string;
      context_tokens?: number;
      response?: string;
    };
    return {
      index,
      model: row.model || `model-${index + 1}`,
      promptPreview: row.prompt_preview ?? null,
      promptFull: row.prompt_full ?? null,
      contextTokens: row.context_tokens ?? null,
      stepId: null,
      role: row.model ? 'answer' : null,
      kind: 'answer',
      status: row.response ? 'succeeded' : null,
      ordinal: index + 1,
      predecessorStepIds: [],
      predecessorModel: null,
      priorDraft: null,
      orchestrationText: null,
      parsedRanking: [],
    };
  });
}

function modelPromptsFromTrace(msg: AssistantMessage, mode: string, trace: ExecutionTrace): ModelPromptEntry[] {
  const relevant = trace.steps.filter((node) => {
    if (node.terminal) return false;
    if (mode === 'council' || mode === 'baseline') return node.kind === 'answer' || node.kind === 'ranking';
    return true;
  });
  return relevant.map((node, index) => {
    const payload = tracePayload(msg, node);
    const predecessor = node.predecessor_step_ids.length
      ? traceStepById(trace, node.predecessor_step_ids[node.predecessor_step_ids.length - 1])
      : null;
    return {
      index,
      model: node.model || `model-${index + 1}`,
      promptPreview: payload?.prompt_preview ?? null,
      promptFull: payload?.prompt_full ?? null,
      contextTokens: payload?.context_tokens ?? null,
      stepId: node.step_id,
      role: node.role,
      kind: node.kind,
      status: node.status,
      ordinal: node.ordinal,
      predecessorStepIds: node.predecessor_step_ids,
      predecessorModel: predecessor?.model || null,
      priorDraft: typeof payload?.prior_draft === 'string' ? payload.prior_draft : null,
      orchestrationText:
        typeof payload?.orchestration_text === 'string'
          ? payload.orchestration_text
          : typeof payload?.turn_instruction === 'string'
            ? payload.turn_instruction
            : null,
      parsedRanking: Array.isArray(payload?.parsed_ranking)
        ? payload.parsed_ranking.map(String)
        : [],
    };
  });
}

export function buildTurnContext(
  conversation: Conversation | null,
  msg: AssistantMessage | null,
  turnIndex: number
): TurnContextSnapshot {
  const messages: Message[] = conversation?.messages || [];
  const meta = msg?.metadata || {};
  const arenaModels = (meta.arena_models as string[]) || [];
  const stage1 = msg?.stage1 || [];
  const mode = String(meta.mode || conversation?.mode || 'council');
  const trace = executionTrace(msg || undefined, mode);
  const tracedPrompts = msg && trace ? modelPromptsFromTrace(msg, mode, trace) : [];
  const modelPrompts = tracedPrompts.length ? tracedPrompts : modelPromptsFromStage1(stage1);
  const first = modelPrompts[0];
  const chunks = ragChunksFromMessage(msg);
  const stage3 = msg?.stage3 as {
    prompt_preview?: string;
    prompt_full?: string;
    orchestration_text?: string;
    prior_draft?: string;
  } | null | undefined;
  const chairPreview = stage3?.prompt_preview ?? null;
  const chairFull = stage3?.prompt_full ?? null;
  const chairOrchestration = stage3?.orchestration_text ?? null;
  const chairPriorDraft = stage3?.prior_draft ?? null;
  const sharedPreview = first?.promptPreview ?? null;
  const aggregateRankings = Array.isArray(meta.aggregate_rankings)
    ? (meta.aggregate_rankings as Array<Record<string, unknown>>).map((row) => ({
        model: String(row.model || ''),
        avgRank:
          typeof row.avg_rank === 'number'
            ? row.avg_rank
            : typeof row.average_rank === 'number'
              ? row.average_rank
              : null,
        votes: typeof row.votes === 'number' ? row.votes : null,
        rankPositions: Array.isArray(row.rank_positions) ? row.rank_positions.map(Number) : [],
      }))
    : [];

  return {
    userQuery: userQueryBefore(messages, turnIndex),
    mode,
    squadSize: arenaModels.length || Math.max(stage1.length, modelPrompts.length),
    respondedCount: trace?.summary.participant_succeeded ?? stage1.length,
    contextChunkCount: chunks.length,
    contextTokens: first?.contextTokens ?? null,
    sharedPromptPreview: sharedPreview,
    modelPrompts,
    chairPromptPreview: chairPreview,
    chairPromptFull: chairFull,
    chairOrchestrationText: chairOrchestration,
    chairPriorDraft,
    aggregateRankings,
    ragChunks: chunks,
    executionTrace: trace,
  };
}

export function chunkKey(chunk: RagChunk, index: number): string {
  return chunk.chunk_id || chunk.citation || chunk.source || `chunk-${index}`;
}

export function activePromptForModel(
  ctx: TurnContextSnapshot,
  modelIndex: number,
  showFull: boolean
): { label: string; text: string | null } {
  const idx = modelIndex < 0 ? 0 : modelIndex;
  const entry = ctx.modelPrompts[idx];
  if (!entry) {
    return { label: 'Shared prompt', text: ctx.sharedPromptPreview };
  }
  const short = entry.model.split('/').pop() || entry.model;
  const text = showFull ? entry.promptFull || entry.promptPreview : entry.promptPreview;
  return {
    label: ctx.modelPrompts.length > 1 ? `${short} (model ${idx + 1})` : 'Shared prompt',
    text,
  };
}
