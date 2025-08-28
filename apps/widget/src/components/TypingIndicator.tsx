import React from 'react';

export const TypingIndicator: React.FC = () => {
  return (
    <div className="message-bubble assistant">
      <div className="message-content assistant-message">
        <div className="typing-indicator">
          <div className="typing-dots">
            <span className="dot"></span>
            <span className="dot"></span>
            <span className="dot"></span>
          </div>
          <span className="typing-text">Assistant is typing...</span>
        </div>
      </div>
    </div>
  );
};
