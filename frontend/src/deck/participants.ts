import { escapeHtml } from './escape';
import { executionTrace, tracePayload } from './execution-trace';
import type { AssistantMessage } from './types';

interface StepLike {
  model?: string;
  role?: string;
  response?: string;
  ranking?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost_usd?: number;
  duration_ms?: number;
}

export interface ParticipantView {
  model: string;
  short: string;
  provider: string;
  avatar: string;
  hue: number;
  isChair: boolean;
  status: 'pending' | 'ok' | 'warn' | 'failed';
  statusLabel: string;
  roles: string[];
  calls: number;
  tokens: number;
  costUsd: number;
  durationMs: number;
  attemptedSteps: number;
  succeededSteps: number;
  failedSteps: number;
}

export function shortModel(model: string) {
  return model.split('/').pop() || model;
}

function providerOf(model: string) {
  return model.includes('/') ? model.split('/')[0] : 'model';
}

function initials(model: string) {
  const provider = providerOf(model);
  const short = shortModel(model);
  return `${provider[0] || ''}${short[0] || ''}`.toUpperCase();
}

function hueFor(model: string) {
  let hash = 0;
  for (const char of model) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % 360;
}

export function participantViews(
  msg: AssistantMessage | undefined,
  mode: string,
  activeModel?: string | null
): ParticipantView[] {
  const meta = msg?.metadata || {};
  const trace = executionTrace(msg, mode);
  const traceRows = msg && trace
    ? trace.steps.map((node) => ({ node, payload: tracePayload(msg, node) as StepLike | null }))
    : [];
  const arena = [...((meta.arena_models as string[] | undefined) || [])];
  if (!arena.length) {
    for (const row of traceRows) {
      if (row.node.model && !row.node.terminal && !arena.includes(row.node.model)) arena.push(row.node.model);
    }
  }
  const chairman = String(meta.chairman_model || msg?.stage3?.model || '');
  const models = [...arena];
  if (chairman && !models.includes(chairman)) models.push(chairman);

  return models.map((model) => {
    const rows = traceRows.filter((row) => row.node.model === model);
    const failed = rows.filter((row) => row.node.status === 'failed');
    const successful = rows.filter((row) => row.node.status === 'succeeded');
    const isChair = model === chairman;
    let status: ParticipantView['status'] = 'pending';
    let statusLabel = activeModel === model ? 'active now' : 'waiting';
    if (failed.length && !successful.length) {
      status = 'failed';
      statusLabel = `${failed.length} failed stage${failed.length === 1 ? '' : 's'}`;
    } else if (failed.length) {
      status = 'warn';
      statusLabel = `${successful.length} completed · ${failed.length} issue${failed.length === 1 ? '' : 's'}`;
    } else if (successful.length) {
      status = 'ok';
      statusLabel = isChair ? 'synthesis complete' : `${successful.length} stage${successful.length === 1 ? '' : 's'} complete`;
    }
    const roles = [...new Set(rows.map((row) => row.node.role).filter(Boolean))];
    const payloads = rows.map((row) => row.payload).filter((row): row is StepLike => Boolean(row));
    return {
      model,
      short: shortModel(model),
      provider: providerOf(model),
      avatar: initials(model),
      hue: hueFor(model),
      isChair,
      status,
      statusLabel,
      roles,
      calls: payloads.filter((row) =>
        Number(row.total_tokens || row.prompt_tokens || row.completion_tokens || row.cost_usd)
      ).length,
      tokens: payloads.reduce(
        (sum, row) => sum + Number(row.total_tokens || ((row.prompt_tokens || 0) + (row.completion_tokens || 0))),
        0
      ),
      costUsd: payloads.reduce((sum, row) => sum + Number(row.cost_usd || 0), 0),
      durationMs: payloads.reduce((sum, row) => sum + Number(row.duration_ms || 0), 0),
      attemptedSteps: rows.filter((row) => ['succeeded', 'failed'].includes(row.node.status)).length,
      succeededSteps: successful.length,
      failedSteps: failed.length,
    };
  });
}

export function renderAvatar(participant: ParticipantView, compact = false) {
  return `<span class="model-avatar ${compact ? 'compact' : ''} tone-${participant.status}" style="--avatar-hue:${participant.hue}" title="${escapeHtml(participant.model)}">${escapeHtml(participant.avatar)}</span>`;
}
