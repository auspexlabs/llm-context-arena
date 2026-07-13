import { userQueryBefore } from '../normalize';
import { buildTurnContext } from '../turn-context';
import { isPendingTurnSelected } from '../turns';
import type {
  AgentTurnSnapshot,
  AssistantMessage,
  Conversation,
  DeckView,
  ModeProgress,
  PendingTurn,
} from '../types';
import { renderContextViewport } from './context';
import { renderCouncilViewport } from './council';
import { renderProgressViewport } from './progress';
import { renderQualityViewport } from './quality';

export function renderDeckViewport(
  container: HTMLElement,
  view: DeckView,
  conversation: Conversation | null,
  msg: AssistantMessage | null,
  turnIndex: number,
  isRunning: boolean,
  pendingTurn: PendingTurn | null = null,
  activeAgentTurn: AgentTurnSnapshot | null = null,
  modeProgress: ModeProgress = { current: 0, total: 0, label: '' }
) {
  const assistantCount = conversation?.messages.filter((m) => m.role === 'assistant').length ?? 0;
  if (isPendingTurnSelected(turnIndex, assistantCount, pendingTurn) && pendingTurn) {
    renderProgressViewport(container, pendingTurn, activeAgentTurn, modeProgress);
    return;
  }

  if (!msg) {
    container.innerHTML = '<p class="empty-state">Select a turn to inspect deliberation.</p>';
    return;
  }

  if (view === 'context') {
    renderContextViewport(container, buildTurnContext(conversation, msg, turnIndex), msg);
    return;
  }

  if (view === 'quality') {
    const userQuery = userQueryBefore(conversation?.messages || [], turnIndex);
    renderQualityViewport(container, msg, userQuery);
    return;
  }

  renderCouncilViewport(container, msg, view, isRunning);
}