import React from 'react';
import { WidgetButton } from './components/WidgetButton';
import { ChatWindow } from './components/ChatWindow';
import { useWidgetStore } from './stores/widgetStore';
import { APIClient } from './utils/apiClient';
import { extractPageContext } from './utils/pageContext';
import type { WidgetConfig } from './types';
import './App.css';

const apiClient = new APIClient('http://localhost:8000');

interface AppProps {
  config?: WidgetConfig;
}

function App({ config }: AppProps) {
  const {
    isOpen,
    messages,
    isTyping,
    setIsOpen,
    addMessage,
    setIsTyping,
    setConfig
  } = useWidgetStore();

  React.useEffect(() => {
    if (config) {
      setConfig(config);
    }
  }, [config, setConfig]);

  const handleToggleWidget = () => {
    setIsOpen(!isOpen);
  };

  const handleSendMessage = async (text: string) => {
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
      
      // Send message to API
      const response = await apiClient.sendMessage({
        content: text,
        context
      });

      // Add assistant response
      addMessage({
        id: (Date.now() + 1).toString(),
        content: response.content,
        role: 'assistant',
        timestamp: new Date(),
        citations: response.citations
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
        <div className="widget-overlay">
          <ChatWindow
            messages={messages}
            isTyping={isTyping}
            onSendMessage={handleSendMessage}
            onClose={() => setIsOpen(false)}
          />
        </div>
      )}
    </div>
  );
}

export default App;
