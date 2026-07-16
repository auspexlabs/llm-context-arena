import { formatUsd, turnCostFromMessage } from './cost';
import { escapeHtml } from './escape';
import { traceRows } from './execution-trace';
import { shortModel } from './participants';
import type { AssistantMessage, Conversation, ConversationSummary } from './types';

export type CostSeriesId = 'current' | 'squad' | 'memory';

export interface CostPanelState {
  selected: CostSeriesId[];
  breakdown: boolean;
  topN: number;
}

interface CostPoint {
  label: string;
  value: number;
}

interface CostStep {
  model?: string;
  role?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost_usd?: number;
}

const SERIES: { id: CostSeriesId; label: string }[] = [
  { id: 'current', label: 'Current session' },
  { id: 'squad', label: 'Same squad' },
  { id: 'memory', label: 'Everything in memory' },
];

function assistants(conversation: Conversation | null) {
  return (conversation?.messages || []).filter(
    (message): message is AssistantMessage => message.role === 'assistant'
  );
}

export function squadFingerprint(msg: AssistantMessage | undefined) {
  const meta = msg?.metadata || {};
  const models = [...((meta.arena_models as string[] | undefined) || [])].sort();
  const chairman = String(meta.chairman_model || msg?.stage3?.model || '');
  return models.length || chairman ? `${chairman}::${models.join('|')}` : '';
}

function currentPoints(conversation: Conversation | null): CostPoint[] {
  let cumulative = 0;
  return assistants(conversation).map((message, index) => {
    cumulative += turnCostFromMessage(message).cost_usd;
    return { label: `Turn ${index + 1}`, value: cumulative };
  });
}

function summaryPoints(summaries: ConversationSummary[]): CostPoint[] {
  return [...summaries]
    .sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
    .map((summary) => ({
      label: summary.title || summary.id.slice(0, 8),
      value: Number(summary.total_cost_usd || 0),
    }));
}

