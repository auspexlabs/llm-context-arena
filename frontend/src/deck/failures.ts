export interface ModelFailure {
  model?: string;
  stage?: string;
  role?: string;
  status?: number | string | null;
  message?: string;
  provider?: string | null;
  raw?: unknown;
  failure_kind?: string;
}

export function failureKey(f: ModelFailure, index: number): string {
  return `${f.model || 'unknown'}-${f.stage || index}-${index}`;
}

export function failureVerbatim(f: ModelFailure): string {
  const parts = [
    f.status != null ? `HTTP ${f.status}` : null,
    f.provider ? `provider: ${f.provider}` : null,
    f.message || null,
  ].filter(Boolean);
  if (f.raw && typeof f.raw === 'object') {
    try {
      parts.push(JSON.stringify(f.raw, null, 2));
    } catch {
      parts.push(String(f.raw));
    }
  } else if (f.raw) {
    parts.push(String(f.raw));
  }
  return parts.join('\n') || 'No detail recorded';
}

export function privacyFailureShare(failures: ModelFailure[]): number {
  if (!failures.length) return 0;
  const n = failures.filter((f) =>
    ['privacy_blocked', 'policy_blocked'].includes(classifyFailureKind(f))
  ).length;
  return n / failures.length;
}

export function failuresByKind(failures: ModelFailure[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const f of failures) {
    const k = String(f.failure_kind || classifyFailureKind(f));
    out[k] = (out[k] || 0) + 1;
  }
  return out;
}

const CONTEXT_TOKENS = [
  'context length',
  'context window',
  'maximum context',
  'too many tokens',
  'token limit',
  'max tokens',
];
const PRIVACY_TOKENS = [
  'privacy',
  'data policy',
  'guardrail',
  'training',
  'data logging',
  'zero data retention',
];

/** Client-side fallback when persisted records lack failure_kind. */
export function classifyFailureKind(f: ModelFailure): string {
  if (f.failure_kind) return String(f.failure_kind);
  const hay = `${f.message || ''} ${f.provider || ''}`.toLowerCase();
  if (CONTEXT_TOKENS.some((t) => hay.includes(t))) return 'context_exceeded';
  if (PRIVACY_TOKENS.some((t) => hay.includes(t))) return 'privacy_blocked';
  const code = Number(f.status);
  if (code === 429) return 'rate_limit';
  if (code === 404 || code === 403) return 'policy_blocked';
  if (code >= 500) return 'server_error';
  if (code >= 400) return 'client_error';
  return 'unknown';
}

export function failureKindExplain(kind: string): string {
  const map: Record<string, string> = {
    privacy_blocked:
      'OpenRouter privacy blocked this route — often the “allow providers that may train on your data” toggle (separate for free vs paid models) at openrouter.ai/settings/privacy. Not a context-size fix.',
    policy_blocked:
      'No endpoint matched your guardrails + data policy. Check “may train on your data” for free/paid models in privacy settings, or use a different model route.',
    context_exceeded:
      'Prompt exceeded the model context window. Shrink RAG (@summarize, fewer chunks) or raise @tokenbudget.',
    rate_limit: 'Transient rate limit — wait and retry; do not shrink context as the first fix.',
    server_error: 'Upstream provider error — retry once or swap the failing model.',
    client_error: 'Bad request — verify model id and prompt shape.',
    timeout: 'Request timed out — retry with fewer parallel models.',
    unknown: 'Unclassified failure — expand a row for the provider message.',
  };
  return map[kind] || map.unknown;
}

export interface RerunSuggestion {
  label: string;
  directive: string;
  reason: string;
}

export function rerunSuggestions(failures: ModelFailure[]): RerunSuggestion[] {
  const kinds = new Set(failures.map((f) => classifyFailureKind(f)));
  const out: RerunSuggestion[] = [];
  if (kinds.has('context_exceeded')) {
    out.push({
      label: 'Re-run with @summarize',
      directive: '@summarize ',
      reason: 'Chairman compresses context before arena queries.',
    });
    out.push({
      label: 'Re-run with lower budget',
      directive: '@tokenbudget 12000 ',
      reason: 'Caps injected context so summarizer kicks in sooner.',
    });
  }
  if (kinds.has('privacy_blocked') || kinds.has('policy_blocked')) {
    out.push({
      label: 'Open privacy settings',
      directive: '',
      reason: 'Enable “may train on your data” for free/paid models at openrouter.ai/settings/privacy, then re-run.',
    });
    out.push({
      label: 'Re-run with paid squad',
      directive: '',
      reason: 'Or switch arena squad away from :free models in Settings, then resend.',
    });
  }
  if (kinds.has('rate_limit')) {
    out.push({
      label: 'Re-run same query',
      directive: '',
      reason: 'Rate limits are usually transient — wait ~30s and retry.',
    });
  }
  if (!out.length && failures.length) {
    out.push({
      label: 'Re-run turn',
      directive: '',
      reason: 'Retry after reviewing failure details below.',
    });
  }
  return out;
}