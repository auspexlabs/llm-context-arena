export type CouncilStepId = 'answers' | 'rankings' | 'verdict';

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
  takeControl: boolean;
  isRunning: boolean;
  modeProgress: ModeProgress;
  theme: 'light' | 'dark';
  settingsOpen: boolean;
}