function renderSparkline(points: CostPoint[], series: CostSeriesId) {
  if (!points.length) return '<p class="cost-empty">No cost data yet.</p>';
  const width = 320;
  const height = 64;
  const pad = 5;
  const max = Math.max(...points.map((point) => point.value), 0.000001);
  const coords = points.map((point, index) => {
    const x = points.length === 1 ? width / 2 : pad + (index / (points.length - 1)) * (width - pad * 2);
    const y = height - pad - (point.value / max) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = points[points.length - 1];
  return `<div class="cost-series-chart tone-${series}">
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(SERIES.find((item) => item.id === series)?.label || series)} cost trend">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="cost-axis" />
      ${points.length > 1 ? `<polyline points="${coords.join(' ')}" class="cost-line" />` : ''}
      ${coords.map((coord) => {
        const [cx, cy] = coord.split(',');
        return `<circle cx="${cx}" cy="${cy}" r="2.7" class="cost-dot" />`;
      }).join('')}
    </svg>
    <div class="cost-series-foot"><span>${points.length} point${points.length === 1 ? '' : 's'}</span><b>${formatUsd(last.value)}</b></div>
  </div>`;
}

function messageCostSteps(message: AssistantMessage): CostStep[] {
  const mode = String(message.metadata?.mode || 'council');
  return traceRows(message, mode)
    .map((row) => row.payload as CostStep | null)
    .filter((row): row is CostStep => Boolean(row));
}

function currentModelBreakdown(conversation: Conversation | null): CostPoint[] {
  const grouped = new Map<string, number>();
  for (const message of assistants(conversation)) {
    for (const step of messageCostSteps(message)) {
      const model = String(step.model || 'unknown');
      grouped.set(model, (grouped.get(model) || 0) + Number(step.cost_usd || 0));
    }
  }
  return [...grouped.entries()]
    .map(([model, value]) => ({ label: shortModel(model), value }))
    .sort((a, b) => b.value - a.value);
}

function bucketMemory(summaries: ConversationSummary[]): { points: CostPoint[]; unit: string } {
  const dated = summaries
    .map((summary) => ({ summary, date: new Date(String(summary.created_at || '')) }))
    .filter((entry) => !Number.isNaN(entry.date.getTime()));
  if (!dated.length) return { points: [], unit: 'week' };
  const times = dated.map((entry) => entry.date.getTime());
  const durationDays = (Math.max(...times) - Math.min(...times)) / 86_400_000;
  const monthly = durationDays > 180;
  const buckets = new Map<string, number>();
  for (const { summary, date } of dated) {
    let key: string;
    if (monthly) {
      key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
    } else {
      const monday = new Date(date);
      const day = (monday.getDay() + 6) % 7;
      monday.setDate(monday.getDate() - day);
      key = monday.toISOString().slice(0, 10);
    }
    buckets.set(key, (buckets.get(key) || 0) + Number(summary.total_cost_usd || 0));
  }
  return {
    points: [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([label, value]) => ({ label, value })),
    unit: monthly ? 'month' : 'week',
  };
}

function renderBars(points: CostPoint[]) {
  if (!points.length) return '<p class="cost-empty">No detailed cost data available.</p>';
  const max = Math.max(...points.map((point) => point.value), 0.000001);
  return `<div class="cost-bars">${points.map((point) => `
    <div class="cost-bar-row">
      <div class="cost-bar-label"><span title="${escapeHtml(point.label)}">${escapeHtml(point.label)}</span><b>${formatUsd(point.value)}</b></div>
      <div class="cost-bar-track"><span style="width:${Math.max(2, (point.value / max) * 100).toFixed(1)}%"></span></div>
    </div>`).join('')}</div>`;
}

export function renderCostPanel(
  state: CostPanelState,
  conversation: Conversation | null,
  summaries: ConversationSummary[],
  msg: AssistantMessage | undefined
) {
  const fingerprint = squadFingerprint(msg);
  const sameSquad = fingerprint
    ? summaries.filter((summary) => summary.squad_fingerprint === fingerprint)
    : [];
  const points: Record<CostSeriesId, CostPoint[]> = {
    current: currentPoints(conversation),
    squad: summaryPoints(sameSquad),
    memory: summaryPoints(summaries),
  };
  const selectedOne = state.selected.length === 1 ? state.selected[0] : null;
  const breakdownEnabled = Boolean(selectedOne);

  let chart = state.selected
    .map((series) => `<div class="cost-series-band"><span class="cost-series-name">${SERIES.find((item) => item.id === series)?.label}</span>${renderSparkline(points[series], series)}</div>`)
    .join('');
  if (!chart) chart = '<p class="cost-empty">Choose at least one series.</p>';

  let breakdown = '';
  if (state.breakdown && selectedOne === 'current') {
    breakdown = `<div class="cost-break"><div class="cost-break-head">By model</div>${renderBars(currentModelBreakdown(conversation))}</div>`;
  } else if (state.breakdown && selectedOne === 'squad') {
    const top = [...points.squad].sort((a, b) => b.value - a.value).slice(0, state.topN);
    const total = points.squad.reduce((sum, point) => sum + point.value, 0);
    breakdown = `<div class="cost-break">
      <div class="cost-break-head">Top sessions <span class="cost-n-controls">${[3, 5, 10].map((n) => `<button type="button" data-cost-top="${n}" class="${state.topN === n ? 'on' : ''}">${n}</button>`).join('')}</span></div>
      <div class="cost-total-line"><span>All matching sessions</span><b>${formatUsd(total)}</b></div>
      ${renderBars(top)}
    </div>`;
  } else if (state.breakdown && selectedOne === 'memory') {
    const bucketed = bucketMemory(summaries);
    breakdown = `<div class="cost-break"><div class="cost-break-head">By ${bucketed.unit}</div>${renderBars(bucketed.points)}</div>`;
  }

  return `
    <div class="cost-controls">
      ${SERIES.map((series) => `<button type="button" class="cost-toggle tone-${series.id} ${state.selected.includes(series.id) ? 'on' : ''}" data-cost-series="${series.id}" aria-pressed="${state.selected.includes(series.id)}">${series.label}</button>`).join('')}
    </div>
    <button type="button" class="cost-break-btn ${state.breakdown ? 'on' : ''}" data-cost-break ${breakdownEnabled ? '' : 'disabled'}>${state.breakdown ? 'Close breakdown' : 'Break down'}</button>
    <div class="cost-chart-area">${breakdown || chart}</div>
  `;
}
