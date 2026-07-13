import { ADDITIVE_TEMPLATES, PROMPT_IDS, additiveTemplate, stage1WrapperFromFull } from './additive-prompts';
import { buildContextInjections } from './chair-context';
import { escapeHtml } from './escape';
import { langFromPath } from './highlight-code';
import { detectContentBlocks, renderRichContent, type ContentBlock } from './markdown';
import type { AssistantMessage } from './types';
import type { TurnContextSnapshot } from './turn-context';

export interface CodeRagSegment {
  citation: string;
  symbol: string | null;
  body: string;
}

const CODERAG_HEADER_RE = /^#\s*Relevant repository context \(CodeRAG\)\s*/m;
const MANUAL_HEADER_RE = /^#\s*Manually selected context\s*/m;

export function splitCodeRagBundle(text: string): CodeRagSegment[] | null {
  const trimmed = text.trim();
  if (!CODERAG_HEADER_RE.test(trimmed) && !MANUAL_HEADER_RE.test(trimmed)) {
    return null;
  }

  const withoutHeader = trimmed
    .replace(CODERAG_HEADER_RE, '')
    .replace(MANUAL_HEADER_RE, '')
    .trim();

  const parts = withoutHeader.split(/\n(?=---\s+.+\s+---\s*$)/m);
  const segments: CodeRagSegment[] = [];

  for (const part of parts) {
    const block = part.trim();
    if (!block) continue;
    const lines = block.split('\n');
    const first = lines[0] || '';
    const citeMatch = first.match(/^---\s+(.+?)\s+---\s*$/);
    if (!citeMatch) continue;

    let rest = lines.slice(1);
    let symbol: string | null = null;
    if (rest[0]?.match(/^#\s+\S/)) {
      symbol = rest[0].replace(/^#\s+/, '').trim();
      rest = rest.slice(1);
    }

    segments.push({
      citation: citeMatch[1].trim(),
      symbol,
      body: rest.join('\n').trim(),
    });
  }

  return segments.length ? segments : null;
}

function renderCodeRagSegments(segments: CodeRagSegment[]): string {
  return segments
    .map((seg) => {
      const lang = langFromPath(seg.citation);
      const sym = seg.symbol ? `<span class="meta"># ${escapeHtml(seg.symbol)}</span>` : '';
      const body = renderRichContent(seg.body, lang, seg.citation);
      return `<section class="trace-citation">
        <h4 class="trace-cite">${escapeHtml(seg.citation)}</h4>
        ${sym}
        ${body}
      </section>`;
    })
    .join('');
}

function renderDetectedBlocks(blocks: ContentBlock[]): string {
  return blocks
    .map((b) => {
      if (b.kind === 'code') return renderRichContent(b.text, b.lang, '');
      if (b.kind === 'markdown') return renderRichContent(b.text, null, '');
      return `<pre class="ctx-pre ctx-chunk-prose">${escapeHtml(b.text)}</pre>`;
    })
    .join('');
}

/** Injected prompt / RAG bundle renderer (canonical copy of referenced context). */
export function renderContextTrace(text: string, label = ''): string {
  if (!text) return '';

  const coderag = splitCodeRagBundle(text);
  if (coderag) {
    return `<div class="trace-coderag">${renderCodeRagSegments(coderag)}</div>`;
  }

  const blocks = detectContentBlocks(text, langFromPath(label), label);
  if (blocks.length > 1) {
    return `<div class="rich-blocks">${renderDetectedBlocks(blocks)}</div>`;
  }

  return renderRichContent(text, langFromPath(label), label);
}

function renderAdditiveItem(id: string, body: string, label?: string): string {
  const meta = additiveTemplate(id);
  const title = label || meta?.label || id;
  return `<details class="trace-additive">
    <summary><code>${escapeHtml(id)}</code> · ${escapeHtml(title)}</summary>
    <pre class="ctx-pre ctx-chunk-prose">${escapeHtml(body)}</pre>
  </details>`;
}

interface SummarizeJobRow {
  prompt_id?: string;
  target_model_id?: string;
  summarizer_model?: string;
  outcome?: string;
  target_tokens?: number;
}

/**
 * Arena additions: linked references + additive wrapper/poke text only.
 * Does NOT re-embed RAG, answers, or rankings bodies.
 */
export function renderArenaAdditions(
  msg: AssistantMessage | null,
  ctx: TurnContextSnapshot
): string {
  if (!msg) return '';

  const inj = buildContextInjections(msg);
  const stage1 = msg.stage1 || [];
  const stage2 = msg.stage2 || [];
  const hasRag = ctx.contextChunkCount > 0;
  const firstFull = ctx.modelPrompts[0]?.promptFull;

  const refs = [
    `<li><button type="button" class="ctx-link" data-goto-user>User question</button> — bare text you typed (panel above).</li>`,
    firstFull || hasRag
      ? `<li><button type="button" class="ctx-link" data-goto-injected>Injected context</button> — CodeRAG bundle + query as sent in stage 1.</li>`
      : '',
    stage1.length
      ? `<li><button type="button" class="ctx-link" data-goto-answers>Stage 1 answers</button> — ${stage1.length} model response(s).</li>`
      : '',
    stage2.length
      ? `<li><button type="button" class="ctx-link" data-goto-rankings>Stage 2 rankings</button> — ${stage2.length} peer evaluation(s).</li>`
      : '',
  ]
    .filter(Boolean)
    .join('');

  const additives: string[] = [];

  additives.push(renderAdditiveItem(PROMPT_IDS.stage1, stage1WrapperFromFull(firstFull)));

  if (hasRag) {
    additives.push(renderAdditiveItem(PROMPT_IDS.ragControl, ADDITIVE_TEMPLATES[PROMPT_IDS.ragControl].text));
  }

  const jobs = (msg.metadata?.summarize_jobs as SummarizeJobRow[]) || [];
  for (const job of jobs) {
    const pid = job.prompt_id || PROMPT_IDS.summarizeRag;
    const tpl = additiveTemplate(pid);
    const label = tpl
      ? `${tpl.label} → ${(job.target_model_id || '?').split('/').pop()} (${job.outcome || '?'})`
      : `${pid} → ${job.target_model_id || '?'}`;
    additives.push(renderAdditiveItem(pid, tpl?.text || pid, label));
  }

  if (Object.keys(inj.summarizeTargets).length && !jobs.length) {
    additives.push(
      `<p class="meta">Summarizer targets recorded (${Object.keys(inj.summarizeTargets).length} model(s)) but poke prompts not stored for this turn.</p>`
    );
  }

  if (inj.contextFromLastChair) {
    additives.push(
      `<p class="meta"><strong>@lastchair</strong> — previous chairman verdict replaced RAG; see prior turn Verdict.</p>`
    );
  }

  if (stage2.length) {
    additives.push(renderAdditiveItem(PROMPT_IDS.rank, ADDITIVE_TEMPLATES[PROMPT_IDS.rank].text));
  }

  if (msg.stage3) {
    additives.push(renderAdditiveItem(PROMPT_IDS.chairPreamble, ADDITIVE_TEMPLATES[PROMPT_IDS.chairPreamble].text));
    additives.push(
      renderAdditiveItem(PROMPT_IDS.chairInstructions, ADDITIVE_TEMPLATES[PROMPT_IDS.chairInstructions].text)
    );
  }

  const directiveNotes: string[] = [];
  if (inj.forceSummarize) directiveNotes.push('@summarize');
  if (inj.skipRag) directiveNotes.push('@norag');
  if (inj.budgetOverride != null) directiveNotes.push(`@tokenbudget ${inj.budgetOverride}`);

  return `<section class="ctx-panel ctx-panel-additions">
    <h3 class="ctx-heading">Arena additions</h3>
    <p class="ctx-sub">Text the system or chairman <em>added</em> to start or advance the turn. Shared context is linked — not copied here.</p>
    <h4 class="trace-cite">Referenced elsewhere</h4>
    <ul class="quality-list ctx-refs">${refs}</ul>
    <h4 class="trace-cite">Additive framing & pokes</h4>
    ${directiveNotes.length ? `<p class="meta">Directives: ${directiveNotes.join(', ')}</p>` : ''}
    ${inj.chairmanModel ? `<p class="meta">Chairman model: ${escapeHtml(inj.chairmanModel.split('/').pop() || inj.chairmanModel)}</p>` : ''}
    <div class="trace-additives">${additives.join('')}</div>
    ${
      !jobs.length && !inj.contextFromLastChair && !Object.keys(inj.summarizeTargets).length
        ? `<p class="meta">No chairman summarizer pokes or @lastchair this turn — council used standard CodeRAG → stage 1 → rankings → chair.</p>`
        : ''
    }
  </section>`;
}

/** @deprecated use renderArenaAdditions */
export function renderChairmanTrace(_msg: AssistantMessage | null): string {
  return '';
}

/** @deprecated use renderArenaAdditions */
export function renderContextInjections(_msg: AssistantMessage | null): string {
  return '';
}