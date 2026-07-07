import { formatTokenCount, formatUsd, turnCostFromMessage } from '../costUtils';
import './TurnCostLine.css';

export default function TurnCostLine({ message }) {
  const cost = turnCostFromMessage(message);
  if (!cost.calls && !cost.cost_usd && !cost.total_tokens) return null;

  return (
    <div className="turn-cost-line" aria-label="Turn usage">
      <span className="turn-cost-heading">Usage</span>
      <span>{formatUsd(cost.cost_usd)}</span>
      <span className="turn-cost-sep">·</span>
      <span>{cost.calls} call{cost.calls === 1 ? '' : 's'}</span>
      <span className="turn-cost-sep">·</span>
      <span>{formatTokenCount(cost.total_tokens)} tokens</span>
      <span className="turn-cost-muted">
        ({formatTokenCount(cost.prompt_tokens)} in / {formatTokenCount(cost.completion_tokens)} out)
      </span>
    </div>
  );
}