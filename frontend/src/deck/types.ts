export type CouncilStepId = 'answers' | 'rankings' | 'verdict';

/** Deck viewport — council steps plus inspector-linked panels. */
export type DeckView = 'context' | CouncilStepId | 'quality';

export type InspectorColumn = 'context' | 'rankings' | 'quality';

export type TurnStatus = 'running' | 'complete' | 'idle';

export interface ConversationSummary {
  id: string;
  title?: string;
  mode?: string;
  message_count: number;
  created_at?: string;
  total_cost_usd?: number;
  total_tokens?: number;
}

export interface ModelResponse {
  model: string;
  response?: string;
  role?: string;
}

export interface RankingEntry {
  model: string;
  ranking?: string;
  parsed_ranking?: string[] | null;
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
  conversations: ConversationSummary[];
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