import type { AssistantMessage } from './types';

const CHAIRMAN_ERROR = 'Error: Unable to generate final synthesis.';

export function isSynthesisFailed(msg: AssistantMessage | null): boolean {
  const s3 = msg?.stage3 as (AssistantMessage['stage3'] & { synthesis_failed?: boolean }) | null;
  if (!s3) return false;
  if (s3.synthesis_failed) return true;
  const resp = (s3.response || '').trim();
  return resp === CHAIRMAN_ERROR || resp.startsWith(CHAIRMAN_ERROR);
}

export function executionSeverity(
  msg: AssistantMessage | null
): 'ok' | 'degraded' | 'failed' | null {
  const q = msg?.metadata?.execution_quality as { severity?: string } | undefined;
  return (q?.severity as 'ok' | 'degraded' | 'failed') || null;
}