/** Cost helpers — OpenRouter usage surfaced on arena steps/metadata. */

export function sumStepsCost(steps) {
  let costUsd = 0;
  let promptTokens = 0;
  let completionTokens = 0;
  let calls = 0;

  for (const step of steps || []) {
    const cost = Number(step?.cost_usd) || 0;
    const prompt = Number(step?.prompt_tokens) || 0;
    const completion = Number(step?.completion_tokens) || 0;
    if (cost || prompt || completion) calls += 1;
    costUsd += cost;
    promptTokens += prompt;
    completionTokens += completion;
  }

  return {
    cost_usd: costUsd,
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    total_tokens: promptTokens + completionTokens,
    calls,
  };
}

export function turnCostFromMessage(msg) {
  if (!msg || msg.role !== 'assistant') return sumStepsCost([]);
  const meta = msg.metadata || {};
  if (meta.cost) {
    return {
      cost_usd: Number(meta.cost.turn_cost_usd) || 0,
      prompt_tokens: Number(meta.cost.prompt_tokens) || 0,
      completion_tokens: Number(meta.cost.completion_tokens) || 0,
      total_tokens: Number(meta.cost.total_tokens) || 0,
      calls: Number(meta.cost.calls) || 0,
    };
  }
  return sumStepsCost(meta.steps);
}

export function sessionCostFromMessages(messages, liveSteps = [], isLoading = false) {
  const msgs = messages || [];
  let costUsd = 0;
  let promptTokens = 0;
  let completionTokens = 0;
  let calls = 0;
  let turns = 0;

  msgs.forEach((msg, index) => {
    if (msg.role !== 'assistant') return;
    const isCurrent = isLoading && index === msgs.length - 1;
    if (isCurrent) return;
    const turn = turnCostFromMessage(msg);
    costUsd += turn.cost_usd;
    promptTokens += turn.prompt_tokens;
    completionTokens += turn.completion_tokens;
    calls += turn.calls;
    turns += 1;
  });

  if (isLoading && liveSteps.length) {
    const live = sumStepsCost(liveSteps);
    costUsd += live.cost_usd;
    promptTokens += live.prompt_tokens;
    completionTokens += live.completion_tokens;
    calls += live.calls;
  }

  return {
    cost_usd: costUsd,
    prompt_tokens: promptTokens,
    completion_tokens: completionTokens,
    total_tokens: promptTokens + completionTokens,
    calls,
    turns: turns + (isLoading && liveSteps.length ? 1 : 0),
  };
}

export function formatUsd(amount) {
  const value = Number(amount) || 0;
  if (value === 0) return '$0.00';
  if (value < 0.01) return `$${value.toFixed(4)}`;
  if (value < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

export function formatTokenCount(count) {
  const value = Number(count) || 0;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}