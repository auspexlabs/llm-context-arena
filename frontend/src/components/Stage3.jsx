import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import './Stage3.css';

export default function Stage3({ finalResponse }) {
  if (!finalResponse) {
    return null;
  }

  const [collapsed, setCollapsed] = useState(true);
  const [copyStatus, setCopyStatus] = useState('');

  useEffect(() => {
    setCollapsed(true);
  }, [finalResponse]);

  const handleCopy = async () => {
    const text = finalResponse?.response || '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus('Copied');
      setTimeout(() => setCopyStatus(''), 1200);
    } catch (err) {
      console.error('Copy failed', err);
      setCopyStatus('Copy failed');
      setTimeout(() => setCopyStatus(''), 1500);
    }
  };

  return (
    <div className="stage stage3">
      <div className="stage-title-row">
        <h3 className="stage-title">Stage 3: Final Arena Answer</h3>
        <div className="stage-actions">
          <button className="stage-action-btn" type="button" onClick={() => setCollapsed((v) => !v)}>
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
          <button className="stage-action-btn" type="button" onClick={handleCopy}>
            Copy{copyStatus ? ` (${copyStatus})` : ''}
          </button>
        </div>
      </div>
      <div className="final-response">
        <div className="chairman-label">
          Chairman: {finalResponse.model.split('/')[1] || finalResponse.model}
        </div>
        {collapsed ? (
          <div
            className="collapsed-note"
            role="button"
            tabIndex={0}
            onClick={() => setCollapsed(false)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setCollapsed(false);
              }
            }}
          >
            Collapsed — click to expand and view the final answer.
          </div>
        ) : (
          <>
            <div className="stage-actions spaced">
              <button className="stage-action-btn" type="button" onClick={handleCopy}>
                Copy{copyStatus ? ` (${copyStatus})` : ''}
              </button>
            </div>
            <div className="final-text markdown-content">
              <ReactMarkdown>{finalResponse.response}</ReactMarkdown>
            </div>
            <div className="stage-actions spaced bottom">
              <button className="stage-action-btn" type="button" onClick={handleCopy}>
                Copy{copyStatus ? ` (${copyStatus})` : ''}
              </button>
              <button
                className="stage-action-btn"
                type="button"
                onClick={() => setCollapsed(true)}
              >
                Collapse
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
