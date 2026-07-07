import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [abortCtrl, setAbortCtrl] = useState(null);
  const [modeProgress, setModeProgress] = useState({ current: 0, total: 0, label: '' });
  const [breadcrumbsByConversation, setBreadcrumbsByConversation] = useState({});
  const [theme, setTheme] = useState('light');
  const [liveStepsByConversation, setLiveStepsByConversation] = useState({});
  const [repoRoot, setRepoRoot] = useState('');

  const pushBreadcrumb = (crumb) => {
    if (!currentConversationId) return;
    setBreadcrumbsByConversation((prev) => {
      const existing = prev[currentConversationId] || [];
      const next = [...existing, { id: `${Date.now()}-${existing.length}`, ...crumb }].slice(-12);
      return { ...prev, [currentConversationId]: next };
    });
  };

  const pushLiveStep = (step) => {
    if (!currentConversationId || !step) return;
    setLiveStepsByConversation((prev) => {
      const existing = prev[currentConversationId] || [];
      const next = [...existing, { ...step, __idx: existing.length }];
      return { ...prev, [currentConversationId]: next };
    });
  };

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
    api.getSettings().then((data) => {
      if (data?.theme) setTheme(data.theme);
      if (data?.repo_root) setRepoRoot(data.repo_root);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    document.body.classList.toggle('theme-dark', theme === 'dark');
  }, [theme]);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const handleNewConversation = async (mode = 'council') => {
    try {
      const newConv = await api.createConversation(mode);
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, message_count: 0, mode: newConv.mode },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
      setCurrentConversation(newConv);
      setModeProgress({ current: 0, total: 0, label: '' });
      setBreadcrumbsByConversation((prev) => ({ ...prev, [newConv.id]: [] }));
      setLiveStepsByConversation((prev) => ({ ...prev, [newConv.id]: [] }));
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
    setModeProgress({ current: 0, total: 0, label: '' });
    setIsLoading(false);
    setBreadcrumbsByConversation((prev) => ({ ...prev, [id]: prev[id] || [] }));
    setLiveStepsByConversation((prev) => ({ ...prev, [id]: prev[id] || [] }));
  };

  const handleSendMessage = async (content, manualContext = []) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    const controller = new AbortController();
    setAbortCtrl(controller);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        contextSources: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));
      setModeProgress({ current: 0, total: 0, label: '' });

      // Send message with streaming
      await api.sendMessageStream(currentConversationId, content, manualContext, (eventType, event) => {
        switch (eventType) {
          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.metadata = {
                ...(lastMsg.metadata || {}),
                ...(event.metadata || {}),
              };
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;
          case 'execution_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              if (event.data?.steps || event.data?.cost) {
                lastMsg.metadata = {
                  ...(lastMsg.metadata || {}),
                  ...(event.data?.steps ? { steps: event.data.steps } : {}),
                  mode: event.data.mode ?? lastMsg.metadata?.mode,
                  ...(event.data?.cost ? { cost: event.data.cost } : {}),
                };
              }
              return { ...prev, messages };
            });
            break;
          case 'execution_start':
          case 'mode_steps':
            if (event.data?.step_total ?? event.data?.total) {
              setModeProgress({
                current: 0,
                total: event.data.step_total ?? event.data.total,
                label: 'Starting...',
                activeModel: null,
              });
            }
            break;
          case 'step_complete':
            if (event.data?.step) {
              pushLiveStep(event.data.step);
            }
            if (event.data) {
              const completed = event.data.step_index ?? event.data.completed ?? event.data.current ?? 0;
              setModeProgress((prev) => ({
                current: completed ?? prev.current ?? 0,
                total: event.data.step_total ?? event.data.total ?? prev.total ?? 0,
                label: event.data.label ?? event.data.role ?? prev.label ?? '',
                activeModel: event.data.active_model ?? event.data.model ?? prev.activeModel ?? null,
                state: event.data.state ?? prev.state,
              }));
            }
            break;
          case 'mode_progress':
            if (event.data) {
              const completed = event.data.step_index ?? event.data.completed ?? event.data.current ?? 0;
              setModeProgress((prev) => ({
                current: completed ?? prev.current ?? 0,
                total: event.data.step_total ?? event.data.total ?? prev.total ?? 0,
                label: event.data.label ?? event.data.role ?? prev.label ?? '',
                activeModel: event.data.active_model ?? event.data.model ?? prev.activeModel ?? null,
                state: event.data.state ?? prev.state,
              }));
              if (event.data.step) {
                pushLiveStep(event.data.step);
              }
              if (event.data.state === 'finish') {
                pushBreadcrumb({
                  label: event.data.label || 'step',
                  model: event.data.active_model || event.data.model,
                  est_tokens: event.data.est_tokens,
                  context_tokens: event.data.context_tokens,
                  completed,
                  total: event.data.total,
                });
              }
            }
            break;
          case 'summarization':
            pushBreadcrumb({
              label: 'summarization',
              model: (event.data?.models || []).join(', '),
              context_tokens: Object.values(event.data?.targets || {}).reduce((a, b) => a + (b || 0), 0),
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            setModeProgress((prev) => ({ ...prev, current: prev.total, label: 'Complete' }));
            // Fallback: if complete never arrives, stop loading shortly after stage3 completes.
            setTimeout(() => setIsLoading(false), 500);
            break;

          case 'rag_context':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.contextSources = event.data || [];
              return { ...prev, messages };
            });
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            loadConversations();
            setIsLoading(false);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      }, controller.signal);
    } catch (error) {
      if (error.name === 'AbortError') {
        // Remove the partial assistant message and keep the user message.
        setCurrentConversation((prev) => {
          const messages = [...prev.messages];
          if (messages[messages.length - 1]?.role === 'assistant') {
            messages.pop();
          }
          return { ...prev, messages };
        });
      } else {
        console.error('Failed to send message:', error);
        // Remove optimistic messages on error
        setCurrentConversation((prev) => ({
          ...prev,
          messages: prev.messages.slice(0, -2),
        }));
      }
    }
    finally {
      setIsLoading(false);
      setAbortCtrl(null);
    }
  };

  const handleStopStreaming = () => {
    if (abortCtrl) {
      abortCtrl.abort();
    }
    setAbortCtrl(null);
    setIsLoading(false);
    setModeProgress({ current: 0, total: 0, label: '' });
    // Remove partial assistant message if present
    setCurrentConversation((prev) => {
      if (!prev) return prev;
      const messages = [...prev.messages];
      if (messages[messages.length - 1]?.role === 'assistant') {
        messages.pop();
      }
      return { ...prev, messages };
    });
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        theme={theme}
        onThemeChange={setTheme}
        repoRoot={repoRoot}
        onRepoRootChange={setRepoRoot}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        onStop={handleStopStreaming}
        isLoading={isLoading}
        modeProgress={modeProgress}
        breadcrumbs={breadcrumbsByConversation[currentConversationId] || []}
        theme={theme}
        liveSteps={liveStepsByConversation[currentConversationId] || []}
        repoRoot={repoRoot}
      />
    </div>
  );
}

export default App;
