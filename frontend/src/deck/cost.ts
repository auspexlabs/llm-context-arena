import { traceRows } from './execution-trace';
import type { AssistantMessage } from './types';

export function turnCostFromMessage(msg: AssistantMessage) {
  const meta = msg.metadata || {};
  const cost = meta.cost as Record<string, number> | undefined;
  if (cost) {
    return {
      cost_usd: Number(cost.turn_cost_usd) || 0,
      total_tokens: Number(cost.total_tokens) || 0,
    };
  }
  const mode = String(meta.mode || 'council');
  const steps = traceRows(msg, mode)
    .flatMap((row) => (row.payload ? [row.payload] : []));
  let costUsd = 0;
  let totalTokens = 0;
  for (const step of steps) {
    costUsd += Number(step.cost_usd) || 0;
    totalTokens +=
      (Number(step.prompt_tokens) || 0) + (Number(step.completion_tokens) || 0);
  }
  return { cost_usd: costUsd, total_tokens: totalTokens };
}

export function formatUsd(n: number) {
  if (!n) return '$0.00';
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}
