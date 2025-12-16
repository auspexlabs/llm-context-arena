import { useState, useEffect } from 'react';
import { api } from '../api';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  theme,
  onThemeChange,
  repoRoot,
  onRepoRootChange,
}) {
  const [mode, setMode] = useState('council');
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState({ arena_models: [], chairman_model: '', repo_root: '' });
  const [settingsStatus, setSettingsStatus] = useState('');

  useEffect(() => {
    if (showSettings) {
      api.getSettings()
        .then((data) => {
          setSettings(data);
          if (data?.theme) {
            onThemeChange && onThemeChange(data.theme);
          }
          if (data?.repo_root) {
            setSettings((prev) => ({ ...prev, repo_root: data.repo_root }));
            onRepoRootChange && onRepoRootChange(data.repo_root);
          }
          if (data?.repo_root === undefined && repoRoot) {
            setSettings((prev) => ({ ...prev, repo_root: repoRoot }));
          }
        })
        .catch(() => setSettingsStatus('Failed to load settings'));
    }
  }, [showSettings, repoRoot, onRepoRootChange, onThemeChange]);

  const handleNew = () => {
    onNewConversation(mode);
  };

  const handleSettingsSave = async () => {
    try {
      setSettingsStatus('Saving...');
      const payload = {
        arena_models: settings.arena_models,
        chairman_model: settings.chairman_model,
        theme: settings.theme || theme,
        repo_root: settings.repo_root,
      };
      const saved = await api.updateSettings(payload);
      setSettings(saved);
      if (saved?.theme) {
        onThemeChange && onThemeChange(saved.theme);
      }
      if (saved?.repo_root) {
        onRepoRootChange && onRepoRootChange(saved.repo_root);
      }
      setSettingsStatus('Saved');
    } catch (err) {
      setSettingsStatus('Save failed');
    }
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Context Arena</h1>
        <div className="new-convo-controls">
          <select
            className="mode-select"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="council">Council</option>
            <option value="round_robin">Round Robin</option>
            <option value="fight">Fight</option>
            <option value="stacks">Stacks</option>
            <option value="complex_iterative">Complex Iterative</option>
            <option value="complex_questioning">Complex Questioning</option>
          </select>
          <button className="new-conversation-btn" onClick={handleNew}>
          + New Conversation
        </button>
        </div>
        <button
          className="settings-toggle"
          onClick={() => setShowSettings((v) => !v)}
        >
          {showSettings ? 'Hide settings' : 'Show settings'}
        </button>
      </div>

      {showSettings && (
        <div className="settings-panel">
          <div className="settings-field">
            <label>Arena models (one per line)</label>
            <textarea
              value={(settings.arena_models || []).join('\n')}
              onChange={(e) =>
                setSettings((prev) => ({
                  ...prev,
                  arena_models: e.target.value
                    .split('\n')
                    .map((v) => v.trim())
                    .filter(Boolean),
                }))
              }
            />
          </div>
          <div className="settings-field">
            <label>Chairman model</label>
            <input
              type="text"
              value={settings.chairman_model || ''}
              onChange={(e) =>
                setSettings((prev) => ({ ...prev, chairman_model: e.target.value }))
              }
            />
          </div>
          <div className="settings-field">
            <label>Repo root (for git reindex)</label>
            <input
              type="text"
              value={settings.repo_root || ''}
              placeholder="/home/you/project"
              onChange={(e) =>
                setSettings((prev) => ({ ...prev, repo_root: e.target.value }))
              }
            />
            <small className="settings-hint">Enter absolute path on the backend machine.</small>
          </div>
          <div className="settings-field">
            <label>Theme</label>
            <select
              value={settings.theme || theme || 'light'}
              onChange={(e) => {
                const val = e.target.value;
                setSettings((prev) => ({ ...prev, theme: val }));
                onThemeChange && onThemeChange(val);
              }}
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </div>
          <div className="settings-actions">
            <button className="new-conversation-btn" onClick={handleSettingsSave}>
              Save settings
            </button>
            {settingsStatus && <span className="settings-status">{settingsStatus}</span>}
          </div>
        </div>
      )}

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv.id)}
            >
              <div className="conversation-title">
                {conv.title || 'New Conversation'}
              </div>
              <div className="conversation-meta">
                {conv.message_count} messages · {conv.mode || 'baseline'}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
