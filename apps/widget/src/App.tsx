import React from 'react';
import { WidgetButton } from './components/WidgetButton';
import { ChatWindow } from './components/ChatWindow';
import { BirthDetailsForm } from './components/LalKitab/BirthDetailsForm';
import { LalKitabSideChart } from './components/LalKitab/LalKitabSideChart';
import { useWidgetStore } from './stores/widgetStore';
import { useFullscreen } from './hooks/useFullscreen';
import { APIClient } from './utils/apiClient';
import { WebSocketClient } from './utils/wsClient';
import { buildBrandTheme } from './utils/brandTheme';
import { shouldAutoOpenFromSearch } from './utils/bootstrap';
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
const apiClient = new APIClient(API_BASE);
const wsClient = new WebSocketClient(API_BASE);
const isEmbedded = window.parent !== window || new URLSearchParams(window.location.search).get('embedded') === '1';

function getEmbeddingParentOrigin(): string | null {
  if (window.parent === window || !document.referrer) {
    return null;
  }

  try {
    const origin = new URL(document.referrer).origin;
    return origin === 'null' ? null : origin;
  } catch {
    return null;
  }
}

function createSecureClientId(prefix: string): string {
  if (window.crypto?.randomUUID) {
    return `${prefix}_${window.crypto.randomUUID()}`;
  }

  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${prefix}_${value}`;
}

function getWidgetSessionStorageKey(agentId: string): string {
  return `agent_widget_session_v1_${encodeURIComponent(window.location.origin)}_${agentId}`;
}

function readStoredWidgetSession(agentId: string): { conversationId?: string; userId?: string; sessionToken?: string } | undefined {
  try {
    const raw = sessionStorage.getItem(getWidgetSessionStorageKey(agentId));
    return raw ? JSON.parse(raw) : undefined;
  } catch {
    return undefined;
  }
}

interface AppProps {
  config?: WidgetConfig;
}

function App({ config }: AppProps) {
  const configuredApiBase = (config?.apiUrl || API_BASE).replace(/\/$/, '');
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
    setMessages,
    setExpanded,
    setBrandTheme,
    setHumanInControl,
    setMessageFeedback,
    removeMessage,
    brandTheme,
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

  React.useEffect(() => {
    apiClient.setBaseUrl(configuredApiBase);
    wsClient.setBaseUrl(configuredApiBase);
  }, [configuredApiBase]);

  // user_id is issued by the server via the signed widget session below. Keep
  // only an in-memory fallback so every page load/new visitor starts clean.
  const [userId, setUserId] = React.useState(() => createSecureClientId('user'));

  const [agentId, setAgentId] = React.useState<string | null>(null);
  const [useWebSocket, setUseWebSocket] = React.useState(true);
  const [humanTakeoverEnabled, setHumanTakeoverEnabled] = React.useState(false);
  const [showSources, setShowSources] = React.useState(config?.showSources ?? false);
  const [showProductCards, setShowProductCards] = React.useState(config?.showProductCards ?? true);
  const [showInquiry, setShowInquiry] = React.useState(false);
  // 'basic' = the lightweight cycling indicator; 'advanced' = the live step
  // timeline. Admin-configurable per agent; defaults to 'basic'.
  const [activityMode, setActivityMode] = React.useState<'basic' | 'advanced'>('basic');
  // In advanced mode: 'temporary' (timeline disappears after the answer) or
  // 'persistent' (stays attached to each answer, Claude/ChatGPT style).
  const [activityPersistence, setActivityPersistence] = React.useState<'temporary' | 'persistent'>('temporary');
  const [unavailableMessage, setUnavailableMessage] = React.useState<string | null>(null);
  // Holds the pending conversation lifecycle event type until agentId is ready.
  const [convStartEvent, setConvStartEvent] = React.useState<'conversation_started' | 'conversation_resumed' | null>(null);

  // ── Lal Kitab form-first flow ──────────────────────────────────
  // Only active for astrology_lalkitab agents with lalkitab.require_birth_profile_form
  // enabled in their configuration (opt-in, see message_service.py
  // _lalkitab_requires_birth_profile_form). All other agents are unaffected.
  const [lalkitabFormRequired, setLalkitabFormRequired] = React.useState(false);
  const [lalkitabProfileStatus, setLalkitabProfileStatus] = React.useState<'unknown' | 'missing' | 'confirmed'>('unknown');
  const [lalkitabChart, setLalkitabChart] = React.useState<unknown>(null);
  const [lalkitabReportText, setLalkitabReportText] = React.useState<string | undefined>(undefined);
  // Maps this brand's real theme tokens onto the birth-details form's CSS
  // variables, so the form matches the same light/dark palette the rest of
  // the widget uses instead of a hardcoded color scheme of its own.
  const lalkitabCssVars = React.useMemo(() => {
    const tk = brandTheme?.tokens;
    const mode = brandTheme?.mode ?? 'light';
    const accent = tk?.accentColor ?? '#c2410c';
    const lightArrow = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='rgba(60,40,20,0.45)' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E\")";
    const darkArrow = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='rgba(255,255,255,0.4)' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E\")";
    return {
      '--lk-bg': tk?.panelBg ?? (mode === 'dark'
        ? 'linear-gradient(160deg,#080d14 0%,#0d1520 30%,#061008 100%)'
        : 'linear-gradient(160deg,#fdfaf5 0%,#ede8df 100%)'),
      '--lk-fg': tk?.titleColor ?? (mode === 'dark' ? '#ffffff' : '#1a1208'),
      '--lk-muted': tk?.subtitleColor ?? (mode === 'dark' ? 'rgba(255,255,255,0.45)' : 'rgba(60,40,20,0.5)'),
      '--lk-card-bg': mode === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.7)',
      '--lk-border': tk?.dividerColor ?? (mode === 'dark' ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'),
      '--lk-card-shadow': mode === 'dark' ? '0 10px 30px rgba(0,0,0,0.35)' : '0 10px 30px rgba(0,0,0,0.08)',
      '--lk-input-bg': tk?.inputBg ?? (mode === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.85)'),
      '--lk-input-border': tk?.inputBorder ?? (mode === 'dark' ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.12)'),
      '--lk-accent': accent,
      '--lk-accent-grad': tk?.sendBg ?? `linear-gradient(135deg,${accent},${accent})`,
      '--lk-accent-shadow': tk?.sendShad ?? `0 4px 14px ${accent}55`,
      '--lk-select-arrow': mode === 'dark' ? darkArrow : lightArrow,
    } as React.CSSProperties;
  }, [brandTheme]);

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
        const agentRes = await fetch(`${configuredApiBase}/api/v1/public/agents/${agentId}`);
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
        const inquiryConfig = agent.configuration?.inquiry || {};
        const shouldShowInquiry = Boolean(inquiryConfig.enabled);
        const domainTemplate = agent.configuration?.domain?.template || agent.configuration?.agent_template || agent.configuration?.template;
        const lalkitabCfg = agent.configuration?.lalkitab || {};
        const isLalkitabAgent = String(domainTemplate || '').toLowerCase().includes('lalkitab') || String(domainTemplate || '').toLowerCase().includes('lal_kitab') || String(domainTemplate || '').toLowerCase().includes('lal-kitab') || String(domainTemplate || '').toLowerCase().includes('lal kitab');
        // Default ON for every Lal Kitab agent — set
        // configuration.lalkitab.require_birth_profile_form = false explicitly
        // to opt a specific agent out of the form-first flow.
        const formFlagRaw = lalkitabCfg.require_birth_profile_form;
        const formRequired = formFlagRaw === undefined || formFlagRaw === null ? true : Boolean(formFlagRaw);
        setLalkitabFormRequired(isLalkitabAgent && formRequired);
        const resolvedActivityMode =
          (widgetChannel.activity_mode ?? features.activity_mode) === 'advanced' ? 'advanced' : 'basic';
        const resolvedActivityPersistence =
          (widgetChannel.activity_persistence ?? features.activity_persistence) === 'persistent' ? 'persistent' : 'temporary';
        setUseWebSocket(wsEnabled);
        setHumanTakeoverEnabled(takeoverEnabled);
        setShowSources(shouldShowSources);
        setShowProductCards(shouldShowProductCards);
        setShowInquiry(shouldShowInquiry);
        setActivityMode(resolvedActivityMode);
        setActivityPersistence(resolvedActivityPersistence);
        if (!brandId) return;

        // 2. Get brand → extract colors / identity
        const brandRes = await fetch(`${configuredApiBase}/api/v1/public/brands/${brandId}`);
        if (!brandRes.ok) return;
        const brand = await brandRes.json();

        const theme = buildBrandTheme(brand.name || 'AI', brand.colors || {});
        setBrandTheme(theme);

      } catch {
        setUnavailableMessage('NOVA could not load this agent right now. Check that the API is running and the agent is active.');
      }
    };

    fetchBrandTheme();
  }, [agentId, configuredApiBase, config?.enableHumanTakeover, config?.showProductCards, config?.showSources, setBrandTheme]);

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

    const parentOrigin = getEmbeddingParentOrigin();
    if (!parentOrigin) return;

    window.parent.postMessage({
      type: 'agentbuilder-widget-state',
      isOpen,
      isExpanded,
    }, parentOrigin);
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
    const sessionToken = apiClient.getSessionToken();
    if (!sessionToken) {
      setHumanInControl(false);
      return;
    }
    const controlWsBase = configuredApiBase.replace(/^http/, 'ws');

    const connect = () => {
      if (destroyed) return;
      // The token travels in a WebSocket subprotocol rather than the URL so it
      // is not copied into browser, proxy, or application access logs.
      ws = new WebSocket(
        `${controlWsBase}/api/v1/messages/ws/widget/${encodeURIComponent(conversationId)}`,
        ['widget-session', sessionToken],
      );
      controlChannelRef.current = ws;

      ws.onopen = () => {
        reconnectDelay = 1_000;
        ws!.send(JSON.stringify({ type: 'register' }));
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
  }, [conversationId, agentId, configuredApiBase, humanTakeoverEnabled, setHumanInControl, addMessage]);

  // ── Establish/resume a server-issued, signed session ─────────
  // The signed token is retained only in tab-scoped sessionStorage. The API
  // remains the source of truth; the widget hydrates history after resuming.
  React.useEffect(() => {
    if (!isOpen || conversationId || !agentId) return;

    let cancelled = false;

    (async () => {
      try {
        const stored = readStoredWidgetSession(agentId);
        const session = await apiClient.startSession(agentId, stored?.sessionToken);
        if (cancelled) return;
        apiClient.setSessionToken(session.sessionToken);
        wsClient.setSessionToken(session.sessionToken);
        setUserId(session.userId);
        setConversationId(session.conversationId);
        sessionStorage.setItem(getWidgetSessionStorageKey(agentId), JSON.stringify({
          version: 1,
          agentId,
          conversationId: session.conversationId,
          userId: session.userId,
          sessionToken: session.sessionToken,
          savedAt: new Date().toISOString(),
        }));
        const history = await apiClient.getHistory();
        if (cancelled) return;
        if (history.length) setMessages(history);
        setConvStartEvent(stored?.conversationId === session.conversationId ? 'conversation_resumed' : 'conversation_started');
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
  }, [isOpen, conversationId, agentId, setConversationId, setMessages]);

  // ── Lal Kitab: always require the birth-details form fresh on every page
  // load/refresh — even if this browser session already has a confirmed
  // profile stored server-side for this conversation. We deliberately do
  // NOT call GET /lalkitab/profile to auto-resume past the form here: a
  // refresh must show the form again, not silently jump to chat.
  React.useEffect(() => {
    if (!lalkitabFormRequired) return;
    setLalkitabProfileStatus('missing');
  }, [lalkitabFormRequired]);

  // ── Fire conversation lifecycle event once both IDs are ready ─
  React.useEffect(() => {
    if (!convStartEvent || !conversationId || !agentId) return;
    trackEvent({
      event_type: convStartEvent,
      actor_type: 'user',
      actor_id: userId,
      agent_id: agentId,
      conversation_id: conversationId,
      sessionToken: apiClient.getSessionToken(),
      page_context: extractPageContext(),
    });
    setConvStartEvent(null);
  }, [convStartEvent, conversationId, agentId, userId]);

  const handleToggleWidget = () => setIsOpen(!isOpen);

  const handleSendMessage = async (text: string, opts?: { inquiryJustCompleted?: boolean }) => {
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
        const stored = readStoredWidgetSession(agentId);
        const session = await apiClient.startSession(agentId, stored?.sessionToken);
        apiClient.setSessionToken(session.sessionToken);
        wsClient.setSessionToken(session.sessionToken);
        currentConvId = session.conversationId;
        currentUserId = session.userId;
        setUserId(session.userId);
        setConversationId(session.conversationId);
        sessionStorage.setItem(getWidgetSessionStorageKey(agentId), JSON.stringify({
          version: 1,
          agentId,
          conversationId: session.conversationId,
          userId: session.userId,
          sessionToken: session.sessionToken,
          savedAt: new Date().toISOString(),
        }));
      }

      trackEvent({
        event_type: 'message_sent',
        actor_type: 'user',
        actor_id: currentUserId,
        agent_id: agentId,
        conversation_id: currentConvId,
        sessionToken: apiClient.getSessionToken(),
        page_context: extractPageContext(),
      });

      addMessage({ id: assistantMessageId, content: '', role: 'assistant', timestamp: new Date(), citations: [] });
      updateActivity({
        steps: [{ id: 'local:working', label: 'Reading your message', detail: 'I’m checking what is needed before answering.', status: 'running' }],
      });

      const client = useWebSocket ? wsClient : apiClient;
      const response = await client.sendMessage(
        { content: text, context, userId: currentUserId, inquiryJustCompleted: opts?.inquiryJustCompleted },
        currentConvId,
        agentId,
        (chunk) => {
          if (chunk.type === 'content' && chunk.content) {
            // Answer started streaming — collapse any in-flight steps to done.
            if (!streamedContent) updateActivity(finalizeActivity(activityRef.current));
            streamedContent += chunk.content;
            updateMessage(assistantMessageId, { content: streamedContent });
          } else if (chunk.type === 'final_answer' && chunk.content) {
            // Authoritative full answer — guarantees nothing is lost if a
            // content chunk was dropped mid-stream.
            if (chunk.content.length >= streamedContent.length) {
              streamedContent = chunk.content;
              updateMessage(assistantMessageId, { content: streamedContent });
            }
            updateActivity(finalizeActivity(activityRef.current));
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
        commerce: response.commerce,
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
        sessionToken: apiClient.getSessionToken(),
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

  // V2 inquiry: after form submission the success message is shown as an
  // assistant bubble directly by ChatWindow. The next real user message
  // (anything the user types after that) must carry inquiry_just_completed=true
  // so the backend skips the inquiry adapter for that one turn.
  const handleSendMessageWithReset = (text: string) => {
    // Show the success message as an assistant bubble directly — no LLM call.
    // Include inquiry_pending.submitted so the next user message is treated
    // as a clean turn (not part of an ongoing inquiry flow).
    addMessage({
      id: Date.now().toString(),
      content: text,
      role: 'assistant',
      timestamp: new Date(),
      metadata: { inquiry_pending: { submitted: true } },
    });
  };

  const handleRegenerate = (messageId: string) => {    const msgIndex = messages.findIndex(m => m.id === messageId);
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

      {isOpen && lalkitabFormRequired && lalkitabProfileStatus === 'missing' && (
        <div className="widget-overlay expanded">
          <div className="lk-root" style={lalkitabCssVars}>
            <BirthDetailsForm
              agentId={agentId || ''}
              apiUrl={configuredApiBase}
              sessionToken={apiClient.getSessionToken()}
              onGenerated={({ kundaliChart }) => {
                setLalkitabChart(kundaliChart);
                setLalkitabProfileStatus('confirmed');
              }}
            />
          </div>
        </div>
      )}

      {isOpen && (!lalkitabFormRequired || lalkitabProfileStatus === 'confirmed') && (
        <div className={`widget-overlay ${(isExpanded || lalkitabFormRequired) ? 'expanded' : ''}`}>
          <ChatWindow
            messages={messages}
            isTyping={isTyping}
            activity={activity}
            activityMode={activityMode}
            activityPersistence={activityPersistence}
            isExpanded={isExpanded || lalkitabFormRequired}
            isMobile={isMobile}
            onSendMessage={handleSendMessage}
            onClose={() => setIsOpen(false)}
            onToggleExpand={lalkitabFormRequired ? undefined : toggleExpanded}
            onRegenerate={handleRegenerate}
            onFeedback={setMessageFeedback}
            showSources={showSources}
            showProductCards={showProductCards}
            showInquiry={showInquiry}
            isAgentConfigured={Boolean(agentId)}
            unavailableMessage={unavailableMessage || undefined}
            apiUrl={configuredApiBase}
            agentId={agentId}
            conversationId={conversationId}
            onSendMessageWithReset={handleSendMessageWithReset}
            sideChart={
              lalkitabFormRequired && lalkitabProfileStatus === 'confirmed'
                ? <LalKitabSideChart kundaliChart={lalkitabChart as never} reportText={lalkitabReportText} />
                : undefined
            }
            // Lal Kitab-only greeting defaults, used only when this brand
            // hasn't configured its own hero/chips text (see ChatWindow's
            // fallback order: brandTheme value first, then these defaults).
            // Every other agent/brand is completely unaffected.
            defaultHeroTitle={lalkitabFormRequired ? "Hi, I'm your Lal Kitab guide" : undefined}
            defaultHeroSubtitle={lalkitabFormRequired ? 'How can I help you today?' : undefined}
            defaultSuggestionChips={lalkitabFormRequired ? [
              'Where is my Moon?',
              'How is my career?',
              'Tell me about my life',
              'What is my current dasha?',
            ] : undefined}
          />
        </div>
      )}
    </div>
  );
}

export default App;
