export type CouncilStepId = 'answers' | 'rankings' | 'verdict';

/** Deck viewport — council steps plus inspector-linked panels. */
export type DeckView = 'context' | CouncilStepId | 'quality';

export type InspectorColumn = 'context' | 'rankings' | 'quality';

export type TurnStatus = 'running' | 'complete' | 'idle' | 'failed';

export type WorkspaceView = 'turns' | 'sessions';

export interface ConversationSummary {
  id: string;
  title?: string;
  mode?: string;
  message_count: number;
  created_at?: string;
  total_cost_usd?: number;
  total_tokens?: number;
  arena_models?: string[];
  chairman_model?: string | null;
  squad_fingerprint?: string;
}

export interface SessionSummary extends ConversationSummary {
  updated_at: string;
  origin: string;
  originator: string;
  last_caller: string;
  turn_count: number;
  status: string;
  latest_quality: string;
  worst_quality: string;
  total_cost_usd: number;
  total_tokens: number;
  total_calls: number;
  failure_count: number;
  duration_ms: number;
  squad_name: string;
  squad_fingerprint: string;
  arena_models: string[];
  chairman_model: string;
  rag_used: boolean;
  repository: string;
}

export interface SessionFacets {
  modes: string[];
  callers: string[];
  origins: string[];
  statuses: string[];
  qualities: string[];
  squads: string[];
}

export interface SessionFilters {
  [key: string]: string | undefined;
  mode?: string;
  caller?: string;
  origin?: string;
  status?: string;
  quality?: string;
  squad?: string;
  from?: string;
  to?: string;
}

export interface SessionPage {
  items: SessionSummary[];
  next_cursor: string | null;
  total: number;
  facets: SessionFacets;
  sort: 'updated_desc' | 'created_desc' | 'cost_desc';
}

export interface ModelResponse {
  model: string;
  response?: string;
  role?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost_usd?: number;
  duration_ms?: number;
  prompt_preview?: string;
  prompt_full?: string;
  orchestration_text?: string;
  prompt_provenance?: PromptProvenance;
  context_tokens?: number;
  est_tokens?: number;
  ranking?: string;
  iteration?: number;
  turn?: number;
  had_prior_draft?: boolean;
  prior_draft?: string | null;
}

export interface RankingEntry {
  model: string;
  ranking?: string;
  parsed_ranking?: string[] | null;
  role?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost_usd?: number;
  duration_ms?: number;
  orchestration_text?: string;
  prompt_provenance?: PromptProvenance;
}

export interface AssistantMessage {
  role: 'assistant';
  stage1?: ModelResponse[] | null;
  stage2?: RankingEntry[] | null;
  stage3?: ModelResponse | null;
  metadata?: Record<string, unknown> | null;
  contextSources?: unknown[] | null;
  loading?: { stage1?: boolean; stage2?: boolean; stage3?: boolean };
}

export type TraceStepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped';

export interface TraceStepSource {
  collection: 'stage1' | 'stage2' | 'stage3' | 'metadata.steps';
  index: number;
}

export interface TraceFailure {
  status?: number;
  message?: string;
  provider?: string;
  failure_kind?: string;
}

export interface PromptProvenancePart {
  kind: 'text' | 'context_ref' | 'artifact_ref';
  text?: string;
  label?: string;
  target?: 'rag' | 'answers' | string;
  artifact_id?: string | null;
  producer?: { role?: string; model?: string };
  producer_step_id?: string;
  producer_status?: TraceStepStatus;
}

export interface PromptProvenance {
  version: number;
  parts: PromptProvenancePart[];
}

export interface TraceStep {
  step_id: string;
  ordinal: number;
  kind: string;
  role: string;
  model: string;
  status: TraceStepStatus;
  terminal: boolean;
  source: TraceStepSource | null;
  iteration?: number | null;
  position?: number | null;
  predecessor_step_ids: string[];
  input_artifact_ids: string[];
  output_artifact_id?: string | null;
  prompt_input_artifact_ids?: string[];
  prompt_provenance?: PromptProvenance;
  failure?: TraceFailure;
}

