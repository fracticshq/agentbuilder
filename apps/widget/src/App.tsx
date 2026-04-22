import React from 'react';
import { WidgetButton } from './components/WidgetButton';
import { ChatWindow } from './components/ChatWindow';
import { useWidgetStore } from './stores/widgetStore';
import { useFullscreen } from './hooks/useFullscreen';
import { APIClient } from './utils/apiClient';
import { WebSocketClient } from './utils/wsClient';
import { buildBrandTheme } from './utils/brandTheme';
import { extractPageContext } from './utils/pageContext';
import { trackEvent } from './utils/activityClient';
import type { WidgetConfig } from './types';
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

function createSecureClientId(prefix: string): string {
  if (window.crypto?.randomUUID) {
    return `${prefix}_${window.crypto.randomUUID()}`;
  }

  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${prefix}_${value}`;
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

  const [typingStatus, setTypingStatus] = React.useState<string>('');
  const controlChannelRef = React.useRef<WebSocket | null>(null);

  const { isExpanded: isFullscreen, toggleExpanded, isMobile } = useFullscreen();

  React.useEffect(() => {
    setExpanded(isFullscreen);
  }, [isFullscreen, setExpanded]);

  // Persistent user_id
  const [userId] = React.useState(() => {
    const stored = localStorage.getItem('agent_widget_user_id');
    if (stored) return stored;
    const newId = createSecureClientId('user');
    localStorage.setItem('agent_widget_user_id', newId);
    return newId;
  });

  const [agentId, setAgentId] = React.useState<string | null>(null);
  const [useWebSocket, setUseWebSocket] = React.useState(true);
  const [humanTakeoverEnabled, setHumanTakeoverEnabled] = React.useState(false);
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

    // Fallback: first available agent
    fetch(`${API_BASE}/api/v1/admin/agents/`)
      .then(r => r.ok ? r.json() : [])
      .then(agents => { if (agents.length > 0) setAgentId(agents[0].id); })
      .catch(() => {});
  }, [config?.agentId]);

  // ── Fetch brand theme once agent ID is known ──────────────────
  React.useEffect(() => {
    if (!agentId) return;

    const fetchBrandTheme = async () => {
      try {
        // 1. Get agent → extract brand_id
        const agentRes = await fetch(`${API_BASE}/api/v1/admin/agents/${agentId}`);
        if (!agentRes.ok) return;
        const agent = await agentRes.json();
        const brandId: string | undefined = agent.brand_id;
        // Read WebSocket setting from agent config (default true if not set)
        const wsEnabled = agent.configuration?.features?.websockets !== false;
        const takeoverEnabled = config?.enableHumanTakeover ?? agent.configuration?.features?.human_takeover === true;
        setUseWebSocket(wsEnabled);
        setHumanTakeoverEnabled(takeoverEnabled);
        if (!brandId) return;

        // 2. Get brand → extract colors / identity
        const brandRes = await fetch(`${API_BASE}/api/v1/admin/brands/${brandId}`);
        if (!brandRes.ok) return;
        const brand = await brandRes.json();

        const theme = buildBrandTheme(brand.name || 'AI', brand.colors || {});
        setBrandTheme(theme);

        // Persist agent_id for MessageBubble product fetches
        localStorage.setItem('agent_widget_agent_id', agentId);
      } catch {
        // Non-fatal: widget renders with default styling
      }
    };

    fetchBrandTheme();
  }, [agentId, config?.enableHumanTakeover, setBrandTheme]);

  React.useEffect(() => {
    if (config) setConfig(config);
  }, [config, setConfig]);

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

  // ── Initialize conversation ID ────────────────────────────────
  React.useEffect(() => {
    if (isOpen && !conversationId) {
      const stored = sessionStorage.getItem('agent_widget_conversation_id');
      if (stored) {
        setConversationId(stored);
        setConvStartEvent('conversation_resumed');
      } else {
        const newConvId = createSecureClientId('conv');
        setConversationId(newConvId);
        sessionStorage.setItem('agent_widget_conversation_id', newConvId);
        setConvStartEvent('conversation_started');
      }
    }
  }, [isOpen, conversationId, setConversationId]);

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
        content: 'Agent is still loading, please wait...',
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
    trackEvent({
      event_type: 'message_sent',
      actor_type: 'user',
      actor_id: userId,
      agent_id: agentId,
      conversation_id: conversationId || `conv_${Date.now()}`,
      page_context: extractPageContext(),
    });

    const assistantMessageId = (Date.now() + 1).toString();
    let streamedContent = '';

    try {
      const context = extractPageContext();
      const currentConvId = conversationId || createSecureClientId('conv');
      if (!conversationId) {
        setConversationId(currentConvId);
        sessionStorage.setItem('agent_widget_conversation_id', currentConvId);
      }

      addMessage({ id: assistantMessageId, content: '', role: 'assistant', timestamp: new Date(), citations: [] });

      const client = useWebSocket ? wsClient : apiClient;
      const response = await client.sendMessage(
        { content: text, context, userId },
        currentConvId,
        agentId,
        (chunk) => {
          if (chunk.type === 'status' && chunk.content) {
            setTypingStatus(chunk.content);
          } else if (chunk.type === 'content' && chunk.content) {
            setTypingStatus('');
            streamedContent += chunk.content;
            updateMessage(assistantMessageId, { content: streamedContent });
          }
        }
      );

      updateMessage(assistantMessageId, {
        content: response.content,
        citations: response.citations,
        products: response.products,
        dealers: response.dealers,
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
      setTypingStatus('');
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
            typingStatus={typingStatus}
            isExpanded={isExpanded}
            isMobile={isMobile}
            onSendMessage={handleSendMessage}
            onClose={() => setIsOpen(false)}
            onToggleExpand={toggleExpanded}
            onRegenerate={handleRegenerate}
            onFeedback={setMessageFeedback}
          />
        </div>
      )}
    </div>
  );
}

export default App;
