import React from 'react';
import { useWidgetStore } from '../stores/widgetStore';

interface WidgetButtonProps {
  onClick: () => void;
}

const ChatIcon = ({ color }: { color: string }) => (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const CloseIcon = ({ color }: { color: string }) => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

export const WidgetButton: React.FC<WidgetButtonProps> = ({ onClick }) => {
  const { isOpen, brandTheme } = useWidgetStore();
  const tk = brandTheme?.tokens;
  const mode = brandTheme?.mode ?? 'dark';

  const chatLogo = mode === 'dark'
    ? brandTheme?.chatLogoDarkUrl
    : brandTheme?.chatLogoLightUrl;

  const bubbleBg = tk?.bubbleBg ?? '#111';
  const bubbleBorder = tk?.bubbleBorder ?? 'rgba(100,100,200,0.2)';
  const bubbleShad = tk?.bubbleShad ?? '0 6px 24px rgba(0,0,0,0.3)';
  const ringColor = tk?.bubbleRing ?? 'rgba(100,100,200,0.3)';
  const iconColor = mode === 'dark' ? 'rgba(255,255,255,0.85)' : 'rgba(30,20,10,0.75)';

  return (
    <button
      onClick={onClick}
      className="widget-bubble"
      aria-label={isOpen ? 'Close chat' : 'Open chat'}
      style={{
        background: bubbleBg,
        border: `1.5px solid ${bubbleBorder}`,
        boxShadow: bubbleShad,
      }}
    >
      {/* Pulse ring — only when closed */}
      {!isOpen && (
        <span
          className="widget-bubble-ring"
          style={{ color: ringColor, borderColor: ringColor }}
        />
      )}

      {isOpen ? (
        <CloseIcon color={iconColor} />
      ) : chatLogo ? (
        <img src={chatLogo} alt="chat" className="widget-bubble-logo" />
      ) : (
        <ChatIcon color={iconColor} />
      )}
    </button>
  );
};
