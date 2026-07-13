import { userQueryBefore } from './normalize';
import type { AssistantMessage, Conversation, Message } from './types';

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
  ragChunks: RagChunk[];
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
    };
    return {
      index,
      model: row.model || `model-${index + 1}`,
      promptPreview: row.prompt_preview ?? null,
      promptFull: row.prompt_full ?? null,
      contextTokens: row.context_tokens ?? null,
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
  const modelPrompts = modelPromptsFromStage1(stage1);
  const first = modelPrompts[0];
  const chunks = ragChunksFromMessage(msg);
  const stage3 = msg?.stage3 as { prompt_preview?: string; prompt_full?: string } | null | undefined;
  const chairPreview = stage3?.prompt_preview ?? null;
  const chairFull = stage3?.prompt_full ?? null;
  const sharedPreview = first?.promptPreview ?? null;

  return {
    userQuery: userQueryBefore(messages, turnIndex),
    mode: String(meta.mode || conversation?.mode || 'council'),
    squadSize: arenaModels.length || Math.max(stage1.length, modelPrompts.length),
    respondedCount: stage1.length,
    contextChunkCount: chunks.length,
    contextTokens: first?.contextTokens ?? null,
    sharedPromptPreview: sharedPreview,
    modelPrompts,
    chairPromptPreview: chairPreview,
    chairPromptFull: chairFull,
    ragChunks: chunks,
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