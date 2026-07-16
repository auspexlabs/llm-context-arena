import { executionTrace } from './execution-trace';
import type { AssistantMessage, ModeProgress } from './types';

interface StepLike {
  role?: string;
  model?: string;
  response?: string;
  prior_draft?: string;
}

export interface PulseView {
  modeLabel: string;
  signalLabel: string;
  signalValue: string;
  detail: string;
  applicability: string;
  tone: 'ok' | 'warn' | 'bad' | 'neutral';
  targetView: 'answers' | 'rankings' | 'quality';
}

function countRole(steps: StepLike[], predicate: (role: string) => boolean) {
  return steps.filter((step) => predicate(String(step.role || '')) && String(step.response || '').trim()).length;
}

function lexicalSimilarity(left: string, right: string): number {
  const tokens = (value: string) => new Set(value.toLowerCase().match(/[a-z0-9_./-]+/g) || []);
  const a = tokens(left);
  const b = tokens(right);
  if (!a.size || !b.size) return 0;
  let intersection = 0;
  a.forEach((token) => { if (b.has(token)) intersection += 1; });
  return intersection / (a.size + b.size - intersection);
}

function nearCopyRefinements(steps: StepLike[]): number {
  return steps.filter((step) =>
    String(step.role || '').startsWith('draft_') &&
    String(step.prior_draft || '').trim() &&
    String(step.response || '').trim() &&
    lexicalSimilarity(String(step.prior_draft), String(step.response)) >= 0.94
  ).length;
}

function rankingAgreement(msg: AssistantMessage | undefined) {
  const aggregate = (msg?.metadata?.aggregate_rankings as Record<string, unknown>[] | undefined) || [];
  const spreads = aggregate
    .map((entry) => {
      const values = (entry.rank_positions as number[] | undefined) || [];
      if (values.length < 2) return null;
      const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
      return Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / values.length);
    })
    .filter((value): value is number => value != null);
  if (!spreads.length) return null;
  const meanSpread = spreads.reduce((sum, value) => sum + value, 0) / spreads.length;
  if (meanSpread <= 0.35) return { label: 'High agreement', tone: 'ok' as const, spread: meanSpread };
  if (meanSpread <= 0.8) return { label: 'Mixed agreement', tone: 'warn' as const, spread: meanSpread };
  return { label: 'High disagreement', tone: 'bad' as const, spread: meanSpread };
}

