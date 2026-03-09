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

const apiClient = new APIClient('http://localhost:8000');
const wsClient = new WebSocketClient('http://localhost:8000');

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
    const newId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    localStorage.setItem('agent_widget_user_id', newId);
    return newId;
  });

  const [agentId, setAgentId] = React.useState<string | null>(null);
  const [useWebSocket, setUseWebSocket] = React.useState(true);
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
    fetch('http://localhost:8000/api/v1/admin/agents/')
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
        const agentRes = await fetch(`http://localhost:8000/api/v1/admin/agents/${agentId}`);
        if (!agentRes.ok) return;
        const agent = await agentRes.json();
        const brandId: string | undefined = agent.brand_id;
        // Read WebSocket setting from agent config (default true if not set)
        const wsEnabled = agent.configuration?.features?.websockets !== false;
        setUseWebSocket(wsEnabled);
        if (!brandId) return;

        // 2. Get brand → extract colors / identity
        const brandRes = await fetch(`http://localhost:8000/api/v1/admin/brands/${brandId}`);
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
  }, [agentId, setBrandTheme]);

  React.useEffect(() => {
    if (config) setConfig(config);
  }, [config, setConfig]);

  // ── Widget control channel (human takeover) ───────────────────
  React.useEffect(() => {
    if (!conversationId) return;

    const ws = new WebSocket(`ws://localhost:8000/api/v1/messages/ws/widget/${conversationId}`);
    controlChannelRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string);
        if (msg.type === 'control_status') {
          setHumanInControl(msg.is_human_in_control ?? false);
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

    const heartbeat = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30_000);

    return () => {
      clearInterval(heartbeat);
      ws.close();
      controlChannelRef.current = null;
      setHumanInControl(false);
    };
  }, [conversationId]);

  // ── Initialize conversation ID ────────────────────────────────
  React.useEffect(() => {
    if (isOpen && !conversationId) {
      const stored = sessionStorage.getItem('agent_widget_conversation_id');
      if (stored) {
        setConversationId(stored);
        setConvStartEvent('conversation_resumed');
      } else {
        const newConvId = `conv_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
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

    try {
      const context = extractPageContext();
      const currentConvId = conversationId || `conv_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      if (!conversationId) {
        setConversationId(currentConvId);
        sessionStorage.setItem('agent_widget_conversation_id', currentConvId);
      }

      const assistantMessageId = (Date.now() + 1).toString();
      let streamedContent = '';

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
      addMessage({
        id: (Date.now() + 1).toString(),
        content: 'Sorry, I encountered an error. Please try again.',
        role: 'assistant',
        timestamp: new Date(),
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
