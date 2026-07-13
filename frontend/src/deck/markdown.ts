import DOMPurify from 'dompurify';
import { marked } from 'marked';
import hljs from 'highlight.js/lib/core';
import { escapeHtml } from './escape';
import { highlightCode, langFromPath } from './highlight-code';

marked.setOptions({ gfm: true, breaks: true });

marked.use({
  renderer: {
    code({ text, lang }: { text: string; lang?: string }) {
      const language = lang && hljs.getLanguage(lang) ? lang : null;
      const inner = language ? highlightCode(text, language) : highlightCode(text, null);
      const cls = language ? `hljs language-${language}` : 'hljs';
      return `<pre><code class="${cls}">${inner}</code></pre>`;
    },
  },
});

export type BlockKind = 'code' | 'markdown' | 'prose';

export interface ContentBlock {
  kind: BlockKind;
  text: string;
  lang: string | null;
}

const FENCE_RE = /```([^\n`]*)\n([\s\S]*?)```/g;

/** Markdown signals that are unlikely to be source code (no single-# headings). */
const MD_STRONG =
  /(^|\n)#{2,6}\s|(^|\n)([-*+]\s+|\d+\.\s+)|\|.+\|.+\||\[[^\]]+\]\([^)]+\)|^>\s/m;

const CODE_LINE =
  /^\s*(import |from |export |def |class |async def |function |const |let |var |#include |package |public |private |fn |use |struct |interface |type )/;

export function looksLikeMarkdown(text: string): boolean {
  return MD_STRONG.test(text.trim());
}

function isCodeLike(text: string): boolean {
  const lines = text.trim().split('\n').filter((l) => l.trim());
  if (!lines.length) return false;
  const codeish = lines.filter((l) => CODE_LINE.test(l) || /[{}();]/.test(l)).length;
  return codeish / lines.length >= 0.35;
}

function resolveLang(hint: string | null, fallback: string | null): string | null {
  if (hint && hljs.getLanguage(hint)) return hint;
  if (fallback && hljs.getLanguage(fallback)) return fallback;
  return hint || fallback;
}

function splitByFences(text: string): ContentBlock[] | null {
  FENCE_RE.lastIndex = 0;
  const blocks: ContentBlock[] = [];
  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = FENCE_RE.exec(text)) !== null) {
    if (match.index > last) {
      blocks.push({ kind: 'markdown', text: text.slice(last, match.index), lang: null });
    }
    const info = (match[1] || '').trim();
    const fenceLang = info.split(/\s+/)[0] || null;
    blocks.push({ kind: 'code', text: match[2], lang: fenceLang });
    last = match.index + match[0].length;
  }

  if (last < text.length) {
    blocks.push({ kind: 'markdown', text: text.slice(last), lang: null });
  }

  return blocks.length ? blocks : null;
}

function classifyTextBlock(text: string, defaultLang: string | null, preferCode: boolean): BlockKind {
  const trimmed = text.trim();
  if (!trimmed) return 'prose';
  if (looksLikeMarkdown(trimmed)) return 'markdown';
  if (preferCode || (defaultLang && isCodeLike(trimmed))) return 'code';
  return 'prose';
}

/** Split chunk text into renderable blocks (fences, then per-segment classification). */
export function detectContentBlocks(
  text: string,
  defaultLang: string | null = null,
  label = ''
): ContentBlock[] {
  const ext = label.split('.').pop()?.toLowerCase() || '';
  const pathLang = langFromPath(label) || defaultLang;
  const isMdFile = pathLang === 'markdown' || ext === 'md' || ext === 'mdx';
  const preferCode = !isMdFile && !!pathLang && pathLang !== 'markdown';

  const fenced = splitByFences(text);
  if (fenced) {
    return fenced.map((block) => {
      if (block.kind === 'code') {
        return { ...block, lang: resolveLang(block.lang, pathLang) };
      }
      const kind = classifyTextBlock(block.text, pathLang, false);
      return { kind, text: block.text, lang: kind === 'code' ? pathLang : null };
    });
  }

  if (isMdFile) {
    return [{ kind: 'markdown', text, lang: null }];
  }

  if (preferCode && !looksLikeMarkdown(text)) {
    return [{ kind: 'code', text, lang: pathLang }];
  }

  const kind = classifyTextBlock(text, pathLang, preferCode);
  return [{ kind, text, lang: kind === 'code' ? pathLang : null }];
}

function renderBlock(block: ContentBlock): string {
  const trimmed = block.text.trim();
  if (!trimmed) return '';

  if (block.kind === 'code') {
    const lang = block.lang;
    return `<pre class="ctx-pre ctx-chunk-body hljs"><code class="language-${lang || 'plaintext'}">${highlightCode(block.text, lang)}</code></pre>`;
  }

  if (block.kind === 'markdown') {
    return `<div class="markdown-content">${renderMarkdown(block.text)}</div>`;
  }

  return `<pre class="ctx-pre ctx-chunk-prose">${escapeHtml(block.text)}</pre>`;
}

export function renderMarkdown(text: string): string {
  if (!text) return '';
  const raw = marked.parse(text) as string;
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
}

/** Per-block markdown / code / plain prose for RAG chunks and mixed sources. */
export function renderRichContent(text: string, lang: string | null = null, label = ''): string {
  if (!text) return '';
  const blocks = detectContentBlocks(text, lang, label).map(renderBlock).filter(Boolean);
  if (!blocks.length) return '';
  if (blocks.length === 1) return blocks[0];
  return `<div class="rich-blocks">${blocks.join('')}</div>`;
}

export function deAnonymizeText(text: string, labelToModel: Record<string, string> | undefined): string {
  if (!labelToModel) return text;
  let result = text;
  for (const [label, model] of Object.entries(labelToModel)) {
    const short = model.split('/').pop() || model;
    result = result.replace(new RegExp(label, 'g'), `**${short}**`);
  }
  return result;
}