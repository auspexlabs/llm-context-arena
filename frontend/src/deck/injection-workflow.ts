import { escapeHtml } from './escape';
import type { ModelPromptEntry, TurnContextSnapshot } from './turn-context';
import type { PromptProvenance } from './types';

export interface InjectionPayload {
  key: string;
  title: string;
  stage: string;
  recipient: string;
  status: string;
  payload: string;
  promptProvenance: PromptProvenance | null;
  contextTokens: number | null;
  kind: 'source' | 'arena' | 'chair';
  stageKind: string;
  hasRagLink: boolean;
  rankBadge?: {
    text: string;
    title: string;
    tone: 'aggregate' | 'ballot';
  };
}

interface NodePosition {
  key: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

const WIDTH = 920;
const NODE_W = 190;
const NODE_H = 66;
const COL_GAP = 36;
const ROW_GAP = 116;
const MODEL_TOP = 154;

function shortModel(model: string): string {
  return model.split('/').pop() || model;
}

function truncate(value: string, length = 24): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function stageLabel(entry: ModelPromptEntry, index: number, mode: string): string {
  if (mode === 'council' || mode === 'baseline') {
    return entry.kind === 'ranking' ? 'Stage 2 · peer ranking' : 'Stage 1 · independent answer';
  }
  if (mode === 'fight') {
    if (entry.kind === 'answer') return 'Opening · position';
    if (entry.kind === 'critique') return 'Opposition · critique';
    if (entry.kind === 'defense') return 'Reply · defense';
  }
  return `Step ${entry.ordinal || index + 1} · ${entry.role || 'arena'}`;
}

function ballotLabel(ranking: string[]): string {
  return ranking
    .map((label) => label.replace(/^Response\s+/i, '').trim())
    .filter(Boolean)
    .join('›');
}

function aggregatePositions(ctx: TurnContextSnapshot): Map<string, { position: number; avgRank: number | null; votes: number | null }> {
  const ordered = [...ctx.aggregateRankings].sort((a, b) => {
    if (a.avgRank == null) return 1;
    if (b.avgRank == null) return -1;
    return a.avgRank - b.avgRank;
  });
  return new Map(ordered.map((entry, index) => [entry.model, {
    position: index + 1,
    avgRank: entry.avgRank,
    votes: entry.votes,
  }]));
}

export function injectionPayloads(ctx: TurnContextSnapshot): InjectionPayload[] {
  const hasRag = ctx.contextChunkCount > 0;
  const aggregate = aggregatePositions(ctx);
  const result: InjectionPayload[] = [
    {
      key: 'source',
      title: hasRag ? 'RAG attached' : 'User input attached',
      stage: 'Context event',
      recipient: 'Context pipeline',
      status: hasRag ? `${ctx.contextChunkCount} chunks attached` : 'no RAG attached',
      payload: hasRag
        ? `CodeRAG retrieval occurred. ${ctx.contextChunkCount} chunks were attached to the grounded question.\n\nThe retrieved text is intentionally shown only in RAG Retrieval.`
        : 'No CodeRAG payload was attached to this turn.',
      promptProvenance: null,
      contextTokens: ctx.contextTokens,
      kind: 'source',
      stageKind: 'context',
      hasRagLink: hasRag,
    },
  ];

  ctx.modelPrompts.forEach((entry, index) => {
    const aggregateRank = entry.kind === 'answer' ? aggregate.get(entry.model) : null;
    const ballot = entry.kind === 'ranking' ? ballotLabel(entry.parsedRanking) : '';
    const aggregateDetails = aggregateRank
      ? `Aggregate peer rank #${aggregateRank.position}${aggregateRank.avgRank == null ? '' : ` · average ${aggregateRank.avgRank.toFixed(2)}`}${aggregateRank.votes == null ? '' : ` · ${aggregateRank.votes} votes`}`
      : '';
    result.push({
      key: `arena-${index}`,
      title: shortModel(entry.model),
      stage: stageLabel(entry, index, ctx.mode),
      recipient: entry.model,
      status: entry.status || 'unknown',
      payload: entry.orchestrationText ||
        `Curia routed the grounded question to this model for ${entry.role || 'an arena step'}.\n\nThe orchestration text was not persisted separately for this legacy turn.`,
      promptProvenance: entry.promptProvenance,
      contextTokens: null,
      kind: 'arena',
      stageKind: entry.kind || entry.role || 'arena',
      hasRagLink: hasRag,
      ...(aggregateRank ? { rankBadge: {
        text: `#${aggregateRank.position}`,
        title: aggregateDetails,
        tone: 'aggregate' as const,
      } } : ballot ? { rankBadge: {
        text: ballot,
        title: `This model's ballot: ${entry.parsedRanking.join(' › ')}`,
        tone: 'ballot' as const,
      } } : {}),
    });
  });

  if (ctx.chairPromptFull || ctx.chairPromptPreview) {
    const leader = [...aggregate.entries()].find(([, rank]) => rank.position === 1);
    result.push({
      key: 'chair',
      title: 'Chair synthesis',
      stage: 'Terminal verdict',
      recipient: 'Chair',
      status: ctx.executionTrace?.summary.final_status || 'unknown',
      payload: ctx.chairOrchestrationText || legacyChairOrchestration(ctx),
      promptProvenance: ctx.chairPromptProvenance,
      contextTokens: null,
      kind: 'chair',
      stageKind: 'verdict',
      hasRagLink: hasRag,
      ...(leader ? { rankBadge: {
        text: '#1',
        title: `Aggregate leader entering synthesis: ${leader[0]}`,
        tone: 'aggregate' as const,
      } } : {}),
    });
  }

  return result;
}

function legacyChairOrchestration(ctx: TurnContextSnapshot): string {
  if (ctx.mode === 'round_robin') {
    return `Final draft from round robin:\n${ctx.chairPriorDraft || '[latest draft attached]'}\n\nOriginal question:\n[Grounded question and repository context attached separately; inspect RAG retrieval]\n\nProduce the final answer building on the latest draft; fix any errors and cite context if present.`;
  }
  return 'Curia assembled a terminal synthesis packet from prior stage artifacts.\n\nThe orchestration framing was not persisted separately from grounded content for this legacy turn.';
}

function arenaPositions(count: number): NodePosition[] {
  const cols = Math.min(4, Math.max(1, count));
  const gridWidth = cols * NODE_W + (cols - 1) * COL_GAP;
  const left = (WIDTH - gridWidth) / 2;
  return Array.from({ length: count }, (_, index) => ({
    key: `arena-${index}`,
    x: left + (index % cols) * (NODE_W + COL_GAP),
    y: MODEL_TOP + Math.floor(index / cols) * ROW_GAP,
    width: NODE_W,
    height: NODE_H,
  }));
}

function stagePositions(payloads: InjectionPayload[], startY: number): NodePosition[] {
  return arenaPositions(payloads.length).map((node, index) => ({
    ...node,
    key: payloads[index].key,
    y: startY + (node.y - MODEL_TOP),
  }));
}

function center(node: NodePosition): { x: number; y: number } {
  return { x: node.x + node.width / 2, y: node.y + node.height / 2 };
}

function renderEdge(
  from: NodePosition,
  to: NodePosition,
  kind: 'injection' | 'handoff' | 'synthesis'
): string {
  const fromCenter = center(from);
  const toCenter = center(to);
  const sameRow = Math.abs(from.y - to.y) < 2;
  const a = kind === 'handoff' && sameRow
    ? { x: from.x + from.width, y: fromCenter.y }
    : { x: fromCenter.x, y: from.y + from.height };
  const b = kind === 'handoff' && sameRow
    ? { x: to.x, y: toCenter.y }
    : { x: toCenter.x, y: to.y };
  const marker = kind === 'handoff' ? 'handoff-arrow' : kind === 'synthesis' ? 'synthesis-arrow' : 'injection-arrow';
  return `<path class="injection-edge ${kind}" d="M ${a.x} ${a.y} C ${a.x} ${(a.y + b.y) / 2}, ${b.x} ${(a.y + b.y) / 2}, ${b.x} ${b.y}" marker-end="url(#${marker})" />`;
}

function renderBusEdges(
  fromNodes: NodePosition[],
  toNodes: NodePosition[],
  kind: 'handoff' | 'synthesis'
): string[] {
  if (!fromNodes.length || !toNodes.length) return [];
  const fromBottom = Math.max(...fromNodes.map((node) => node.y + node.height));
  const toTop = Math.min(...toNodes.map((node) => node.y));
  const busY = (fromBottom + toTop) / 2;
  const xs = [...fromNodes, ...toNodes].map((node) => center(node).x);
  const marker = kind === 'handoff' ? 'handoff-arrow' : 'synthesis-arrow';
  const paths = fromNodes.map((node) => {
    const x = center(node).x;
    return `<path class="injection-edge ${kind}" d="M ${x} ${node.y + node.height} L ${x} ${busY}" />`;
  });
  paths.push(`<path class="injection-edge ${kind}" d="M ${Math.min(...xs)} ${busY} L ${Math.max(...xs)} ${busY}" />`);
  paths.push(...toNodes.map((node) => {
    const x = center(node).x;
    return `<path class="injection-edge ${kind}" d="M ${x} ${busY} L ${x} ${node.y}" marker-end="url(#${marker})" />`;
  }));
  return paths;
}

function renderNode(node: NodePosition, payload: InjectionPayload, selected: boolean): string {
  const status = payload.status === 'succeeded' ? '✓ succeeded' : payload.status;
  const badge = payload.rankBadge;
  const badgeWidth = badge ? Math.min(104, Math.max(32, 18 + badge.text.length * 7)) : 0;
  const badgeMarkup = badge
    ? `<g class="injection-rank-badge tone-${badge.tone}" aria-label="${escapeHtml(badge.title)}">
        <title>${escapeHtml(badge.title)}</title>
        <rect x="${node.x + node.width - badgeWidth + 6}" y="${node.y - 10}" width="${badgeWidth}" height="22" rx="11" />
        <text x="${node.x + node.width - badgeWidth / 2 + 6}" y="${node.y + 5}" text-anchor="middle">${escapeHtml(badge.text)}</text>
      </g>`
    : '';
  return `<g class="injection-node kind-${payload.kind}${selected ? ' selected' : ''}" data-injection-node="${payload.key}" role="button" tabindex="0" aria-label="Open ${escapeHtml(payload.stage)} payload for ${escapeHtml(payload.recipient)}">
    <title>${escapeHtml(payload.stage)} · ${escapeHtml(payload.title)} · ${escapeHtml(status)}</title>
    <rect x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="10" />
    <text class="injection-node-stage" x="${node.x + 12}" y="${node.y + 20}">${escapeHtml(payload.stage)}</text>
    <text class="injection-node-title" x="${node.x + 12}" y="${node.y + 40}">${escapeHtml(truncate(payload.title, 20))}</text>
    <text class="injection-node-status" x="${node.x + 12}" y="${node.y + 56}">${escapeHtml(status)}</text>
    ${badgeMarkup}
  </g>`;
}

function modal(payload: InjectionPayload | undefined): string {
  if (!payload) return '';
  const size = payload.payload.length.toLocaleString();
  const tokens = payload.contextTokens != null ? ` · ~${payload.contextTokens.toLocaleString()} context tokens` : '';
  const note = payload.kind === 'source'
    ? 'Retrieval event only. The RAG body is intentionally not duplicated in this modal.'
    : 'Curia orchestration text and handoff artifacts for this node. Grounded user/RAG content is intentionally omitted.';
  const ragLink = payload.hasRagLink
    ? '<button type="button" class="ctx-link injection-rag-link" data-injection-goto-rag>Open RAG retrieval →</button>'
    : '';
  const promptBody = payload.promptProvenance
    ? `<div class="injection-payload injection-provenance">${payload.promptProvenance.parts.map((part) => {
        if (part.kind === 'text') return escapeHtml(part.text || '');
        if (part.kind === 'context_ref') {
          return `<button type="button" class="injection-artifact-link context" data-injection-goto-rag>[${escapeHtml(part.label || 'Grounded context')} attached separately]</button>`;
        }
        const label = `[${part.label || 'model output'} artifact attached]`;
        return part.producer_step_id
          ? `<button type="button" class="injection-artifact-link" data-injection-goto-step="${escapeHtml(part.producer_step_id)}">${escapeHtml(label)}</button>`
          : `<span class="injection-artifact-missing">${escapeHtml(label)}</span>`;
      }).join('')}</div>`
    : `<pre class="injection-payload"><code>${escapeHtml(payload.payload || 'No persisted payload was recorded for this node.')}</code></pre>`;
  return `<div class="injection-modal-backdrop" data-injection-close>
    <section class="injection-modal" role="dialog" aria-modal="true" aria-labelledby="injection-modal-title">
      <header class="injection-modal-head">
        <div>
          <p class="rail-eyebrow">${escapeHtml(payload.stage)}</p>
          <h2 id="injection-modal-title">${escapeHtml(payload.title)}</h2>
          <p class="ctx-sub">Recipient: ${escapeHtml(payload.recipient)} · ${escapeHtml(payload.status)} · ${size} characters${tokens}</p>
        </div>
        <button type="button" class="participant-close" data-injection-close aria-label="Close injected payload">×</button>
      </header>
      <div class="injection-modal-note"><span>${note}</span>${ragLink}</div>
      ${promptBody}
    </section>
  </div>`;
}

export function renderInjectionWorkflow(ctx: TurnContextSnapshot, selectedKey: string | null): string {
  const payloads = injectionPayloads(ctx);
  const arenas = payloads.filter((payload) => payload.kind === 'arena');
  const sourcePayload = payloads[0];
  const chairPayload = payloads.find((payload) => payload.kind === 'chair');
  const sourceNode: NodePosition = { key: 'source', x: (WIDTH - 220) / 2, y: 20, width: 220, height: 72 };
  let arenaNodes: NodePosition[] = [];
  let chairNode: NodePosition | null = null;
  let height = 360;
  const edges: string[] = [];
  const isCouncil = ctx.mode === 'council' || ctx.mode === 'baseline';
  const isFight = ctx.mode === 'fight';
  let handoffLegends = ['Predecessor draft'];
  let synthesisLegend = 'Synthesis packet';

  if (isCouncil) {
    const answers = arenas.filter((payload) => payload.stageKind === 'answer');
    const rankings = arenas.filter((payload) => payload.stageKind === 'ranking');
    const answerNodes = stagePositions(answers, MODEL_TOP);
    const answerRows = Math.ceil(Math.max(1, answers.length) / 4);
    const rankingTop = MODEL_TOP + answerRows * ROW_GAP + 50;
    const rankingNodes = stagePositions(rankings, rankingTop);
    const rankingRows = Math.ceil(Math.max(1, rankings.length) / 4);
    const chairY = rankingTop + rankingRows * ROW_GAP + 50;
    arenaNodes = [...answerNodes, ...rankingNodes];
    chairNode = chairPayload
      ? { key: 'chair', x: (WIDTH - 220) / 2, y: chairY, width: 220, height: 72 }
      : null;
    answerNodes.forEach((node) => edges.push(renderEdge(sourceNode, node, 'injection')));
    edges.push(...renderBusEdges(answerNodes, rankingNodes, 'handoff'));
    if (chairNode) edges.push(...renderBusEdges(rankingNodes.length ? rankingNodes : answerNodes, [chairNode], 'synthesis'));
    height = (chairNode ? chairNode.y + chairNode.height : rankingTop + rankingRows * ROW_GAP) + 24;
    handoffLegends = ['Anonymized answer packet'];
    synthesisLegend = 'Answers + rankings';
  } else if (isFight) {
    const answers = arenas.filter((payload) => payload.stageKind === 'answer');
    const critiques = arenas.filter((payload) => payload.stageKind === 'critique');
    const defenses = arenas.filter((payload) => payload.stageKind === 'defense');
    const answerNodes = stagePositions(answers, MODEL_TOP);
    const answerRows = Math.ceil(Math.max(1, answers.length) / 4);
    const critiqueTop = MODEL_TOP + answerRows * ROW_GAP + 50;
    const critiqueNodes = stagePositions(critiques, critiqueTop);
    const critiqueRows = Math.ceil(Math.max(1, critiques.length) / 4);
    const defenseTop = critiqueTop + critiqueRows * ROW_GAP + 50;
    const defenseNodes = stagePositions(defenses, defenseTop);
    const defenseRows = Math.ceil(Math.max(1, defenses.length) / 4);
    const chairY = defenseTop + defenseRows * ROW_GAP + 50;
    arenaNodes = [...answerNodes, ...critiqueNodes, ...defenseNodes];
    chairNode = chairPayload
      ? { key: 'chair', x: (WIDTH - 220) / 2, y: chairY, width: 220, height: 72 }
      : null;
    answerNodes.forEach((node) => edges.push(renderEdge(sourceNode, node, 'injection')));
    edges.push(...renderBusEdges(answerNodes, critiqueNodes, 'handoff'));
    edges.push(...renderBusEdges(critiqueNodes, defenseNodes, 'handoff'));
    if (chairNode) edges.push(...renderBusEdges(defenseNodes.length ? defenseNodes : critiqueNodes, [chairNode], 'synthesis'));
    height = (chairNode ? chairNode.y + chairNode.height : defenseTop + defenseRows * ROW_GAP) + 24;
    handoffLegends = ['Peer positions → critique', 'Own answer + peer critiques → defense'];
    synthesisLegend = 'Defenses → synthesis';
  } else {
    arenaNodes = arenaPositions(arenas.length);
    const rows = Math.ceil(Math.max(1, arenas.length) / 4);
    const chairY = MODEL_TOP + rows * ROW_GAP + 18;
    chairNode = chairPayload
      ? { key: 'chair', x: (WIDTH - 220) / 2, y: chairY, width: 220, height: 72 }
      : null;
    arenaNodes.forEach((node) => edges.push(renderEdge(sourceNode, node, 'injection')));
    arenaNodes.forEach((node, index) => {
      const entry = ctx.modelPrompts[index];
      if (!entry?.predecessorStepIds.length || index === 0) return;
      edges.push(renderEdge(arenaNodes[index - 1], node, 'handoff'));
    });
    if (chairNode && arenaNodes.length) {
      const terminalNode = chairNode;
      const sequential = arenaNodes.some((_, index) => (ctx.modelPrompts[index]?.predecessorStepIds.length || 0) > 0);
      const sources = sequential ? [arenaNodes[arenaNodes.length - 1]] : arenaNodes;
      sources.forEach((node) => edges.push(renderEdge(node, terminalNode, 'synthesis')));
    }
    height = (chairNode ? chairNode.y + chairNode.height : MODEL_TOP + rows * ROW_GAP) + 24;
  }

  const payloadByKey = new Map(payloads.map((payload) => [payload.key, payload]));
  const nodes = [
    renderNode(sourceNode, sourcePayload, selectedKey === sourcePayload.key),
    ...arenaNodes.map((node) => {
      const payload = payloadByKey.get(node.key)!;
      return renderNode(node, payload, selectedKey === payload.key);
    }),
    chairNode && chairPayload ? renderNode(chairNode, chairPayload, selectedKey === chairPayload.key) : '',
  ].join('');
  const selected = payloads.find((payload) => payload.key === selectedKey);

  return `<div class="injection-workflow">
    <svg class="injection-graph" viewBox="0 0 ${WIDTH} ${height}" role="img" aria-label="Context injection workflow">
      <defs>
        <marker id="injection-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker>
        <marker id="handoff-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker>
        <marker id="synthesis-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker>
      </defs>
      <g class="injection-edges">${edges.join('')}</g>
      <g class="injection-nodes">${nodes}</g>
    </svg>
    <div class="injection-legend" aria-label="Workflow legend">
      <span><i class="legend-line injection"></i> RAG attached</span>
      ${handoffLegends.map((label) => `<span><i class="legend-line handoff"></i> ${label}</span>`).join('')}
      <span><i class="legend-line synthesis"></i> ${synthesisLegend}</span>
      <span>Click a node for Curia's orchestration text</span>
    </div>
  </div>${modal(selected)}`;
}
