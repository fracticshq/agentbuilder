import React from 'react';
import { WidgetButton } from './components/WidgetButton';
import { ChatWindow } from './components/ChatWindow';
import { useWidgetStore } from './stores/widgetStore';
import { useFullscreen } from './hooks/useFullscreen';
import { APIClient } from './utils/apiClient';
import { WebSocketClient } from './utils/wsClient';
import { buildBrandTheme } from './utils/brandTheme';
import { getConversationStorageKey, shouldAutoOpenFromSearch } from './utils/bootstrap';
import { extractPageContext } from './utils/pageContext';
import { trackEvent } from './utils/activityClient';
import { reduceActivity, finalizeActivity, EMPTY_ACTIVITY } from './utils/activityTimeline';
import type { ActivityState, WidgetConfig } from './types';
import './App.css';
import './styles/responsive.css';

declare global {
  interface Window {
    __APP_CONFIG__?: {
      API_BASE_URL?: string;
    };
  }
}

const API_BASE = window.__APP_CONFIG__?.API_BASE_URL || import.meta.env.VITE_API_BASE_URL || window.location.origin;
const WS_BASE = API_BASE.replace(/^http/, 'ws');
const apiClient = new APIClient(API_BASE);
const wsClient = new WebSocketClient(API_BASE);
const isEmbedded = window.parent !== window || new URLSearchParams(window.location.search).get('embedded') === '1';

