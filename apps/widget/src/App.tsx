import React from 'react';
import { WidgetButton } from './components/WidgetButton';
import { ChatWindow } from './components/ChatWindow';
import { useWidgetStore } from './stores/widgetStore';
import { useFullscreen } from './hooks/useFullscreen';
import { APIClient } from './utils/apiClient';
import { extractPageContext } from './utils/pageContext';
import type { WidgetConfig } from './types';
import './App.css';
import './styles/responsive.css';

const apiClient = new APIClient('http://localhost:8000');

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
    setIsOpen,
    addMessage,
    updateMessage,
    setIsTyping,
    setConfig,
    setConversationId,
    setExpanded
  } = useWidgetStore();

  // Fullscreen hook for expand/collapse functionality
  const { isExpanded: isFullscreen, toggleExpanded, isMobile } = useFullscreen();

  // Sync fullscreen state with store
  React.useEffect(() => {
    setExpanded(isFullscreen);
  }, [isFullscreen, setExpanded]);

  // Generate persistent user_id and conversation_id
  const [userId] = React.useState(() => {
    const stored = localStorage.getItem('agent_widget_user_id');
    if (stored) return stored;
    const newId = `user_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    localStorage.setItem('agent_widget_user_id', newId);
    return newId;
  });

  // Fetch agent ID dynamically from URL or config
  const [agentId, setAgentId] = React.useState<string | null>(null);

  React.useEffect(() => {
    // Priority: URL query param > config.agentId > data-agent-id attribute > fetch from API

    // 1. Check URL query parameter (highest priority)
    const urlParams = new URLSearchParams(window.location.search);
    const urlAgentId = urlParams.get('agent_id');
    if (urlAgentId) {
      setAgentId(urlAgentId);
      console.log('[Widget] Using agent ID from URL:', urlAgentId);
      return;
    }

    // 2. Check config prop
    if (config?.agentId) {
      setAgentId(config.agentId);
      console.log('[Widget] Using agent ID from config:', config.agentId);
      return;
    }

    // 3. Check for data-agent-id attribute on script tag
    const scriptTag = document.querySelector('script[data-agent-id]') as HTMLScriptElement;
    if (scriptTag?.dataset.agentId) {
      setAgentId(scriptTag.dataset.agentId);
      console.log('[Widget] Using agent ID from data attribute:', scriptTag.dataset.agentId);
      return;
    }

    // 4. Fallback: Fetch first available agent from API
    const fetchAgent = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/v1/admin/agents/');
        if (response.ok) {
          const agents = await response.json();
          if (agents.length > 0) {
            setAgentId(agents[0].id);
            console.log('[Widget] Using first available agent:', agents[0].name, agents[0].id);
          } else {
            console.error('[Widget] No agents found in database');
          }
        }
      } catch (error) {
        console.error('[Widget] Failed to fetch agent:', error);
      }
    };

    fetchAgent();
  }, [config?.agentId]);

  React.useEffect(() => {
    if (config) {
      setConfig(config);
    }
  }, [config, setConfig]);

  // Initialize conversation_id when widget first opens
  React.useEffect(() => {
    if (isOpen && !conversationId) {
      const stored = sessionStorage.getItem('agent_widget_conversation_id');
      if (stored) {
        setConversationId(stored);
      } else {
        const newConvId = `conv_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        setConversationId(newConvId);
        sessionStorage.setItem('agent_widget_conversation_id', newConvId);
      }
    }
  }, [isOpen, conversationId, setConversationId]);

  // Handle WebSocket connection for real-time admin messages
  React.useEffect(() => {
    if (!conversationId) return;

    const ws = apiClient.connectWebSocket(conversationId, (data) => {
      console.log('[App] WebSocket message received:', data);

      if (data.type === 'admin_message') {
        // Add new admin message as assistant
        addMessage({
          id: Date.now().toString(),
          content: data.content,
          role: 'assistant',
          timestamp: new Date()
        });

        // Ensure typing indicator is cleared since a human answered
        setIsTyping(false);
      } else if (data.type === 'control_status') {
        console.log('[App] Control status update:', data.is_human_in_control);
        // Optionally update store if we want to show a UI indicator
      }
    });

    return () => {
      ws.close();
    };
  }, [conversationId, addMessage, setIsTyping]);

  const handleToggleWidget = () => {
    setIsOpen(!isOpen);
  };

  const handleSendMessage = async (text: string) => {
    // Check if agent is loaded
    if (!agentId) {
      console.error('[Widget] Agent ID not available yet');
      addMessage({
        id: Date.now().toString(),
        content: 'Agent is still loading, please wait...',
        role: 'assistant',
        timestamp: new Date()
      });
      return;
    }

    // Add user message
    addMessage({
      id: Date.now().toString(),
      content: text,
      role: 'user',
      timestamp: new Date()
    });

    // Set typing indicator
    setIsTyping(true);

    try {
      // Extract page context
      const context = extractPageContext();

      // Use conversation ID from store (or create new one)
      const currentConvId = conversationId || `conv_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      if (!conversationId) {
        setConversationId(currentConvId);
        sessionStorage.setItem('agent_widget_conversation_id', currentConvId);
      }

      // Create placeholder message for streaming
      const assistantMessageId = (Date.now() + 1).toString();
      let streamedContent = '';  // Track streamed content

      console.log('[App] Adding placeholder message:', assistantMessageId);

      addMessage({
        id: assistantMessageId,
        content: '',
        role: 'assistant',
        timestamp: new Date(),
        citations: []
      });

      console.log('[App] Calling sendMessage with streaming...');

      // Send message to API with streaming enabled
      const response = await apiClient.sendMessage({
        content: text,
        context,
        userId  // Pass the persistent user_id
      }, currentConvId, agentId, (chunk) => {
        // Handle streaming chunks
        console.log('[App] Stream chunk received:', chunk);
        if (chunk.type === 'content' && chunk.content) {
          // Append new content
          streamedContent += chunk.content;
          console.log('[App] Updating message with content:', streamedContent.substring(0, 50) + '...');
          // Update the message with accumulated content
          updateMessage(assistantMessageId, {
            content: streamedContent
          });
        } else if (chunk.type === 'status') {
          // Optionally show status updates (e.g., "Retrieving context...")
          console.log('[App] Status:', chunk.content);
        }
      });

      console.log('[App] Stream complete, final response:', response);

      // Update final message with complete response, citations, products, and dealers
      updateMessage(assistantMessageId, {
        content: response.content,
        citations: response.citations,
        products: response.products,  // Phase 5: Product cards
        dealers: response.dealers      // Phase 5: Dealer cards
      });
    } catch (error) {
      console.error('Error sending message:', error);

      // Add error message
      addMessage({
        id: (Date.now() + 1).toString(),
        content: 'Sorry, I encountered an error. Please try again.',
        role: 'assistant',
        timestamp: new Date()
      });
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="widget-container">
      <WidgetButton onClick={handleToggleWidget} />

      {isOpen && (
        <div className={`widget-overlay ${isExpanded ? 'expanded' : ''}`}>
          <ChatWindow
            messages={messages}
            isTyping={isTyping}
            isExpanded={isExpanded}
            isMobile={isMobile}
            onSendMessage={handleSendMessage}
            onClose={() => setIsOpen(false)}
            onToggleExpand={toggleExpanded}
          />
        </div>
      )}
    </div>
  );
}

export default App;
