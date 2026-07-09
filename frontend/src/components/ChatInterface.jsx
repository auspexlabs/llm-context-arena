import { useState, useEffect, useRef, memo } from 'react';
import { useDropzone } from 'react-dropzone';
import ReactMarkdown from 'react-markdown';
import { api } from '../api';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import { RoundTrack } from './RoundTrack';
import ArenaStatusBar from './ArenaStatusBar';
import TurnCostLine from './TurnCostLine';
import {
  sessionCostFromMessages,
  sumStepsCost,
  turnCostFromMessage,
} from '../costUtils';
import './ChatInterface.css';
import './RoundTrack.css';

function RepoDropzone({ conversationId, onIndexed }) {
  const [status, setStatus] = useState(null);
  const [progress, setProgress] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const progressTimer = useRef(null);

  const onDrop = async (acceptedFiles) => {
    const file = acceptedFiles[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.zip')) {
      setStatus('Please drop a .zip file.');
      return;
    }

    setStatus('Uploading…');
    setIsUploading(true);
    setProgress(5);

    if (progressTimer.current) clearInterval(progressTimer.current);
    progressTimer.current = setInterval(() => {
      setProgress((p) => {
        if (p >= 90) return 90;
        return p + 5;
      });
    }, 200);

    try {
      const data = await api.uploadRepo(conversationId, file);
      if (data.status === 'success') {
        setStatus('Indexing…');
        // Show an indexing spinner state until the response returns.
        setProgress(90);
        setStatus(data.message || 'Repository indexed successfully.');
        setProgress(100);
        onIndexed && onIndexed();
      } else {
        setStatus(data.message || 'Indexing failed.');
        setProgress(100);
      }
    } catch (err) {
      console.error(err);
      setStatus(err.message || 'Upload failed. Check backend logs.');
      setProgress(0);
    }

    if (progressTimer.current) {
      clearInterval(progressTimer.current);
      progressTimer.current = null;
    }
    setIsUploading(false);
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  useEffect(() => {
    return () => {
      if (progressTimer.current) clearInterval(progressTimer.current);
    };
  }, []);

  return (
    <div className="repo-dropzone-wrapper">
      <div
        {...getRootProps()}
        className="repo-dropzone"
        style={{
          border: '2px dashed #555',
          borderRadius: '0.5rem',
          padding: '0.75rem',
          fontSize: '0.85rem',
          cursor: 'pointer',
          marginBottom: '0.75rem',
          backgroundColor: isDragActive ? '#1f1f1f' : 'transparent',
        }}
      >
        <input {...getInputProps()} />
        {isDragActive ? (
          <span>Drop your repo .zip here…</span>
        ) : (
          <span>
            Drag &amp; drop a repo <code>.zip</code> here to give the arena local
            code context for this conversation.
          </span>
        )}
      </div>
      {status && (
        <div
          style={{
            fontSize: '0.8rem',
            marginTop: '0.25rem',
            opacity: 0.9,
          }}
        >
          {status}
        </div>
      )}
      {(isUploading || progress > 0) && (
        <div
          style={{
            marginTop: '0.35rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <div
            style={{
              flex: 1,
              background: '#2a2a2a',
              borderRadius: '0.35rem',
              overflow: 'hidden',
              height: '6px',
            }}
          >
            <div
              style={{
                width: `${progress}%`,
                transition: 'width 0.2s ease',
                background: '#4caf50',
                height: '100%',
              }}
            />
          </div>
          {progress >= 90 && progress < 100 && (
            <div className="tiny-spinner" title="Indexing" />
          )}
        </div>
      )}
    </div>
  );
}

const ContextPanel = memo(function ContextPanel({ sources }) {
  if (!sources || sources.length === 0) return null;
  const manual = sources.filter((s) => (s.source_type || '').startsWith('manual'));
  const rag = sources.filter((s) => (s.source_type || '').startsWith('rag'));

  const uniqueFiles = new Set((sources || []).map((s) => s.source)).size;
  const lineTotal = (sources || []).reduce((sum, s) => sum + (s.lines || 0), 0);

  const [collapsed, setCollapsed] = useState(true);

  const renderSection = (label, items) => (
    <div className="context-section">
      <div className="context-section-title">{label}</div>
      {items.map((item, idx) => {
        const isFullFile = (item.source_type || '').startsWith('manual') && item.content && item.content.length > 0;
        const showPreview = !isFullFile || (item.source_type || '').includes('snippet') || (item.source_type || '').startsWith('rag');
        return (
          <div className="context-row" key={`${item.source}-${idx}`}>
            <div className="context-row-header">
              <span className="context-tag">{label === 'Manual' ? 'Manual' : 'RAG'}</span>
              <span className="context-path">{item.source}</span>
              {item.score !== null && item.score !== undefined && (
                <span className="context-score">score {item.score.toFixed(3)}</span>
              )}
              <span className="context-meta">{item.lines} lines · {item.est_tokens || 0} est tokens</span>
            </div>
            {showPreview ? (
              <div className="context-preview">{item.content || ''}</div>
            ) : (
              <div className="context-preview muted">(Full file included; content hidden)</div>
            )}
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="context-panel">
      <div className="context-header" onClick={() => setCollapsed((v) => !v)} role="button">
        <div className="context-title">Context used · {uniqueFiles} files · {lineTotal} lines</div>
        <div className="context-toggle-indicator">{collapsed ? 'Show' : 'Hide'}</div>
      </div>
      {!collapsed && (
        <>
          {manual.length > 0 && renderSection('Manual', manual)}
          {rag.length > 0 && renderSection('RAG', rag)}
        </>
      )}
    </div>
  );
}, (prev, next) => prev.sources === next.sources);

export default function ChatInterface({
  conversation,
  onSendMessage,
  onStop,
  isLoading,
  modeProgress,
  breadcrumbs = [],
  theme = 'light',
  liveSteps = [],
  repoRoot,
}) {
  const [input, setInput] = useState('');
  const [manualSelections, setManualSelections] = useState([]);
  const [repoTree, setRepoTree] = useState([]);
  const [contextPanelOpen, setContextPanelOpen] = useState(false);
  const [resolvingDirectives, setResolvingDirectives] = useState(false);
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const [showScrollDown, setShowScrollDown] = useState(false);
  const [reindexStatus, setReindexStatus] = useState('');
  const [indexFreshness, setIndexFreshness] = useState(null);
  const [isReindexing, setIsReindexing] = useState(false);
  const [focusedTarget, setFocusedTarget] = useState(null);
  const stage1Ref = useRef(null);
  const [currentModeProgress, setCurrentModeProgress] = useState(modeProgress || { current: 0, total: 0, label: '' });
  const [expandedPrompts, setExpandedPrompts] = useState({});
  const [pendingScrollIndex, setPendingScrollIndex] = useState(null);
  const timelineRefs = useRef({});
  const quips = [
    'Sharpening pencils…',
    'Consulting the oracle…',
    'Counting tokens so you don’t have to.',
    'Arguing politely…',
    'Refilling the coffee pot…',
  ];
  const [quipIndex, setQuipIndex] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const shortModelName = (model) => (model?.split('/')?.[1] || model || '').trim();
  const friendlyStepLabel = (label) => {
    const map = {
      answer: 'Collecting answers',
      critique: 'Critiques',
      defense: 'Defenses',
      muse: 'Muse round',
      brief: 'Chair brief',
      extract: 'Extracting',
      expand: 'Expanding',
      stacks_merge: 'Merging answers',
      stacks_critique: 'Critiques',
      stacks_judge: 'Judging',
      stacks_defense: 'Defending',
      round_robin: 'Round Robin pass',
      fight: 'Fight flow',
      stacks: 'Stacks flow',
      complex_iterative: 'Iterative flow',
      complex_questioning: 'Questioning flow',
      council: 'Council',
      baseline: 'Council',
    };
    if (!label) return '';
    return map[label] || label.replace(/_/g, ' ');
  };
  const modeDescriptions = {
    council: 'Council. Answers → rankings → chairman synthesis.',
    baseline: 'Council. Answers → rankings → chairman synthesis.',
    round_robin: 'Round Robin passes improve a shared draft before chair finalizes.',
    fight: 'Fight: answers, critiques, defenses, then chair.',
    stacks: 'Stacks: pair answers, merge, critiques, judge, defenses, chair.',
    complex_iterative: 'Iterative extract/expand chain, then chair.',
    complex_questioning: 'Questioning: answers, self-questions, brief, muse, chair.',
  };

  const formatProgressLabel = (mp) => {
    if (!mp?.total) return '';
    const rawLabel = friendlyStepLabel(mp.label) || 'Step';
    const label = rawLabel.charAt(0).toUpperCase() + rawLabel.slice(1);
    const model = shortModelName(mp.activeModel);
    const current = mp.current ?? 0;
    const total = mp.total ?? 0;
    const stepText = `${Math.max(0, current)}/${total || '?'}`;
    return model ? `${label} · ${model} (${stepText})` : `${label} (${stepText})`;
  };

  const spinnerText = () => {
    const modeLabelMap = {
      round_robin: 'Round Robin',
      fight: 'Fight',
      stacks: 'Stacks',
      complex_iterative: 'Complex Iterative',
      complex_questioning: 'Complex Questioning',
      baseline: 'Council',
      council: 'Council',
    };
    const modeLabel = modeLabelMap[conversation?.mode] || 'Council';
    const label = friendlyStepLabel(currentModeProgress?.label);
    const model = shortModelName(currentModeProgress?.activeModel);
    const stepText =
      currentModeProgress?.total && (currentModeProgress.current || currentModeProgress.current === 0)
        ? `${currentModeProgress.current}/${currentModeProgress.total}`
        : '';

    const timePart = elapsedSeconds ? ` · ${elapsedSeconds}s` : '';

    if (label) {
      return `${modeLabel}: ${label}${model ? ` · ${model}` : ''}${stepText ? ` (${stepText})` : ''}${timePart}`;
    }
    return `Consulting the ${modeLabel.toLowerCase()}...${timePart}`;
  };

  const stage1LoadingText = () => {
    switch (conversation.mode) {
      case 'round_robin':
        return 'Running Stage 1: Drafting (Round Robin)...';
      case 'fight':
        return 'Running Stage 1: Gathering answers for Fight...';
      case 'stacks':
        return 'Running Stage 1: Pair answers for Stacks...';
      case 'complex_iterative':
        return 'Running Stage 1: Extract/Expand kickoff...';
      case 'complex_questioning':
        return 'Running Stage 1: Gathering answers for Questioning...';
      default:
        return 'Running Stage 1: Collecting individual responses...';
    }
  };

  const computeActiveIndex = (steps = []) => {
    if (!steps.length || !currentModeProgress?.total) return -1;
    const base =
      currentModeProgress.state === 'finish'
        ? (currentModeProgress.current ?? 0) - 1
        : currentModeProgress.current ?? 0;
    if (base < 0) return -1;
    return Math.min(base, steps.length - 1);
  };

  const previewText = (text = '', limit = 220) => {
    if (!text) return '';
    const normalized = `${text}`.trim();
    if (!normalized) return '';
    return normalized.length > limit ? `${normalized.slice(0, limit)}…` : normalized;
  };

  const sanitizePrompt = (prompt = '') => {
    if (!prompt) return '';
    const text = typeof prompt === 'string' ? prompt : String(prompt);
    try {
      // Drop explicit context blocks so the UI doesn't show injected RAG snippets.
      const withoutContext = text.replace(/# (relevant|manually selected)[\s\S]*?(?=User question:|$)/gi, '').trim();
      const target = withoutContext || text;
      const markerIdx = target.lastIndexOf('User question:');
      if (markerIdx !== -1) {
        return target.slice(markerIdx).trim();
      }
      return target.trim();
    } catch (err) {
      console.error('sanitizePrompt failed', err);
      return text;
    }
  };

  const togglePrompt = (idx) => {
    setExpandedPrompts((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  useEffect(() => {
    if (pendingScrollIndex === null || pendingScrollIndex === undefined) return;
    const el = timelineRefs.current?.[pendingScrollIndex];
    if (el?.scrollIntoView) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    setPendingScrollIndex(null);
  }, [pendingScrollIndex]);

  const formatIndexedAgo = (unixSeconds) => {
    if (!unixSeconds) return 'never';
    const diffSec = Math.max(0, Math.floor(Date.now() / 1000 - unixSeconds));
    if (diffSec < 60) return 'just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return `${Math.floor(diffSec / 86400)}d ago`;
  };

  const describeIndexDrift = (delta) => {
    if (!delta) return '';
    const drift = delta.git_stale && delta.git_drift ? delta.git_drift : delta;
    const parts = [];
    if (drift.added?.length) parts.push(`${drift.added.length} added`);
    if (drift.changed?.length) parts.push(`${drift.changed.length} changed`);
    if (drift.removed?.length) parts.push(`${drift.removed.length} removed`);
    return parts.join(', ');
  };

  const refreshIndexFreshness = () => {
    if (!conversation?.id) return;
    api
      .getIndexManifest(conversation.id, repoRoot)
      .then((manifest) => setIndexFreshness(manifest?.changed_since_index || manifest))
      .catch((err) => console.error('Failed to load index freshness', err));
  };

  const refreshRepoTree = () => {
    if (!conversation?.id) return;
    api
      .getRepoTree(conversation.id)
      .then((tree) => setRepoTree(tree))
      .catch((err) => console.error('Failed to load repo tree', err));
    refreshIndexFreshness();
  };

  const handleReindex = async () => {
    if (!conversation?.id || isReindexing) return;
    setIsReindexing(true);
    try {
      setReindexStatus('Reindexing…');
      const resp = repoRoot
        ? await api.reindexGit(conversation.id, repoRoot)
        : await api.reindexSnapshot(conversation.id);
      if (resp?.status === 'error') {
        throw new Error(resp.message || 'Reindex failed');
      }
      setReindexStatus(resp.message || 'Reindexed.');
      refreshRepoTree();
    } catch (err) {
      console.error('Failed to reindex', err);
      setReindexStatus(err.message || 'Reindex failed');
    } finally {
      setIsReindexing(false);
    }
  };

  const renderTimeline = (steps = [], activeIndex = -1) => {
    if (!steps || steps.length === 0) return null;
    return (
      <div className="mode-timeline">
        <div className="timeline-title">Mode timeline</div>
        {steps.map((step, idx) => {
          const modelName = shortModelName(step.model) || step.model || 'model';
          const rawPrompt = step.prompt_full || step.promptFull || step.prompt_preview || step.promptPreview || '';
          const rawPromptText = typeof rawPrompt === 'string' ? rawPrompt : String(rawPrompt || '');
          const promptText = sanitizePrompt(rawPromptText);
          const promptWasStripped = rawPromptText && promptText && promptText.length !== rawPromptText.trim().length;
          const promptPreview = previewText(promptText || rawPromptText);
          const responsePreview = previewText(step.response);
          const summary = responsePreview || promptPreview || 'No prompt/response captured.';
          const isExpanded = !!expandedPrompts[idx];
          return (
            <div
              key={idx}
              id={`timeline-step-${idx}`}
              className={`timeline-card ${idx === activeIndex ? 'active' : ''}`}
              onClick={() => togglePrompt(idx)}
              ref={(el) => {
                if (el) {
                  timelineRefs.current[idx] = el;
                }
              }}
            >
              <div className="timeline-top">
                <span className="timeline-order">#{idx + 1}</span>
                <span className="timeline-role">{step.role || 'step'}</span>
                <span className="timeline-model">{modelName}</span>
                {typeof step.duration_ms === 'number' && (
                  <span className="timeline-duration">{step.duration_ms} ms</span>
                )}
              </div>
              <div className="timeline-body">
                <div className="timeline-summary">
                  <div className="timeline-label">
                    {step.role || 'step'} → {modelName}
                  </div>
                  <div className="timeline-preview">
                    {summary}
                  </div>
                </div>

                {isExpanded && (
                  <div className="timeline-detail">
                    {(promptText || rawPromptText) ? (
                      <div className="timeline-block">
                        <div className="timeline-block-title">
                          Prompt {promptWasStripped ? <span className="muted">(context hidden in display)</span> : null}
                        </div>
                        <div className="timeline-block-text">{promptText || rawPromptText}</div>
                      </div>
                    ) : null}
                    {step.response ? (
                      <div className="timeline-block nested">
                        <div className="timeline-block-title">Response</div>
                        <div className="timeline-block-text">{step.response}</div>
                      </div>
                    ) : null}
                    {!rawPromptText && !step.response ? (
                      <div className="timeline-empty">No details recorded for this step.</div>
                    ) : null}
                  </div>
                )}

                <div className="timeline-meta">
                  {step.est_tokens ? <span>{step.est_tokens} est tokens</span> : null}
                  {step.context_tokens !== undefined ? <span>context {step.context_tokens}</span> : null}
                  <button
                    className="timeline-toggle"
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      togglePrompt(idx);
                    }}
                  >
                    {isExpanded ? 'Collapse details' : 'Expand prompt/response'}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
    setCurrentModeProgress(modeProgress || { current: 0, total: 0, label: '' });
  }, [modeProgress]);

  useEffect(() => {
    scrollToBottom();
    setCurrentModeProgress({ current: 0, total: 0, label: '' });
    setExpandedPrompts({});
    setPendingScrollIndex(null);
    timelineRefs.current = {};
    refreshRepoTree();
  }, [conversation]);

  useEffect(() => {
    if (!isLoading) {
      setElapsedSeconds(0);
      return;
    }
    const start = Date.now();
    const timer = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [isLoading, currentModeProgress.activeModel]);

  useEffect(() => {
    if (!isLoading) return;
    const timer = setInterval(() => {
      setQuipIndex((idx) => (idx + 1) % quips.length);
    }, 4000);
    return () => clearInterval(timer);
  }, [isLoading]);

  useEffect(() => {
    const el = messagesContainerRef.current;
    if (!el) return;

    const handleScroll = () => {
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowScrollDown(distanceFromBottom > 200);
    };

    el.addEventListener('scroll', handleScroll);
    handleScroll();
    return () => el.removeEventListener('scroll', handleScroll);
  }, [conversation?.id, modeProgress]);

  const parseDirectives = (text) => {
    const regex = /@("[^"]+"|\S+)/g;
    const directives = [];
    let cleaned = text;
    let match;
    while ((match = regex.exec(text)) !== null) {
      directives.push(match[0]);
      cleaned = cleaned.replace(match[0], '').trim();
    }
    return { directives, cleaned };
  };

  const resolveDirectives = async (directives, userText) => {
    const resolved = [];
    for (const dir of directives) {
      let token = dir.startsWith('@') ? dir.slice(1) : dir;
      if (token.startsWith('file:')) {
        token = token.replace('file:', '');
      }

      try {
        const pathRes = await api.resolvePath(conversation.id, token, userText);
        const match = pathRes?.matches?.[0];
        if (match?.content) {
          resolved.push({
            path: match.path,
            content: match.content,
            source_type: 'manual_at',
            score: match.score,
          });
          continue;
        }
      } catch (err) {
        console.error('Path resolve failed', err);
      }

      try {
        const searchRes = await api.searchRepo(conversation.id, token, 1);
        const result = searchRes?.results?.[0];
        if (result?.snippet) {
          resolved.push({
            path: result.path,
            content: result.snippet,
            source_type: 'manual_at_snippet',
          });
        }
      } catch (err) {
        console.error('Search failed', err);
      }
    }
    return resolved;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading || resolvingDirectives) return;
    setCurrentModeProgress({ current: 0, total: 0, label: '' });
    setExpandedPrompts({});
    setContextPanelOpen(false);

    try {
      setResolvingDirectives(true);
      const { directives, cleaned } = parseDirectives(input);
      const directiveContexts = await resolveDirectives(directives, cleaned);

      const manualContext = [
        ...manualSelections,
        ...directiveContexts,
      ];

      await onSendMessage(cleaned, manualContext);
      setInput('');
      // Clear manual selections after a send so the picker resets.
      setManualSelections([]);
    } catch (err) {
      console.error('Failed to send message', err);
    } finally {
      setResolvingDirectives(false);
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  useEffect(() => {
    if (!conversation?.id) {
      setRepoTree([]);
      setManualSelections([]);
      return;
    }

    // Reset picker state on conversation change so prior repos don't linger visually.
    setRepoTree([]);
    setManualSelections([]);
    setReindexStatus('');
    setIndexFreshness(null);
    refreshRepoTree();
  }, [conversation?.id]);

  useEffect(() => {
    if (!conversation?.id) return undefined;
    refreshIndexFreshness();
    const timer = setInterval(refreshIndexFreshness, 60000);
    const onFocus = () => refreshIndexFreshness();
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [conversation?.id, repoRoot]);

  const handleAddFileContext = async (path) => {
    try {
      const file = await api.getFile(conversation.id, path);
      setManualSelections((prev) => {
        if (prev.find((p) => p.path === path)) return prev;
        return [...prev, { path, content: file.content, source_type: 'manual_picker' }];
      });
    } catch (err) {
      console.error('Failed to add file', err);
    }
  };

  const handleRemoveManual = (path) => {
    setManualSelections((prev) => prev.filter((p) => p.path !== path));
  };

  const handleClearManualSelections = () => {
    setManualSelections((prev) => (prev.length ? [] : prev));
  };

  const renderRepoTree = (nodes) => {
    if (!nodes || nodes.length === 0) return <div className="repo-tree-empty">No repo uploaded or tree unavailable.</div>;

    return nodes.map((node) => {
      if (node.type === 'dir') {
        return (
          <details key={node.path} open>
            <summary>{node.name}</summary>
            <div className="repo-tree-children">{renderRepoTree(node.children)}</div>
          </details>
        );
      }
      return (
        <div
          key={node.path}
          className="repo-tree-file"
          onClick={() => handleAddFileContext(node.path)}
          role="button"
        >
          {node.name}
        </div>
      );
    });
  };

  if (!conversation) {
    return (
      <div className={`chat-interface theme-${theme}`}>
        <div className="empty-state">
          <h2>Welcome to LLM Context Arena</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  const isCouncilMode = ['council', 'baseline'].includes(
    (conversation.mode || 'council').toLowerCase()
  );
  const lastAssistantMsg = [...(conversation.messages || [])]
    .reverse()
    .find((m) => m.role === 'assistant');
  const executionSteps =
    isLoading && liveSteps.length
      ? liveSteps
      : lastAssistantMsg?.metadata?.steps || [];

  const turnCost = isLoading && liveSteps.length
    ? sumStepsCost(liveSteps)
    : turnCostFromMessage(lastAssistantMsg);
  const sessionCost = sessionCostFromMessages(
    conversation.messages,
    liveSteps,
    isLoading
  );

  const indexDelta = indexFreshness;
  const indexIsStale = !!indexDelta?.needs_reindex;
  const indexMissing = indexDelta && indexDelta.has_index === false;
  const driftSummary = describeIndexDrift(indexDelta);
  const indexedAgo = formatIndexedAgo(indexDelta?.indexed_at);
  const staleReason =
    indexDelta?.git_stale
      ? 'your git repo has changed since the last index'
      : indexDelta?.snapshot_stale
        ? 'the indexed snapshot no longer matches the last index'
        : indexMissing
          ? 'no codebase is indexed for this conversation'
          : 'the codebase index is out of date';

  const progressLabel = formatProgressLabel(currentModeProgress);

  return (
    <div className={`chat-interface theme-${theme}`}>
      <ArenaStatusBar
        mode={conversation.mode}
        title={conversation.title}
        isLoading={isLoading}
        modeProgress={currentModeProgress}
        progressLabel={progressLabel}
        turnCost={turnCost}
        sessionCost={sessionCost}
      />

      {(indexIsStale || indexMissing) && (
        <div className={`index-freshness-banner ${indexMissing ? 'missing' : 'stale'}`}>
          <div className="index-freshness-copy">
            <strong>{indexMissing ? 'No codebase indexed' : 'Code index out of date'}</strong>
            <span>
              {indexMissing
                ? 'Upload a ZIP or reindex from git before relying on retrieval.'
                : `${staleReason}${driftSummary ? ` (${driftSummary})` : ''}. Last indexed ${indexedAgo}.`}
            </span>
          </div>
          {!indexMissing && (
            <button
              type="button"
              className="index-freshness-action"
              onClick={handleReindex}
              disabled={isReindexing || isLoading}
            >
              {isReindexing ? 'Reindexing…' : repoRoot ? 'Reindex from git' : 'Reindex snapshot'}
            </button>
          )}
        </div>
      )}
      <div className="top-grid">
        <div className="controls-column">
          <div className="controls-row">
            <RepoDropzone conversationId={conversation.id} onIndexed={refreshRepoTree} />
            <div className="repo-actions inline">
              <button
                type="button"
                className="context-toggle"
                onClick={handleReindex}
                disabled={isReindexing || isLoading}
              >
                {repoRoot ? 'Reindex from git' : 'Reindex snapshot'}
              </button>
              {indexDelta?.has_index && !indexIsStale && (
                <span className="index-freshness-ok">Indexed {indexedAgo}</span>
              )}
              {reindexStatus && <span className="reindex-status">{reindexStatus}</span>}
              {repoRoot && (
                <span className="reindex-root">Root: {repoRoot}</span>
              )}
            </div>
          </div>
          <div className="context-tools">
            <div className="context-tools-header">
              <div>
                <div className="context-tools-title">Manual context</div>
                <div className="context-tools-subtitle">
                  Click files to add, or use @file:path / @token. Manual context skips auto-RAG.
                </div>
              </div>
              <button className="context-toggle" onClick={() => setContextPanelOpen((v) => !v)}>
                {contextPanelOpen ? 'Hide details' : 'Expand details'}
              </button>
            </div>
            {contextPanelOpen && (
              <div className="context-picker">
                <div className="repo-tree" aria-label="Repository tree">
                  {renderRepoTree(repoTree)}
                </div>
                <div className="selected-context">
                  <div className="selected-context-header">
                    <div className="selected-context-title">Selected for next message</div>
                    <button
                      type="button"
                      className="clear-selection"
                      onClick={handleClearManualSelections}
                      disabled={manualSelections.length === 0}
                    >
                      Clear all
                    </button>
                  </div>
                  {manualSelections.length === 0 && <div className="selected-context-empty">None yet</div>}
                  {manualSelections.map((item) => (
                    <div className="selected-chip" key={item.path}>
                      <span className="chip-path">{item.path}</span>
                      <button className="chip-remove" onClick={() => handleRemoveManual(item.path)}>×</button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="mode-summary-card">
          <div className="mode-summary-text">
            {modeDescriptions[conversation.mode] || 'Multi-step arena orchestration.'}
          </div>
          <div className="mode-summary-steps">
            {(() => {
              const steps = conversation.mode === 'round_robin'
                ? ['Drafts (passes)', 'Chair synthesis']
                : conversation.mode === 'fight'
                ? ['Answers', 'Critiques', 'Defenses', 'Chair']
                : conversation.mode === 'stacks'
                ? ['Pair answers', 'Merge', 'Critiques', 'Judge', 'Defenses', 'Chair']
                : conversation.mode === 'complex_iterative'
                ? ['Extract/Expand x2', 'Chair']
                : conversation.mode === 'complex_questioning'
                ? ['Answers', 'Self-questions', 'Brief', 'Muse', 'Chair']
                : ['Answers', 'Rankings', 'Chair'];
              return steps.map((s, idx) => <span key={idx} className="mode-chip">{s}</span>);
            })()}
          </div>
          {contextPanelOpen && (
            <div className="directives-panel">
              <div className="directives-title">@ directives</div>
              <div className="directives-grid">
                <div className="directive-item"><span className="dir-name">@lastchair</span> Reuse previous chairman reply as context (skip RAG).</div>
                <div className="directive-item"><span className="dir-name">@norag</span> Skip RAG entirely.</div>
                <div className="directive-item"><span className="dir-name">@summarize</span> Force context summarization.</div>
                <div className="directive-item"><span className="dir-name">@tokenbudget N</span> Set per-model context cap.</div>
                <div className="directive-item"><span className="dir-name">@temp X</span> Set temperature (0-1).</div>
                <div className="directive-item"><span className="dir-name">@maxtokens N</span> Override max output tokens.</div>
                <div className="directive-item"><span className="dir-name">@cite</span> Require inline citations.</div>
                <div className="directive-item"><span className="dir-name">@reset</span> Reset the conversation.</div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="messages-container" ref={messagesContainerRef}>
        {breadcrumbs.length > 0 && (
          <div className="breadcrumb-strip">
            {breadcrumbs.map((crumb) => (
              <div
                key={crumb.id}
                className="breadcrumb-item"
                title={`${friendlyStepLabel(crumb.label)}${crumb.model ? ` · ${shortModelName(crumb.model)}` : ''}${crumb.context_tokens ? ` (${crumb.context_tokens} ctx)` : ''}`}
              >
                <span className="breadcrumb-label">{friendlyStepLabel(crumb.label) || 'Step'}</span>
              </div>
            ))}
          </div>
        )}
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the Arena</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">You</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM Context Arena</div>

                  {/* Council: Stage 1 answers */}
                  {isCouncilMode && msg.loading?.stage1 && isLoading && index === conversation.messages.length - 1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>{stage1LoadingText()}</span>
                    </div>
                  )}
                  {!isCouncilMode && msg.loading?.stage1 && isLoading && index === conversation.messages.length - 1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>{formatProgressLabel(currentModeProgress) || `Running ${conversation.mode}…`}</span>
                    </div>
                  )}
                  {isCouncilMode && msg.stage1?.length > 0 && (
                    <Stage1
                      ref={stage1Ref}
                      responses={msg.stage1}
                      focusedTarget={focusedTarget}
                      onActiveChange={setFocusedTarget}
                      inProgressIndex={
                        isLoading && index === conversation.messages.length - 1
                          ? currentModeProgress?.activeModel
                            ? msg.stage1.findIndex((r) => r.model === currentModeProgress.activeModel)
                            : computeActiveIndex(msg.stage1)
                          : -1
                      }
                    />
                  )}

                  {/* Council: Stage 2 rankings */}
                  {isCouncilMode && msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer rankings...</span>
                    </div>
                  )}
                  {isCouncilMode && msg.stage2?.length > 0 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToModel={msg.metadata?.label_to_model || msg.metadata?.labelToModel}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                      onSelectModel={(model) => {
                        setFocusedTarget({ model });
                        stage1Ref.current?.scrollIntoView({ behavior: 'smooth' });
                      }}
                    />
                  )}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 3: Final synthesis...</span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} />}

                  {(msg.metadata?.model_failures?.length > 0) && (
                    <div className="model-failures-panel">
                      <div className="model-failures-title">
                        Model failures ({msg.metadata.model_failures.length})
                      </div>
                      <ul className="model-failures-list">
                        {msg.metadata.model_failures.map((f, i) => (
                          <li key={`${f.model}-${f.stage}-${i}`}>
                            <strong>{(f.model || '').split('/').pop()}</strong>
                            {' '}
                            [{f.stage}/{f.role}]
                            {f.status ? ` HTTP ${f.status}` : ''}
                            {f.message ? ` — ${f.message}` : ''}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <TurnCostLine message={msg} />

                  <ContextPanel sources={msg.contextSources || msg.context_sources} />
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>
              {spinnerText()}
            </span>
            <span className="loading-quip">{quips[quipIndex]}</span>
            {onStop && (
              <button className="stop-button" type="button" onClick={onStop}>
                Stop
              </button>
            )}
          </div>
        )}

        {executionSteps.length > 0 && (
          <div className="execution-timeline-panel">
            {(() => {
              const stepsWithIndex = executionSteps.map((s, i) => ({
                ...s,
                __idx: s.__idx ?? i,
              }));
              const activeMode = lastAssistantMsg?.metadata?.mode || conversation.mode;
              return (
                <>
                  <div className="timeline-detail-pane full">
                    {renderTimeline(stepsWithIndex, computeActiveIndex(stepsWithIndex))}
                  </div>
                  <div className="timeline-roundtrack full">
                    <RoundTrack
                      mode={activeMode}
                      steps={stepsWithIndex}
                      onSelectStep={(idx) => {
                        if (idx === null || idx === undefined) return;
                        const step = stepsWithIndex[idx];
                        setFocusedTarget({ index: idx, role: step?.role, model: step?.model });
                        setPendingScrollIndex(idx);
                        setExpandedPrompts((prev) => ({ ...prev, [idx]: true }));
                        if (isCouncilMode && step?.role === 'answer') {
                          stage1Ref.current?.scrollIntoView({ behavior: 'smooth' });
                        }
                      }}
                    />
                  </div>
                </>
              );
            })()}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {showScrollDown && (
        <button className="scroll-bottom" type="button" onClick={scrollToBottom}>
          ↓
        </button>
      )}

      <form className="input-form" onSubmit={handleSubmit}>
        <textarea
          className="message-input"
          placeholder="Ask your question... (Shift+Enter for new line, Enter to send)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading || resolvingDirectives}
          rows={3}
        />
        <button
          type="submit"
          className="send-button"
          disabled={!input.trim() || isLoading || resolvingDirectives}
        >
          {resolvingDirectives ? 'Resolving…' : 'Send'}
        </button>
      </form>
    </div>
  );
}