function createSecureClientId(prefix: string): string {
  if (window.crypto?.randomUUID) {
    return `${prefix}_${window.crypto.randomUUID()}`;
  }

  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${prefix}_${value}`;
}

function getSessionStorageKey(agentId: string): string {
  return `agent_widget_session_${agentId}`;
}

function getControlSecretStorageKey(conversationId: string): string {
  return `agent_widget_control_secret_${conversationId}`;
}

function getOrCreateControlSecret(conversationId: string): string {
  const storageKey = getControlSecretStorageKey(conversationId);
  const existingSecret = sessionStorage.getItem(storageKey);
  if (existingSecret) {
    return existingSecret;
  }

  const secret = createSecureClientId('control');
  sessionStorage.setItem(storageKey, secret);
  return secret;
}

interface AppProps {
  config?: WidgetConfig;
}

function App({ config }: AppProps) {
  const {
    isOpen,
    messages,
    isTyping,
    conversationId,
    isExpanded,
    isHumanInControl,
    setIsOpen,
    addMessage,
    updateMessage,
    setIsTyping,
    setConfig,
    setConversationId,
    setExpanded,
    setBrandTheme,
    setHumanInControl,
    setMessageFeedback,
    removeMessage,
  } = useWidgetStore();

  const [activity, setActivity] = React.useState<ActivityState>(EMPTY_ACTIVITY);
  const activityRef = React.useRef<ActivityState>(EMPTY_ACTIVITY);
  const controlChannelRef = React.useRef<WebSocket | null>(null);

  // Keep a ref in sync so we can snapshot the final trace when the turn ends.
  const updateActivity = React.useCallback((next: ActivityState) => {
    activityRef.current = next;
    setActivity(next);
  }, []);

  const { isExpanded: isFullscreen, toggleExpanded, isMobile } = useFullscreen();

  React.useEffect(() => {
    setExpanded(isFullscreen);
  }, [isFullscreen, setExpanded]);

  // user_id is now issued by the server via the signed widget session below.
  // Keep a local fallback only for the brief window before the session resolves.
  const [userId, setUserId] = React.useState(() => {
    const stored = localStorage.getItem('agent_widget_user_id');
    if (stored) return stored;
    const newId = createSecureClientId('user');
    localStorage.setItem('agent_widget_user_id', newId);
    return newId;
  });

  const [agentId, setAgentId] = React.useState<string | null>(null);
  const [useWebSocket, setUseWebSocket] = React.useState(true);
  const [humanTakeoverEnabled, setHumanTakeoverEnabled] = React.useState(false);
  const [showSources, setShowSources] = React.useState(config?.showSources ?? false);
  const [showProductCards, setShowProductCards] = React.useState(config?.showProductCards ?? true);
  // 'basic' = the lightweight cycling indicator; 'advanced' = the live step
  // timeline. Admin-configurable per agent; defaults to 'basic'.
  const [activityMode, setActivityMode] = React.useState<'basic' | 'advanced'>('basic');
  const [unavailableMessage, setUnavailableMessage] = React.useState<string | null>(null);
  // Holds the pending conversation lifecycle event type until agentId is ready.
  const [convStartEvent, setConvStartEvent] = React.useState<'conversation_started' | 'conversation_resumed' | null>(null);

  // ── Resolve agent ID ──────────────────────────────────────────
  React.useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const urlAgentId = urlParams.get('agent_id');
    if (urlAgentId) { setAgentId(urlAgentId); return; }
    if (config?.agentId) { setAgentId(config.agentId); return; }
    const scriptTag = document.querySelector('script[data-agent-id]') as HTMLScriptElement;
    if (scriptTag?.dataset.agentId) { setAgentId(scriptTag.dataset.agentId); return; }
    setAgentId(null);
  }, [config?.agentId]);

  // ── Fetch brand theme once agent ID is known ──────────────────
  React.useEffect(() => {
    if (!agentId) return;

    const fetchBrandTheme = async () => {
      try {
        setUnavailableMessage(null);
        // 1. Get agent → extract brand_id
        const agentRes = await fetch(`${API_BASE}/api/v1/public/agents/${agentId}`);
        if (!agentRes.ok) {
          setUnavailableMessage('This agent is not available for widget preview. Activate it and enable the Public Widget channel in NOVA Admin.');
          return;
        }
        const agent = await agentRes.json();
        const brandId: string | undefined = agent.brand_id;
        // Read WebSocket setting from agent config (default true if not set)
        const features = agent.configuration?.features || {};
        const widgetChannel = agent.configuration?.channels?.widget || {};
        if (widgetChannel.enabled === false) {
          setUnavailableMessage('This agent has the Public Widget channel disabled.');
          return;
        }
        const wsEnabled = features.websockets !== false;
        const takeoverEnabled = config?.enableHumanTakeover ?? widgetChannel.human_takeover ?? features.human_takeover === true;
        const shouldShowSources = config?.showSources ?? widgetChannel.show_sources ?? features.show_sources === true;
        const shouldShowProductCards = config?.showProductCards ?? widgetChannel.show_product_cards ?? features.show_product_cards !== false;
        const resolvedActivityMode =
          (widgetChannel.activity_mode ?? features.activity_mode) === 'advanced' ? 'advanced' : 'basic';
        setUseWebSocket(wsEnabled);
        setHumanTakeoverEnabled(takeoverEnabled);
        setShowSources(shouldShowSources);
        setShowProductCards(shouldShowProductCards);
        setActivityMode(resolvedActivityMode);
        if (!brandId) return;

        // 2. Get brand → extract colors / identity
        const brandRes = await fetch(`${API_BASE}/api/v1/public/brands/${brandId}`);
        if (!brandRes.ok) return;
        const brand = await brandRes.json();

        const theme = buildBrandTheme(brand.name || 'AI', brand.colors || {});
        setBrandTheme(theme);

        // Persist agent_id for MessageBubble product fetches
        localStorage.setItem('agent_widget_agent_id', agentId);
      } catch {
        setUnavailableMessage('NOVA could not load this agent right now. Check that the API is running and the agent is active.');
      }
    };

    fetchBrandTheme();
  }, [agentId, config?.enableHumanTakeover, config?.showProductCards, config?.showSources, setBrandTheme]);

  React.useEffect(() => {
    if (config) setConfig(config);
  }, [config, setConfig]);

  React.useEffect(() => {
    if (shouldAutoOpenFromSearch(window.location.search)) {
      setIsOpen(true);
    }
  }, [setIsOpen]);

  React.useEffect(() => {
    if (!isEmbedded) return;

    window.parent.postMessage({
      type: 'agentbuilder-widget-state',
      isOpen,
      isExpanded,
    }, '*');
  }, [isOpen, isExpanded]);

  // ── Widget control channel (human takeover) ───────────────────
  React.useEffect(() => {
    if (!conversationId || !agentId || !humanTakeoverEnabled) {
      setHumanInControl(false);
      return;
    }

    let ws: WebSocket | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
    let destroyed = false;
    let reconnectDelay = 1_000;
    const controlSecret = getOrCreateControlSecret(conversationId);

    const connect = () => {
      if (destroyed) return;
      const params = new URLSearchParams({
        agent_id: agentId,
        control_secret: controlSecret,
      });
      ws = new WebSocket(`${WS_BASE}/api/v1/messages/ws/widget/${conversationId}?${params.toString()}`);
      controlChannelRef.current = ws;

      ws.onopen = () => {
        reconnectDelay = 1_000;
        ws!.send(JSON.stringify({ type: 'register', agent_id: agentId }));
        heartbeat = setInterval(() => {
          if (ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30_000);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data as string);
          if (msg.type === 'control_status') {
            setHumanInControl(msg.is_human_in_control ?? false);
          } else if (msg.type === 'system_notice') {
            addMessage({
              id: `sys_${Date.now()}`,
              content: msg.content || '',
              role: 'system',
              timestamp: new Date(),
            });
          } else if (msg.type === 'admin_message') {
            addMessage({
              id: `admin_${Date.now()}`,
              content: msg.content || '',
              role: 'assistant',
              timestamp: new Date(),
            });
          }
        } catch {
          // ignore malformed frames
        }
      };

      ws.onerror = () => {};

      ws.onclose = (event) => {
        if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
        controlChannelRef.current = null;
        if (!destroyed && event.code !== 1008) {
          // Exponential backoff reconnect, cap at 30s
          reconnectTimeout = setTimeout(() => {
            reconnectDelay = Math.min(reconnectDelay * 2, 30_000);
            connect();
          }, reconnectDelay);
        }
      };
    };

    connect();

    return () => {
      destroyed = true;
      if (heartbeat) clearInterval(heartbeat);
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      ws?.close();
      controlChannelRef.current = null;
      setHumanInControl(false);
    };
  }, [conversationId, agentId, humanTakeoverEnabled, setHumanInControl]);

  // ── Establish a server-issued, signed session ─────────────────
  // The server mints conversation_id + user_id bound to a signed token. We can
  // no longer fabricate ids client-side; doing so is exactly the hijacking
  // vector this closes. A stored token (valid 7d) resumes the same conversation.
  React.useEffect(() => {
    if (!isOpen || conversationId || !agentId) return;

    let cancelled = false;
    const storageKey = getSessionStorageKey(agentId);
    const priorToken = localStorage.getItem(storageKey) || undefined;
    const resuming = Boolean(priorToken);

    (async () => {
      try {
        const session = await apiClient.startSession(agentId, priorToken);
        if (cancelled) return;
        localStorage.setItem(storageKey, session.sessionToken);
        apiClient.setSessionToken(session.sessionToken);
        wsClient.setSessionToken(session.sessionToken);
        setUserId(session.userId);
        setConversationId(session.conversationId);
        sessionStorage.setItem(getConversationStorageKey(agentId), session.conversationId);
        setConvStartEvent(resuming ? 'conversation_resumed' : 'conversation_started');
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to establish widget session:', err);
          setUnavailableMessage('This agent is not ready for widget chat. Activate it and enable the Public Widget channel in NOVA Admin.');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [isOpen, conversationId, agentId, setConversationId]);

  // ── Fire conversation lifecycle event once both IDs are ready ─
  React.useEffect(() => {
    if (!convStartEvent || !conversationId || !agentId) return;
    trackEvent({
      event_type: convStartEvent,
      actor_type: 'user',
      actor_id: userId,
      agent_id: agentId,
      conversation_id: conversationId,
      page_context: extractPageContext(),
    });
    setConvStartEvent(null);
  }, [convStartEvent, conversationId, agentId, userId]);

  const handleToggleWidget = () => setIsOpen(!isOpen);

  const handleSendMessage = async (text: string) => {
    if (!agentId) {
      addMessage({
        id: Date.now().toString(),
        content: 'Add an agent_id in the URL to preview a NOVA agent, for example: ?agent_id=your-agent-id&open=1',
        role: 'assistant',
        timestamp: new Date(),
      });
      return;
    }

    addMessage({ id: Date.now().toString(), content: text, role: 'user', timestamp: new Date() });

    // If a human agent has taken control, route the message to them via the
    // control channel instead of sending it to the AI.
    if (isHumanInControl) {
      const cc = controlChannelRef.current;
      if (cc?.readyState === WebSocket.OPEN) {
        cc.send(JSON.stringify({ type: 'user_message', content: text }));
      }
      return;
    }
    setIsTyping(true);

    const assistantMessageId = (Date.now() + 1).toString();
    let streamedContent = '';

    try {
      const context = extractPageContext();

      // Ensure a signed session exists. Conversation/user ids come from the
      // server; the client can't mint them anymore.
      let currentConvId = conversationId;
      let currentUserId = userId;
      if (!currentConvId) {
        const storageKey = getSessionStorageKey(agentId);
        const session = await apiClient.startSession(agentId, localStorage.getItem(storageKey) || undefined);
        localStorage.setItem(storageKey, session.sessionToken);
        wsClient.setSessionToken(session.sessionToken);
        currentConvId = session.conversationId;
        currentUserId = session.userId;
        setUserId(session.userId);
        setConversationId(session.conversationId);
        sessionStorage.setItem(getConversationStorageKey(agentId), session.conversationId);
      }

      trackEvent({
        event_type: 'message_sent',
        actor_type: 'user',
        actor_id: currentUserId,
        agent_id: agentId,
        conversation_id: currentConvId,
        page_context: extractPageContext(),
      });

      addMessage({ id: assistantMessageId, content: '', role: 'assistant', timestamp: new Date(), citations: [] });
      updateActivity(EMPTY_ACTIVITY);

      const client = useWebSocket ? wsClient : apiClient;
      const response = await client.sendMessage(
        { content: text, context, userId: currentUserId },
        currentConvId,
        agentId,
        (chunk) => {
          if (chunk.type === 'content' && chunk.content) {
            // Answer started streaming — collapse any in-flight steps to done.
            if (!streamedContent) updateActivity(finalizeActivity(activityRef.current));
            streamedContent += chunk.content;
            updateMessage(assistantMessageId, { content: streamedContent });
          } else {
            // Any other event is background activity — fold it into the timeline.
            updateActivity(reduceActivity(activityRef.current, chunk));
          }
        }
      );

      const finalActivity = finalizeActivity(activityRef.current);
      updateMessage(assistantMessageId, {
        content: response.content,
        citations: response.citations,
        products: response.products,
        dealers: response.dealers,
        activitySteps: finalActivity.steps.length ? finalActivity.steps : undefined,
        metadata: {
          ...(response.metadata || {}),
          ...(finalActivity.disambiguation
            ? { place_candidates: finalActivity.disambiguation.candidates }
            : {}),
        },
      });
      trackEvent({
        event_type: 'message_received',
        actor_type: 'agent',
        actor_id: agentId,
        agent_id: agentId,
        conversation_id: currentConvId,
      });
    } catch (err) {
      console.error('[Widget] Chat error:', err);
      updateMessage(assistantMessageId, {
        content: streamedContent || 'Sorry, I encountered an error. Please try again.',
        citations: [],
        products: [],
        dealers: [],
      });
    } finally {
      setIsTyping(false);
      updateActivity(EMPTY_ACTIVITY);
    }
  };

  const handleRegenerate = (messageId: string) => {
    const msgIndex = messages.findIndex(m => m.id === messageId);
    if (msgIndex < 0) return;
    // Find the preceding user message
    let userMsg: string | null = null;
    for (let i = msgIndex - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        userMsg = messages[i].content;
        break;
      }
    }
    if (!userMsg) return;
    removeMessage(messageId);
    handleSendMessage(userMsg);
  };

  return (
    <div className="widget-container">
      <WidgetButton onClick={handleToggleWidget} />

      {isOpen && (
        <div className={`widget-overlay ${isExpanded ? 'expanded' : ''}`}>
          <ChatWindow
            messages={messages}
            isTyping={isTyping}
            activity={activity}
            activityMode={activityMode}
            isExpanded={isExpanded}
            isMobile={isMobile}
            onSendMessage={handleSendMessage}
            onClose={() => setIsOpen(false)}
            onToggleExpand={toggleExpanded}
            onRegenerate={handleRegenerate}
            onFeedback={setMessageFeedback}
            showSources={showSources}
            showProductCards={showProductCards}
            isAgentConfigured={Boolean(agentId)}
            unavailableMessage={unavailableMessage || undefined}
          />
        </div>
      )}
    </div>
  );
}

export default App;
