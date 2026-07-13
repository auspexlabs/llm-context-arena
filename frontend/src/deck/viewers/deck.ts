import { userQueryBefore } from '../normalize';
import { buildTurnContext } from '../turn-context';
import type { AssistantMessage, Conversation, DeckView } from '../types';
import { renderContextViewport } from './context';
import { renderCouncilViewport } from './council';
import { renderQualityViewport } from './quality';

export function renderDeckViewport(
  container: HTMLElement,
  view: DeckView,
  conversation: Conversation | null,
  msg: AssistantMessage | null,
  turnIndex: number,
  isRunning: boolean
) {
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