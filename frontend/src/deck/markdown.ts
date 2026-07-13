import { marked } from 'marked';

marked.setOptions({ gfm: true, breaks: true });

export function renderMarkdown(text: string): string {
  if (!text) return '';
  return marked.parse(text) as string;
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