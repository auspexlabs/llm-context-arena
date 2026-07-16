import { escapeHtml } from '../escape';
import { renderArenaAdditions } from '../content-trace';
import { langFromPath } from '../highlight-code';
import { renderInjectionWorkflow } from '../injection-workflow';
import { renderRichContent } from '../markdown';
import { preventFocusScroll, setScrollAnchor } from '../scroll-anchor';
import { setContextAdditiveExpanded, setDeckView } from '../store';
import { chunkKey, type TurnContextSnapshot } from '../turn-context';
import {
  collapseAllRag,
  expandAllRag,
  getState,
  setContextInjectionSelection,
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
  const keys = ctx.ragChunks.map((c, i) => chunkKey(c, i));

  const toolbar =
    ctx.ragChunks.length > 0
      ? `<div class="ctx-toolbar">
          <button type="button" class="ctx-link" data-expand-all>Expand all RAG</button>
          <span class="meta">·</span>
          <button type="button" class="ctx-link" data-collapse-all>Collapse all</button>
        </div>`
      : '';

  const promptBlock = ctx.modelPrompts.length
    ? `<section class="ctx-panel ctx-panel-prompt" id="ctx-injected">
        <h3 class="ctx-heading">Injected context</h3>
        <p class="ctx-sub">Where retrieval happened, who received the grounded turn, and what Curia inserted between model calls. RAG content stays in RAG Retrieval.</p>
        ${renderInjectionWorkflow(ctx, s.contextInjectionSelection)}
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
    ? `<section class="ctx-panel ctx-panel-rag" id="ctx-rag">
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
    ${promptBlock}
    ${msg ? renderArenaAdditions(msg, ctx, s.contextAdditivesExpanded) : ''}
    ${ragSection}
  `;

  container.querySelectorAll('[data-injection-node]').forEach((node) => {
    const open = () => setContextInjectionSelection((node as SVGGElement).dataset.injectionNode || null);
    node.addEventListener('click', open);
    node.addEventListener('keydown', (event) => {
      const key = (event as KeyboardEvent).key;
      if (key === 'Enter' || key === ' ') {
        event.preventDefault();
        open();
      }
    });
  });
  container.querySelectorAll('[data-injection-close]').forEach((node) => {
    node.addEventListener('click', (event) => {
      if (event.target === node || (node as HTMLElement).matches('button')) {
        setContextInjectionSelection(null);
      }
    });
  });
  container.querySelectorAll<HTMLDetailsElement>('details[data-additive-key]').forEach((details) => {
    details.addEventListener('toggle', () => {
      const key = details.dataset.additiveKey;
      if (key) setContextAdditiveExpanded(key, details.open);
    });
  });
  container.querySelectorAll('[data-injection-goto-rag]').forEach((node) => {
    node.addEventListener('click', () => {
      setContextInjectionSelection(null);
      container.querySelector('#ctx-rag')?.scrollIntoView({ block: 'start' });
    });
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
}
