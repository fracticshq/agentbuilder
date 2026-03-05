import React from 'react';
import { useCyclingText } from '../hooks/useCyclingText';

const FALLBACK_MESSAGES = ['Thinking...', 'Planning...', 'Searching knowledge base...', 'Preparing response...'];

interface ThinkingIndicatorProps {
  statusText: string;
  dotColor?: string;
  bgColor?: string;
}

export const ThinkingIndicator: React.FC<ThinkingIndicatorProps> = ({
  statusText,
  dotColor = 'rgba(255,255,255,0.6)',
  bgColor = 'rgba(255,255,255,0.08)',
}) => {
  const { text: cyclingText, visible: cyclingVisible } = useCyclingText(FALLBACK_MESSAGES);

  const displayText = statusText || cyclingText;
  const visible = statusText ? true : cyclingVisible;

  return (
    <div className="typing-indicator">
      <div className="typing-dots" style={{ background: bgColor, display: 'flex', alignItems: 'center', gap: 8, paddingRight: 12 }}>
        <span className="dot" style={{ background: dotColor }} />
        <span className="dot" style={{ background: dotColor }} />
        <span className="dot" style={{ background: dotColor }} />
        <span
          className="thinking-status-text"
          style={{
            opacity: visible ? 1 : 0,
            transform: visible ? 'translateY(0)' : 'translateY(4px)',
            transition: 'opacity 0.3s ease, transform 0.3s ease',
          }}
        >
          {displayText}
        </span>
      </div>
    </div>
  );
};
