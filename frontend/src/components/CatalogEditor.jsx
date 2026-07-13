import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import './CatalogEditor.css';

function formatLimit(value) {
  if (value == null) return '—';
  return Number(value).toLocaleString();
}

function formatDelta(ratio) {
  if (ratio == null) return '';
  const pct = (Number(ratio) * 100).toFixed(1);
  return `${pct}%`;
}

function shortModelId(modelId) {
  if (!modelId) return '';
  const parts = modelId.split('/');
  return parts.length > 1 ? parts.slice(-1)[0] : modelId;
}

export default function CatalogEditor({ squad }) {
  const [report, setReport] = useState(null);
  const [pending, setPending] = useState([]);
  const [meta, setMeta] = useState(null);
  const [validateResult, setValidateResult] = useState(null);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState({ tags: '', model_modifier: '1', manual_override_limit: '' });

  const loadData = useCallback(async () => {
    try {
      setValidateResult(null);
      setStatus('Loading catalog…');
      const squadParam = squad || undefined;
      const [limits, pendingData, metaData] = await Promise.all([
        api.catalogEffectiveLimits(squadParam),
        api.catalogPendingObservations(squadParam),
        api.catalogMeta(),
      ]);
      setReport(limits);
      setPending(pendingData.pending || []);
      setMeta(metaData);
      setStatus('');
    } catch (err) {
      setStatus('Failed to load catalog');
    }
  }, [squad]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = async (force = false) => {
    try {
      setBusy(true);
      setStatus(force ? 'Refreshing from OpenRouter…' : 'Checking refresh…');
      const result = await api.catalogRefresh(force);
      if (result.skipped) {
        setStatus(`Refresh skipped (${result.reason || 'ttl'})`);
      } else {
        setStatus(`Refresh done — ${result.updated_count ?? 0} updated`);
      }
      await loadData();
    } catch (err) {
      setStatus('Catalog refresh failed');
    } finally {
      setBusy(false);
    }
  };

  const handleValidate = async () => {
    try {
      setBusy(true);
      const result = await api.catalogValidate();
      setValidateResult(result);
      setStatus(result.ok ? 'Config valid' : 'Config has issues');
    } catch (err) {
      setStatus('Validate failed');
    } finally {
      setBusy(false);
    }
  };

  const handleAccept = async (obsId) => {
    try {
      setBusy(true);
      await api.catalogAcceptObservation(obsId);
      setStatus('Observation accepted');
      await loadData();
    } catch (err) {
      setStatus('Accept failed');
    } finally {
      setBusy(false);
    }
  };

  const handleDecline = async (obsId) => {
    try {
      setBusy(true);
      await api.catalogDeclineObservation(obsId);
      setStatus('Observation declined');
      await loadData();
    } catch (err) {
      setStatus('Decline failed');
    } finally {
      setBusy(false);
    }
  };

  const openEditor = (row) => {
    setEditingId(row.model_id);
    setDraft({
      tags: (row.tags || []).join(', '),
      model_modifier: String(row.model_modifier ?? 1),
      manual_override_limit:
        row.manual_override_limit != null ? String(row.manual_override_limit) : '',
    });
  };

  const handleSaveModel = async (modelId) => {
    try {
      setBusy(true);
      const parsedModifier = parseFloat(draft.model_modifier);
      const payload = {
        tags: draft.tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        model_modifier: Number.isFinite(parsedModifier) ? parsedModifier : 1,
      };
      if (draft.manual_override_limit.trim()) {
        payload.manual_override_limit = parseInt(draft.manual_override_limit, 10);
      } else {
        payload.clear_manual_override = true;
      }
      await api.catalogUpdateModel(modelId, payload);
      setStatus('Saved — restart backend to apply');
      setEditingId(null);
      await loadData();
    } catch (err) {
      setStatus('Save failed');
    } finally {
      setBusy(false);
    }
  };

  const rows = report?.models || [];
  const reverify = report?.reverify_required || [];

  return (
    <div className="catalog-editor">
      <p className="catalog-restart-note">
        Catalog edits write to <code>model_catalog.yaml</code>. Restart the backend for changes to
        take full effect in running turns.
      </p>

      {meta?.last_refresh_at && (
        <p className="catalog-meta">
          Last refresh: {new Date(meta.last_refresh_at).toLocaleString()}
          {meta.updated_count != null ? ` · ${meta.updated_count} models updated` : ''}
        </p>
      )}

      <div className="catalog-toolbar">
        <button type="button" className="catalog-btn" disabled={busy} onClick={() => handleRefresh(false)}>
          Refresh
        </button>
        <button type="button" className="catalog-btn secondary" disabled={busy} onClick={() => handleRefresh(true)}>
          Force refresh
        </button>
        <button type="button" className="catalog-btn secondary" disabled={busy} onClick={handleValidate}>
          Validate
        </button>
      </div>

      {validateResult && !validateResult.ok && (
        <div className="catalog-issues">
          {(validateResult.issues || []).map((issue) => (
            <div key={issue}>{issue}</div>
          ))}
        </div>
      )}

      {reverify.length > 0 && (
        <div className="catalog-alert">
          Re-verify required: {reverify.join(', ')}
        </div>
      )}

      {pending.length > 0 && (
        <section className="catalog-section">
          <h3>Pending observations ({pending.length})</h3>
          <ul className="catalog-pending-list">
            {pending.map((obs) => (
              <li key={obs.id} className="catalog-pending-item">
                <div className="catalog-pending-head">
                  <span className="catalog-model-name" title={obs.model_id}>
                    {shortModelId(obs.model_id)}
                  </span>
                  <span className="catalog-delta">{formatDelta(obs.delta_ratio)}</span>
                </div>
                <div className="catalog-pending-limits">
                  reg {formatLimit(obs.registered_limit)} → obs {formatLimit(obs.observed_limit)}
                </div>
                <div className="catalog-pending-actions">
                  <button type="button" className="catalog-btn" disabled={busy} onClick={() => handleAccept(obs.id)}>
                    Accept
                  </button>
                  <button
                    type="button"
                    className="catalog-btn secondary"
                    disabled={busy}
                    onClick={() => handleDecline(obs.id)}
                  >
                    Decline
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="catalog-section">
        <h3>Squad limits {squad ? `(${squad})` : ''}</h3>
        {rows.length === 0 ? (
          <p className="catalog-empty">No models in report.</p>
        ) : (
          <ul className="catalog-model-list">
            {rows.map((row) => (
              <li key={row.model_id} className="catalog-model-item">
                <button
                  type="button"
                  className="catalog-model-summary"
                  onClick={() => (editingId === row.model_id ? setEditingId(null) : openEditor(row))}
                >
                  <span className="catalog-model-name" title={row.model_id}>
                    {shortModelId(row.model_id)}
                  </span>
                  <span className="catalog-effective">{formatLimit(row.effective_limit)} eff</span>
                </button>
                <div className="catalog-model-detail">
                  <span>reg {formatLimit(row.registered_limit)}</span>
                  {row.observed_limit != null && <span> · obs {formatLimit(row.observed_limit)}</span>}
                  {(row.tags || []).length > 0 && <span> · {row.tags.join(', ')}</span>}
                </div>

                {editingId === row.model_id && (
                  <div className="catalog-edit-form">
                    <label>
                      Tags (comma-separated)
                      <input
                        type="text"
                        value={draft.tags}
                        onChange={(e) => setDraft((d) => ({ ...d, tags: e.target.value }))}
                      />
                    </label>
                    <label>
                      Model modifier
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={draft.model_modifier}
                        onChange={(e) => setDraft((d) => ({ ...d, model_modifier: e.target.value }))}
                      />
                    </label>
                    <label>
                      Manual override limit
                      <input
                        type="number"
                        min="0"
                        placeholder="optional"
                        value={draft.manual_override_limit}
                        onChange={(e) =>
                          setDraft((d) => ({ ...d, manual_override_limit: e.target.value }))
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="catalog-btn"
                      disabled={busy}
                      onClick={() => handleSaveModel(row.model_id)}
                    >
                      Save model
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {status && <p className="catalog-status">{status}</p>}
    </div>
  );
}