export function buildPulse(
  msg: AssistantMessage | undefined,
  mode: string,
  running: boolean,
  progress: ModeProgress
): PulseView {
  const meta = msg?.metadata || {};
  const trace = executionTrace(msg, mode);
  const steps = (meta.steps as StepLike[] | undefined) || [];
  const succeededRoles = trace?.steps.filter((step) => step.status === 'succeeded').map((step) => step.role) || [];
  const countSucceededRole = (predicate: (role: string) => boolean) => succeededRoles.filter(predicate).length;
  const failures = ((meta.model_failures as unknown[] | undefined) || []).length;
  const quality = meta.execution_quality as Record<string, unknown> | undefined;
  const qualityDetail = quality
    ? `${String(quality.severity || 'ok')} quality${failures ? ` · ${failures} failure${failures === 1 ? '' : 's'}` : ''}`
    : failures
      ? `${failures} recorded failure${failures === 1 ? '' : 's'}`
      : running
        ? progress.label || 'Deliberation in progress'
        : 'Quality metadata unavailable';

  if (mode === 'council' || mode === 'baseline') {
    const agreement = rankingAgreement(msg);
    const answers = msg?.stage1?.length || 0;
    const rankings = msg?.stage2?.length || 0;
    return {
      modeLabel: mode === 'baseline' ? 'Baseline council' : 'Council',
      signalLabel: 'Peer agreement',
      signalValue: agreement?.label || (rankings ? 'Insufficient ranking spread' : 'Awaiting rankings'),
      detail: `${answers} answer${answers === 1 ? '' : 's'} · ${rankings} ranking${rankings === 1 ? '' : 's'} · ${qualityDetail}`,
      applicability: agreement
        ? `Comparable independent positions; mean rank spread ${agreement.spread.toFixed(2)}.`
        : 'Agreement appears only after at least two peers rank comparable independent answers.',
      tone: agreement?.tone || (failures ? 'bad' : 'neutral'),
      targetView: rankings ? 'rankings' : 'answers',
    };
  }

  if (mode === 'fight') {
    const answers = countSucceededRole((role) => role === 'answer');
    const critiques = countSucceededRole((role) => role === 'critique');
    const defenses = countSucceededRole((role) => role === 'defense');
    return {
      modeLabel: 'Fight',
      signalLabel: 'Adversarial coverage',
      signalValue: `${answers} / ${critiques} / ${defenses}`,
      detail: `answers / critiques / defenses · ${qualityDetail}`,
      applicability: 'Agreement is intentionally not inferred: opposition and defended revision are the useful signals.',
      tone: failures ? 'bad' : defenses && critiques ? 'ok' : 'neutral',
      targetView: failures ? 'quality' : 'answers',
    };
  }

  if (mode === 'round_robin') {
    const expected = trace?.summary.drafts_expected ?? steps.filter((step) => String(step.role || '').startsWith('draft_')).length;
    const drafts = trace?.summary.drafts_succeeded ?? countRole(steps, (role) => role.startsWith('draft_'));
    const refinements = trace?.summary.successful_refinements ?? Math.max(0, drafts - 1);
    const deliveries = trace?.summary.handoff_deliveries ?? Math.max(0, expected - 1);
    const nearCopies = nearCopyRefinements(steps);
    const changed = Math.max(0, refinements - nearCopies);
    const passes = Number(meta.iterations || 1);
    return {
      modeLabel: 'Round robin',
      signalLabel: 'Refinement chain',
      signalValue: nearCopies
        ? `${changed} changed · ${nearCopies} ${nearCopies === 1 ? 'near-copy' : 'near-copies'}`
        : `${refinements} completed refinement call${refinements === 1 ? '' : 's'}`,
      detail: `${drafts}/${expected} drafts · ${deliveries} handoff deliver${deliveries === 1 ? 'y' : 'ies'} · ${passes} pass${passes === 1 ? '' : 'es'} · ${qualityDetail}`,
      applicability: nearCopies
        ? 'Completion means the model returned output; near-copy is a deterministic lexical-overlap warning, not proof of added value.'
        : 'No consensus score: each draft depends on the previous draft, so positions are not independent.',
      tone: failures ? 'bad' : nearCopies ? 'warn' : refinements || drafts === 1 ? 'ok' : 'neutral',
      targetView: failures ? 'quality' : 'answers',
    };
  }

  if (mode === 'stacks') {
    const branches = countSucceededRole((role) => role === 'stacks_answer');
    const reviews = countSucceededRole((role) => role === 'stacks_critique' || role === 'stacks_defense');
    const judged = countSucceededRole((role) => role === 'stacks_judge');
    return {
      modeLabel: 'Stacks',
      signalLabel: 'Branch coverage',
      signalValue: `${branches} branches · ${reviews} reviews`,
      detail: `${judged ? 'Judge complete' : 'Awaiting judge'} · ${qualityDetail}`,
      applicability: 'No consensus score: branches are merged, selected, and defended rather than peer-ranked as equals.',
      tone: failures ? 'bad' : judged ? 'ok' : 'neutral',
      targetView: failures ? 'quality' : 'answers',
    };
  }

  if (mode === 'complex_iterative') {
    const extracts = countSucceededRole((role) => role === 'extract');
    const expands = countSucceededRole((role) => role === 'expand');
    return {
      modeLabel: 'Extract / expand',
      signalLabel: 'Iteration progress',
      signalValue: `${extracts} extracts · ${expands} expansions`,
      detail: qualityDetail,
      applicability: 'No consensus score: the useful signal is completion and continuity across dependent transformations.',
      tone: failures ? 'bad' : extracts && expands ? 'ok' : 'neutral',
      targetView: failures ? 'quality' : 'answers',
    };
  }

  if (mode === 'complex_questioning') {
    const answers = countSucceededRole((role) => role === 'answer');
    const questions = countSucceededRole((role) => role === 'question_self');
    const muses = countSucceededRole((role) => role === 'muse');
    return {
      modeLabel: 'Complex questioning',
      signalLabel: 'Reflection coverage',
      signalValue: `${answers} answers · ${questions} questions · ${muses} muses`,
      detail: qualityDetail,
      applicability: 'No consensus score: self-questioning and post-brief reflection are dependent stages.',
      tone: failures ? 'bad' : muses ? 'ok' : 'neutral',
      targetView: failures ? 'quality' : 'answers',
    };
  }

  return {
    modeLabel: mode || 'Unknown mode',
    signalLabel: 'Mode pulse unavailable',
    signalValue: progress.label || 'Raw telemetry only',
    detail: qualityDetail,
    applicability: 'Curia has no defensible derived signal for this mode; quality and raw step telemetry remain authoritative.',
    tone: failures ? 'bad' : 'neutral',
    targetView: 'quality',
  };
}
