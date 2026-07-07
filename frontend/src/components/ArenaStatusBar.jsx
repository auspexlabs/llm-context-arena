import './ArenaStatusBar.css';
import { formatTokenCount, formatUsd } from '../costUtils';

function Metric({ label, value, detail }) {
  return (
    <div className="arena-metric">
      <span className="arena-metric-label">{label}</span>
      <span className="arena-metric-value">{value}</span>
      {detail ? <span className="arena-metric-detail">{detail}</span> : null}
    </div>
  );
}

export default function ArenaStatusBar({
  mode,
  title,
  isLoading,
  modeProgress,
  progressLabel,
  turnCost,
  sessionCost,
}) {
  const progressPct =
    modeProgress?.total > 0
      ? Math.min(100, Math.round(((modeProgress.current || 0) / modeProgress.total) * 100))
      : 0;
  const showProgress = isLoading || (modeProgress?.total > 0 && progressPct < 100);

  return (
    <header className="arena-status-bar" aria-label="Arena execution status">
      <div className="arena-status-row">
        <div className="arena-status-identity">
          <span className="arena-mode-pill">{(mode || 'council').replace(/_/g, ' ')}</span>
          <h2 className="arena-status-title">{title || 'New conversation'}</h2>
          {isLoading ? <span className="arena-live-badge">Live</span> : null}
        </div>

        <div className="arena-metrics" role="group" aria-label="OpenRouter usage">
          <Metric
            label="This turn"
            value={formatUsd(turnCost.cost_usd)}
            detail={
              isLoading
                ? `${turnCost.calls || 0} calls`
                : turnCost.calls
                  ? `${turnCost.calls} calls`
                  : '—'
            }
          />
          <Metric
            label="Session"
            value={formatUsd(sessionCost.cost_usd)}
            detail={`${sessionCost.turns || 0} turn${sessionCost.turns === 1 ? '' : 's'}`}
          />
          <Metric
            label="Tokens"
            value={formatTokenCount(sessionCost.total_tokens)}
            detail={`${formatTokenCount(turnCost.prompt_tokens)} in · ${formatTokenCount(turnCost.completion_tokens)} out`}
          />
          <Metric
            label="API calls"
            value={String(sessionCost.calls || 0)}
            detail={isLoading ? 'accumulating' : 'OpenRouter'}
          />
        </div>
      </div>

      {showProgress ? (
        <div className="arena-status-progress">
          <div className="arena-progress-track" aria-hidden="true">
            <div className="arena-progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="arena-progress-meta">
            <span className="arena-progress-label">
              {progressLabel ||
                (modeProgress?.total
                  ? `Step ${modeProgress.current || 0} / ${modeProgress.total}`
                  : 'Starting…')}
            </span>
            {isLoading && turnCost.cost_usd > 0 ? (
              <span className="arena-progress-cost">
                turn running · {formatUsd(turnCost.cost_usd)}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </header>
  );
}