export interface TraceSummary {
  planned_steps: number;
  attempted_steps: number;
  succeeded_steps: number;
  failed_steps: number;
  arena_steps: number;
  arena_succeeded_steps: number;
  arena_failed_steps: number;
  participant_expected: number;
  participant_succeeded: number;
  participant_failed: number;
  drafts_expected: number;
  drafts_succeeded: number;
  successful_refinements: number;
  handoff_deliveries: number;
  final_status: string;
}

export interface ExecutionTrace {
  version: number;
  mode: string;
  steps: TraceStep[];
  artifacts: Array<Record<string, unknown>>;
  edges: Array<{ from_step_id: string; to_step_id: string; artifact_id: string }>;
  summary: TraceSummary;
  legacy?: boolean;
}

export interface UserMessage {
  role: 'user';
  content: string;
}

export type Message = UserMessage | AssistantMessage;

export interface Conversation {
  id: string;
  mode?: string;
  title?: string;
  messages: Message[];
}

export interface ModeProgress {
  current: number;
  total: number;
  label: string;
  activeModel?: string | null;
  state?: string;
}

/** Agent turn sidecar snapshot (create_turn / advance_turn path). */
export interface AgentTurnSnapshot {
  turn_id: string;
  status: string;
  step_index: number;
  step_total: number;
  next_step?: string | null;
  user_query?: string;
  agent_id?: string | null;
}

/** Turn awaiting assistant message (MCP send_message or orphan user msg). */
export interface PendingTurn {
  turnIndex: number;
  userQuery: string;
  source: 'external' | 'local';
  startedAt?: number;
}

export interface StepRuntime {
  startedAt: number | null;
  endedAt: number | null;
}

export interface TurnRuntime {
  turnIndex: number;
  startedAt: number;
  currentStep: 'stage1' | 'stage2' | 'stage3' | null;
  steps: Record<'stage1' | 'stage2' | 'stage3', StepRuntime>;
}

export interface TurnView {
  index: number;
  status: TurnStatus;
  userQuery: string;
  assistant: AssistantMessage;
  costUsd: number;
  totalTokens: number;
}

export interface DeckState {
  workspaceView: WorkspaceView;
  conversations: ConversationSummary[];
  sessions: SessionSummary[];
  sessionFacets: SessionFacets;
  sessionFilters: SessionFilters;
  sessionSort: 'updated_desc' | 'created_desc' | 'cost_desc';
  sessionNextCursor: string | null;
  sessionTotal: number;
  sessionsLoading: boolean;
  sessionsError: string | null;
  conversationId: string | null;
  conversation: Conversation | null;
  selectedTurnIndex: number;
  focusedStep: CouncilStepId;
  deckView: DeckView;
  inspectorColumn: InspectorColumn;
  ragListExpanded: boolean;
  ragChunksExpanded: string[];
  /** Stage-1 model index whose prompt is shown in Context view (-1 = shared/first). */
  contextPromptModel: number;
  /** Injection-workflow node whose exact persisted payload is open in the modal. */
  contextInjectionSelection: string | null;
  /** Canonical trace step selected through an artifact-reference link. */
  focusedTraceStepId: string | null;
  /** Arena-addition disclosures the user has opened for the selected turn. */
  contextAdditivesExpanded: string[];
  failuresExpanded: string[];
  takeControl: boolean;
  isRunning: boolean;
  modeProgress: ModeProgress;
  /** Active agent turn from sidecar API, if any. */
  activeAgentTurn: AgentTurnSnapshot | null;
  /** User message without matching assistant (external MCP run). */
  pendingTurn: PendingTurn | null;
  /** User manually picked a session — suppress auto-switch on new MCP sessions. */
  sessionPinned: boolean;
  /** Conversation ids surfaced since last poll (badge in rail). */
  newSessionIds: string[];
  pollError: string | null;
  turnRuntime: TurnRuntime | null;
  /** Bumped every second while a turn is running (drives live timers). */
  runtimeTick: number;
  theme: 'light' | 'dark';
  settingsOpen: boolean;
}
