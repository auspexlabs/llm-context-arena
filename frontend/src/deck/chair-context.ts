import type { AssistantMessage } from './types';

const STAGE1_MARKER = 'User question:\n';

const CHAIR_TEMPLATE = (
  userQuery: string,
  stage1Text: string,
  stage2Text: string
) => `You are the Chairman of an LLM Arena. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: ${userQuery}

STAGE 1 - Individual Responses:
${stage1Text}

STAGE 2 - Peer Rankings:
${stage2Text}

First, briefly summarize what you saw in each stage (2 sentences or a short paragraph per item), covering the key points of each response and ranking. Label this section "What I saw".

Then, provide the final answer to the original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the arena's collective wisdom:`;

export interface ContextInjections {
  contextFromLastChair: boolean;
  summarizeTargets: Record<string, number>;
  summarizeJobCount: number;
  forceSummarize: boolean;
  useLastChair: boolean;
  skipRag: boolean;
  budgetOverride: number | null;
  chairmanModel: string | null;
}

export function buildContextInjections(msg: AssistantMessage | null): ContextInjections {
  const meta = msg?.metadata || {};
  const directives = (meta.directives as Record<string, unknown>) || {};
  const targets = (meta.summarize_targets as Record<string, number>) || {};
  const jobs = (meta.summarize_jobs as unknown[]) || [];

  return {
    contextFromLastChair: Boolean(meta.context_from_last_chair),
    summarizeTargets: targets,
    summarizeJobCount: jobs.length,
    forceSummarize: Boolean(directives.force_summarize),
    useLastChair: Boolean(directives.use_last_chair),
    skipRag: Boolean(directives.skip_rag),
    budgetOverride:
      directives.budget_override != null ? Number(directives.budget_override) : null,
    chairmanModel: (meta.chairman_model as string) || null,
  };
}

export function extractEmbeddedUserQuery(stage1PromptFull: string | null | undefined): string | null {
  if (!stage1PromptFull) return null;
  const idx = stage1PromptFull.indexOf(STAGE1_MARKER);
  if (idx >= 0) return stage1PromptFull.slice(idx + STAGE1_MARKER.length).trim();
  return stage1PromptFull.trim();
}

/** Resolve full stage-3 chair prompt — stored, steps metadata, or reconstructed from stage 1/2. */
export function resolveChairmanPrompt(msg: AssistantMessage | null): {
  text: string | null;
  source: 'stored' | 'steps' | 'reconstructed' | 'preview_only';
} {
  if (!msg) return { text: null, source: 'preview_only' };

  const s3 = msg.stage3 as { prompt_full?: string; prompt_preview?: string } | null | undefined;
  if (s3?.prompt_full) return { text: s3.prompt_full, source: 'stored' };

  const steps = msg.metadata?.steps as Array<{ role?: string; prompt_full?: string }> | undefined;
  const chairStep = steps?.find((s) => s.role === 'chair_final' || s.role === 'chair');
  if (chairStep?.prompt_full) return { text: chairStep.prompt_full, source: 'steps' };

  const stage1 = msg.stage1 || [];
  const stage2 = msg.stage2 || [];
  if (stage1.length) {
    const first = stage1[0] as { prompt_full?: string };
    const embedded = extractEmbeddedUserQuery(first.prompt_full);
    if (embedded) {
      const stage1Text = stage1
        .map((r) => `Model: ${r.model}\nResponse: ${r.response || ''}`)
        .join('\n\n');
      const stage2Text = stage2
        .map((r) => `Model: ${r.model}\nRanking: ${r.ranking || ''}`)
        .join('\n\n');
      return {
        text: CHAIR_TEMPLATE(embedded, stage1Text, stage2Text),
        source: 'reconstructed',
      };
    }
  }

  if (s3?.prompt_preview) return { text: s3.prompt_preview, source: 'preview_only' };
  return { text: null, source: 'preview_only' };
}