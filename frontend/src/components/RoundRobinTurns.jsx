import './RoundRobinTurns.css';

const shortModel = (model) => (model || '').split('/').pop() || model || 'Model';

const parseDraftMeta = (step) => {
  if (step.iteration != null && step.turn != null) {
    return { pass: step.iteration, turn: step.turn };
  }
  const match = String(step.role || '').match(/draft_p(\d+)_t(\d+)/i);
  if (match) {
    return { pass: parseInt(match[1], 10), turn: parseInt(match[2], 10) };
  }
  return { pass: null, turn: null };
};

const preview = (text, limit = 320) => {
  const t = (text || '').trim();
  if (!t) return '';
  return t.length > limit ? `${t.slice(0, limit)}…` : t;
};

export function RoundRobinTurns({ steps = [], expanded = {}, onToggle }) {
  const drafts = (steps || []).filter((s) => String(s.role || '').startsWith('draft_'));
  const chair = (steps || []).find((s) => s.role === 'chair_final');

  if (!drafts.length && !chair) return null;

  return (
    <div className="rr-turns">
      <div className="rr-turns-title">Round Robin turns</div>
      <p className="rr-turns-hint">
        Each model receives the same RAG context plus the latest shared draft from the prior turn.
        Expand a turn to see the full prompt sent to that model.
      </p>

      {drafts.map((step, idx) => {
        const { pass, turn } = parseDraftMeta(step);
        const hadPrior = step.had_prior_draft ?? Boolean(step.prior_draft);
        const prior = step.prior_draft ?? '';
        const isOpen = !!expanded[idx];
        const failed = !step.response?.trim();

        return (
          <div
            key={step.__idx ?? idx}
            className={`rr-turn-card ${failed ? 'rr-turn-failed' : ''}`}
            id={`rr-turn-${step.__idx ?? idx}`}
          >
            <div className="rr-turn-header">
              <span className="rr-turn-order">#{idx + 1}</span>
              {pass != null && (
                <span className="rr-turn-pass">
                  Pass {pass}
                  {turn != null ? ` · Turn ${turn}` : ''}
                </span>
              )}
              <span className="rr-turn-model">{shortModel(step.model)}</span>
              {typeof step.context_tokens === 'number' && (
                <span className="rr-turn-ctx">{step.context_tokens} ctx tokens</span>
              )}
            </div>

            <div className="rr-turn-prior">
              <div className="rr-block-label">Prior draft received</div>
              {hadPrior && prior ? (
                <div className="rr-block-text rr-prior-text">{preview(prior, 600)}</div>
              ) : (
                <div className="rr-block-empty">(none yet) — first turn or prior model failed</div>
              )}
            </div>

            <div className="rr-turn-response">
              <div className="rr-block-label">This model&apos;s draft</div>
              {step.response?.trim() ? (
                <div className="rr-block-text">{preview(step.response, 800)}</div>
              ) : (
                <div className="rr-block-empty">No response (model failed or empty)</div>
              )}
            </div>

            {isOpen && (
              <div className="rr-turn-expanded">
                {step.turn_instruction ? (
                  <div className="rr-expand-block">
                    <div className="rr-block-label">Turn instruction (no RAG)</div>
                    <div className="rr-block-text mono">{step.turn_instruction}</div>
                  </div>
                ) : null}
                {step.prompt_full ? (
                  <div className="rr-expand-block">
                    <div className="rr-block-label">Full prompt (RAG + turn)</div>
                    <div className="rr-block-text mono">{step.prompt_full}</div>
                  </div>
                ) : null}
              </div>
            )}

            <button
              type="button"
              className="rr-turn-toggle"
              onClick={() => onToggle && onToggle(step.__idx ?? idx)}
            >
              {isOpen ? 'Collapse' : 'Show full prompt'}
            </button>
          </div>
        );
      })}

      {chair ? (
        <div className="rr-turn-card rr-chair-card">
          <div className="rr-turn-header">
            <span className="rr-turn-order">Final</span>
            <span className="rr-turn-model">{shortModel(chair.model)}</span>
            <span className="rr-turn-pass">Chair synthesis</span>
          </div>
          <div className="rr-turn-response">
            <div className="rr-block-label">Chairman answer</div>
            <div className="rr-block-text">{preview(chair.response, 1200)}</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}