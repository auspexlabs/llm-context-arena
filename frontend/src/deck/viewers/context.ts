import { escapeHtml } from '../escape';
import { renderArenaAdditions, renderContextTrace } from '../content-trace';
import { langFromPath } from '../highlight-code';
import { renderRichContent } from '../markdown';
import { preventFocusScroll, setScrollAnchor } from '../scroll-anchor';
import { setDeckView } from '../store';
import {
  activePromptForModel,
  chunkKey,
  type TurnContextSnapshot,
} from '../turn-context';
import {
  collapseAllRag,
  expandAllRag,
  getState,
  setContextPromptModel,
  toggleRagChunk,
  toggleRagList,
} from '../store';
import type { AssistantMessage } from '../types';

export function renderContextViewport(
  container: HTMLElement,
  ctx: TurnContextSnapshot,
  msg: AssistantMessage | null = null
) {
  const s = getState();
  const modelIdx = s.contextPromptModel;
  const prompt = activePromptForModel(ctx, modelIdx, false);
  const keys = ctx.ragChunks.map((c, i) => chunkKey(c, i));
  const entry = ctx.modelPrompts[modelIdx < 0 ? 0 : modelIdx];

  const toolbar =
    ctx.ragChunks.length > 0
      ? `<div class="ctx-toolbar">
          <button type="button" class="ctx-link" data-expand-all>Expand all RAG</button>
          <span class="meta">·</span>
          <button type="button" class="ctx-link" data-collapse-all>Collapse all</button>
        </div>`
      : '';

  const modelTabs =
    ctx.modelPrompts.length > 1
      ? `<div class="ctx-model-tabs">
          <button type="button" class="ctx-model-tab${modelIdx < 0 ? ' on' : ''}" data-prompt-model="-1">Shared</button>
          ${ctx.modelPrompts
            .map((m, i) => {
              const short = m.model.split('/').pop() || m.model;
              const on = modelIdx === i ? ' on' : '';
              return `<button type="button" class="ctx-model-tab${on}" data-prompt-model="${i}">${escapeHtml(short)}</button>`;
            })
            .join('')}
        </div>`
      : '';

  const promptBlock = prompt.text
    ? `<section class="ctx-panel ctx-panel-prompt" id="ctx-injected">
        <h3 class="ctx-heading">Injected context</h3>
        <p class="ctx-sub">${escapeHtml(prompt.label)} · stage 1 message body (query + RAG)${ctx.contextTokens != null ? ` · ~${ctx.contextTokens.toLocaleString()} ctx tok` : ''}</p>
        ${modelTabs}
        <div class="ctx-trace-body" data-prompt-body>${renderContextTrace(prompt.text)}</div>
        ${entry?.promptFull ? `<button type="button" class="ctx-link" data-toggle-full>Toggle full prompt</button>` : ''}
      </section>`
    : '';

  const ragList = s.ragListExpanded
    ? ctx.ragChunks
        .map((chunk, i) => {
          const key = chunkKey(chunk, i);
          const open = s.ragChunksExpanded.includes(key);
          const label = chunk.citation || chunk.source || chunk.doc_id || `chunk ${i + 1}`;
          const score = chunk.score != null ? ` · ${(chunk.score * 100).toFixed(0)}%` : '';
          const lang = langFromPath(label);
          const body =
            open && chunk.content ? renderRichContent(chunk.content, lang, label) : '';
          return `<button type="button" class="rag-chunk ${open ? 'open' : ''}" data-rag-chunk="${i}" data-scroll-anchor="${key.replace(/"/g, '')}">
            <span>${open ? '▾' : '▸'} ${escapeHtml(label)}${score}</span>
          </button>${body}`;
        })
        .join('')
    : '';

  const ragSection = ctx.ragChunks.length
    ? `<section class="ctx-panel ctx-panel-rag">
        <h3 class="ctx-heading">RAG retrieval</h3>
        <p class="ctx-sub">${ctx.ragChunks.length} chunks · same content as injected context, per-chunk view</p>
        <button type="button" class="rag-toggle" data-rag-list-toggle>
          ${s.ragListExpanded ? '▾' : '▸'} Show chunk list
        </button>
        ${ragList ? `<div class="rag-list">${ragList}</div>` : ''}
      </section>`
    : '';

  container.innerHTML = `
    <h2 class="ctx-title">Context trace</h2>
    ${toolbar}
    <section class="ctx-panel ctx-panel-user" id="ctx-user">
      <h3 class="ctx-heading">User question</h3>
      <p class="ctx-sub">What you typed — without injection</p>
      <pre class="ctx-pre">${escapeHtml(ctx.userQuery || '—')}</pre>
    </section>
    ${msg ? renderArenaAdditions(msg, ctx) : ''}
    ${promptBlock}
    ${ragSection}
  `;

  let showFull = false;
  container.querySelector('[data-toggle-full]')?.addEventListener('click', () => {
    showFull = !showFull;
    const p = activePromptForModel(ctx, modelIdx, showFull);
    const body = container.querySelector('[data-prompt-body]');
    if (body && p.text) body.innerHTML = renderContextTrace(p.text);
  });

  container.querySelector('[data-goto-user]')?.addEventListener('click', () => {
    container.querySelector('#ctx-user')?.scrollIntoView({ block: 'nearest' });
  });
  container.querySelector('[data-goto-injected]')?.addEventListener('click', () => {
    container.querySelector('#ctx-injected')?.scrollIntoView({ block: 'nearest' });
  });
  container.querySelector('[data-goto-answers]')?.addEventListener('click', () => setDeckView('answers'));
  container.querySelector('[data-goto-rankings]')?.addEventListener('click', () => setDeckView('rankings'));

  container.querySelectorAll('[data-expand-all], [data-collapse-all], [data-rag-list-toggle], [data-rag-chunk]').forEach((btn) => {
    preventFocusScroll(btn);
  });
  container.querySelector('[data-expand-all]')?.addEventListener('click', () => expandAllRag(keys));
  container.querySelector('[data-collapse-all]')?.addEventListener('click', () => collapseAllRag());
  container.querySelector('[data-rag-list-toggle]')?.addEventListener('click', () => toggleRagList());
  container.querySelectorAll('[data-rag-chunk]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const i = Number((btn as HTMLElement).dataset.ragChunk);
      const key = chunkKey(ctx.ragChunks[i], i);
      setScrollAnchor(key);
      toggleRagChunk(key);
    });
  });
  container.querySelectorAll('[data-prompt-model]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      setContextPromptModel(Number((btn as HTMLElement).dataset.promptModel));
    });
  });
}