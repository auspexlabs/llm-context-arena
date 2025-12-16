import { useState, useEffect, forwardRef } from 'react';
import ReactMarkdown from 'react-markdown';
import './Stage1.css';

const Stage1 = forwardRef(function Stage1({ responses, focusedTarget, onActiveChange, inProgressIndex = -1 }, ref) {
  const [activeTab, setActiveTab] = useState(0);
  const [collapsed, setCollapsed] = useState(true);
  const [copyStatus, setCopyStatus] = useState('');

  if (!responses || responses.length === 0) {
    return null;
  }

  useEffect(() => {
    setCollapsed(true);
  }, [responses]);

  useEffect(() => {
    if (!focusedTarget) return;

    // If an explicit index is provided, prefer that so duplicate models across rounds can be selected.
    if (typeof focusedTarget.index === 'number' && focusedTarget.index >= 0 && focusedTarget.index < responses.length) {
      if (focusedTarget.index !== activeTab) {
        setActiveTab(focusedTarget.index);
      }
      return;
    }

    if (focusedTarget.model) {
      const idx = responses.findIndex((r) => {
        if (focusedTarget.role && r.role) {
          return r.model === focusedTarget.model && r.role === focusedTarget.role;
        }
        return r.model === focusedTarget.model;
      });
      if (idx !== -1 && idx !== activeTab) {
        setActiveTab(idx);
      }
    }
  }, [focusedTarget, responses, activeTab]);

  const handleTab = (index) => {
    setActiveTab(index);
    const resp = responses[index];
    onActiveChange &&
      onActiveChange({
        model: resp.model,
        role: resp.role,
        index,
      });
  };

  const handleCopy = async () => {
    const text = responses[activeTab]?.response || '';
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
    <div className="stage stage1" ref={ref}>
      <div className="stage-title-row">
        <h3 className="stage-title">Stage 1: Individual Responses</h3>
        <div className="stage-actions">
          <button className="stage-action-btn" type="button" onClick={() => setCollapsed((v) => !v)}>
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
          <button className="stage-action-btn" type="button" onClick={handleCopy}>
            Copy{copyStatus ? ` (${copyStatus})` : ''}
          </button>
        </div>
      </div>

      <div className="tabs">
        {responses.map((resp, index) => {
          const lineCount = resp.response ? resp.response.split('\n').length : 0;
          return (
            <button
              key={index}
              className={`tab ${activeTab === index ? 'active' : ''}`}
              onClick={() => handleTab(index)}
            >
              {resp.model.split('/')[1] || resp.model}
              {lineCount ? <span className="role-tag" style={{ marginLeft: 6 }}>{lineCount} lines</span> : null}
              {inProgressIndex === index && <span className="role-tag" style={{ marginLeft: 6 }}>running</span>}
            </button>
          );
        })}
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
          Collapsed — click to expand and view the responses.
        </div>
      ) : (
        <div className="tab-content">
          <div className="model-name">
            {responses[activeTab].model}
            {responses[activeTab].role && (
              <span className="role-tag">{responses[activeTab].role}</span>
            )}
          </div>
          <div className="stage-actions spaced">
            <button className="stage-action-btn" type="button" onClick={handleCopy}>
              Copy{copyStatus ? ` (${copyStatus})` : ''}
            </button>
          </div>
          <div className="response-text markdown-content">
            <ReactMarkdown>{responses[activeTab].response}</ReactMarkdown>
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
        </div>
      )}
    </div>
  );
});

export default Stage1;
