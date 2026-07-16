import type {
  AssistantMessage,
  ExecutionTrace,
  ModelResponse,
  TraceStep,
  TraceStepSource,
} from './types';

export type TracePayload = ModelResponse & Record<string, unknown>;

interface FailureLike {
  model?: string;
  role?: string;
  stage?: string;
  status?: number;
  message?: string;
  provider?: string;
  failure_kind?: string;
}

const TERMINAL = new Set(['chair', 'chair_final', 'verdict']);

function hasOutput(payload: TracePayload | undefined) {
  return Boolean(String(payload?.response || payload?.ranking || '').trim());
}

function kindFor(role: string) {
  if (role.startsWith('draft_')) return 'draft';
  if (TERMINAL.has(role)) return 'verdict';
  if (role === 'rankings' || role === 'ranking') return 'ranking';
  if (role.startsWith('stacks_')) return role.replace(/^stacks_/, '');
  return role || 'step';
}

function failureFor(failures: FailureLike[], model: string, role: string) {
  const aliases: Record<string, string[]> = {
    answer: ['answer', 'stage1'],
    rankings: ['rankings', 'ranking', 'stage2'],
    chair_final: ['chair_final', 'chair', 'stage3'],
  };
  return failures.find((failure) => {
    if (failure.model !== model) return false;
    const labels = [String(failure.role || ''), String(failure.stage || '')];
    return labels.some((label) => label === role || (aliases[role] || [role]).includes(label));
  });
}

function payloadRows(msg: AssistantMessage, mode: string) {
  if (mode === 'council' || mode === 'baseline') {
    return [
      ...(msg.stage1 || []).map((payload, index) => ({
        payload: payload as TracePayload,
        role: 'answer',
        source: { collection: 'stage1', index } as TraceStepSource,
      })),
      ...(msg.stage2 || []).map((payload, index) => ({
        payload: payload as TracePayload,
        role: 'rankings',
        source: { collection: 'stage2', index } as TraceStepSource,
      })),
      ...(msg.stage3 ? [{
        payload: msg.stage3 as TracePayload,
        role: 'chair_final',
        source: { collection: 'stage3', index: 0 } as TraceStepSource,
      }] : []),
    ];
  }
  const steps = (msg.metadata?.steps as TracePayload[] | undefined) || [];
  return steps.map((payload, index) => ({
    payload,
    role: String(payload.role || `step_${index + 1}`),
    source: { collection: 'metadata.steps', index } as TraceStepSource,
  }));
}

function legacyTrace(msg: AssistantMessage, mode: string): ExecutionTrace {
  const failures = (msg.metadata?.model_failures as FailureLike[] | undefined) || [];
  const rows = payloadRows(msg, mode);
  const nodes: TraceStep[] = rows.map((row, index) => {
    const model = String(row.payload.model || '');
    const failure = failureFor(failures, model, row.role);
    return {
      step_id: `legacy-step-${index + 1}`,
      ordinal: index + 1,
      kind: kindFor(row.role),
      role: row.role,
      model,
      status: hasOutput(row.payload) && !failure ? 'succeeded' : 'failed',
      terminal: TERMINAL.has(row.role),
      source: row.source,
      iteration: Number(row.payload.iteration) || null,
      position: Number(row.payload.turn) || null,
      predecessor_step_ids: [],
      input_artifact_ids: ['user-query'],
      output_artifact_id: null,
      ...(failure ? { failure: {
        status: failure.status,
        message: failure.message,
        provider: failure.provider,
        failure_kind: failure.failure_kind,
      } } : {}),
    };
  });

  if (mode === 'round_robin' || mode === 'complex_iterative') {
    let lastSuccess: string | null = null;
    for (const node of nodes) {
      if (lastSuccess) node.predecessor_step_ids = [lastSuccess];
      if (node.status === 'succeeded' && !node.terminal) lastSuccess = node.step_id;
    }
  } else {
    let lastSuccess: string | null = null;
    for (const node of nodes) {
      if (lastSuccess && node.kind !== 'answer') node.predecessor_step_ids = [lastSuccess];
      if (node.status === 'succeeded' && !node.terminal) lastSuccess = node.step_id;
    }
  }
  for (const node of nodes) {
    node.input_artifact_ids.push(...node.predecessor_step_ids.map((id) => `${id}:output`));
    if (node.status === 'succeeded') node.output_artifact_id = `${node.step_id}:output`;
  }

  const arena = nodes.filter((node) => !node.terminal);
  const models = (msg.metadata?.arena_models as string[] | undefined) || [];
  const succeededModels = new Set(arena.filter((node) => node.status === 'succeeded').map((node) => node.model));
  const failedModels = new Set(
    models.filter((model) => !succeededModels.has(model) && arena.some((node) => node.model === model && node.status === 'failed'))
  );
  const drafts = arena.filter((node) => node.kind === 'draft');
  return {
    version: 0,
    mode,
    steps: nodes,
    artifacts: [],
    edges: nodes.flatMap((node) => node.predecessor_step_ids.map((parent) => ({
      from_step_id: parent,
      to_step_id: node.step_id,
      artifact_id: `${parent}:output`,
    }))),
    summary: {
      planned_steps: nodes.length,
      attempted_steps: nodes.length,
      succeeded_steps: nodes.filter((node) => node.status === 'succeeded').length,
      failed_steps: nodes.filter((node) => node.status === 'failed').length,
      arena_steps: arena.length,
      arena_succeeded_steps: arena.filter((node) => node.status === 'succeeded').length,
      arena_failed_steps: arena.filter((node) => node.status === 'failed').length,
      participant_expected: models.length || new Set(arena.map((node) => node.model)).size,
      participant_succeeded: succeededModels.size,
      participant_failed: failedModels.size,
      drafts_expected: drafts.length,
      drafts_succeeded: drafts.filter((node) => node.status === 'succeeded').length,
      successful_refinements: drafts.filter((node) => node.status === 'succeeded' && node.predecessor_step_ids.length).length,
      handoff_deliveries: drafts.filter((node) => node.predecessor_step_ids.length).length,
      final_status: nodes.filter((node) => node.terminal).at(-1)?.status || 'missing',
    },
    legacy: true,
  };
}

export function executionTrace(msg: AssistantMessage | undefined, mode = 'council'): ExecutionTrace | null {
  if (!msg) return null;
  const stored = msg.metadata?.execution_trace as ExecutionTrace | undefined;
  if (stored?.version && Array.isArray(stored.steps) && stored.summary) return stored;
  return legacyTrace(msg, mode);
}

export function tracePayload(msg: AssistantMessage, node: TraceStep): TracePayload | null {
  const source = node.source;
  if (!source) return null;
  if (source.collection === 'stage1') return (msg.stage1?.[source.index] as TracePayload | undefined) || null;
  if (source.collection === 'stage2') return (msg.stage2?.[source.index] as TracePayload | undefined) || null;
  if (source.collection === 'stage3') return (msg.stage3 as TracePayload | undefined) || null;
  const steps = (msg.metadata?.steps as TracePayload[] | undefined) || [];
  return steps[source.index] || null;
}

export function traceStepById(trace: ExecutionTrace, stepId: string) {
  return trace.steps.find((node) => node.step_id === stepId) || null;
}

export function traceRows(msg: AssistantMessage, mode: string, includeTerminal = true) {
  const trace = executionTrace(msg, mode);
  if (!trace) return [];
  return trace.steps
    .filter((node) => includeTerminal || !node.terminal)
    .map((node) => ({ node, payload: tracePayload(msg, node) }));
}
