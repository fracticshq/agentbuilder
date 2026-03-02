import React from 'react';
import type { Message, BrandThemeTokens } from '../types';
import { MessageBubble } from './MessageBubble';
import { useWidgetStore } from '../stores/widgetStore';
import { NOVA_LOGO } from '../utils/brandTheme';
import { useCyclingText } from '../hooks/useCyclingText';

interface ChatWindowProps {
  messages: Message[];
  isTyping: boolean;
  isExpanded?: boolean;
  isMobile?: boolean;
  onSendMessage: (text: string) => void;
  onClose: () => void;
  onToggleExpand?: () => void;
}

// ── Icon components ────────────────────────────────────────────
const MicIcon = ({ color }: { color: string }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    <line x1="8" y1="23" x2="16" y2="23" />
  </svg>
);

const SendIcon = ({ color }: { color: string }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);

const CloseIcon = ({ color }: { color: string }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);


// ── Themed input row ───────────────────────────────────────────
interface InputRowProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  placeholder: string;
  tk: BrandThemeTokens;
}

const InputRow: React.FC<InputRowProps> = ({ value, onChange, onSubmit, placeholder, tk }) => {
  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <div
      className="chat-input-row"
      style={{
        background: tk.inputBg,
        border: `1px solid ${tk.inputBorder}`,
        boxShadow: tk.mode === 'light' ? '0 2px 12px rgba(0,0,0,0.06)' : 'none',
      }}
    >
      <input
        type="text"
        className="chat-input-field"
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={handleKey}
        placeholder={placeholder}
        style={{ color: tk.inputColor }}
        autoComplete="off"
      />
      <div className="chat-input-divider" style={{ background: tk.dividerColor }} />
      <button
        type="button"
        className="chat-input-btn"
        style={{ background: tk.voiceBg, borderColor: tk.voiceBorder }}
        aria-label="Voice input"
      >
        <MicIcon color={tk.voiceIconColor} />
      </button>
      <button
        type="button"
        className="chat-send-btn"
        onClick={onSubmit}
        disabled={!value.trim()}
        style={{ background: tk.sendBg, boxShadow: tk.sendShad }}
        aria-label="Send"
      >
        <SendIcon color="#ffffff" />
      </button>
    </div>
  );
};

// ── Main component ─────────────────────────────────────────────
export const ChatWindow: React.FC<ChatWindowProps> = ({
  messages,
  isTyping,
  isExpanded = false,
  isMobile = false,
  onSendMessage,
  onClose,
}) => {
  const { brandTheme } = useWidgetStore();
  const [inputValue, setInputValue] = React.useState('');
  const messagesEndRef = React.useRef<HTMLDivElement>(null);

  const tk = brandTheme?.tokens;
  const mode = brandTheme?.mode ?? 'dark';
  const isLanding = messages.length === 0 && !isTyping;

  const categories = brandTheme?.cyclingCategories ?? [];
  const { text: cyclingText, visible: cyclingVisible } = useCyclingText(categories);
  const hasCycling = categories.length > 0;

  const chatLogo = mode === 'dark'
    ? brandTheme?.chatLogoDarkUrl
    : brandTheme?.chatLogoLightUrl;

  React.useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const handleSubmit = () => {
    if (inputValue.trim()) {
      onSendMessage(inputValue.trim());
      setInputValue('');
    }
  };

  const handleChipClick = (chip: string) => {
    onSendMessage(chip);
  };

  // Fallback tokens if brandTheme not yet loaded
  const panelBg = tk?.panelBg ?? (mode === 'dark'
    ? 'linear-gradient(160deg,#080d14 0%,#0d1520 30%,#061008 100%)'
    : 'linear-gradient(160deg,#fdfaf5 0%,#ede8df 100%)');
  const orbBg = tk?.orbBg ?? 'radial-gradient(circle,rgba(100,100,200,0.1) 0%,transparent 70%)';
  const topbarColor = mode === 'dark' ? 'rgba(255,255,255,0.55)' : 'rgba(60,40,20,0.45)';
  const titleColor = tk?.titleColor ?? (mode === 'dark' ? '#fff' : '#1a1208');
  const subtitleColor = tk?.subtitleColor ?? (mode === 'dark' ? 'rgba(255,255,255,0.45)' : 'rgba(60,40,20,0.5)');
  const accentColor = tk?.accentColor ?? '#6366f1';

  return (
    <div
      className={`chat-panel ${isExpanded ? 'expanded' : ''} ${isMobile ? 'mobile' : ''}`}
      style={{ background: panelBg }}
    >
      {/* Background orb */}
      <div className="chat-panel-orb" style={{ background: orbBg }} />

      {/* Top bar */}
      <div className="chat-topbar">
        {!brandTheme?.hideNovaLogo && (
          <img
            src={NOVA_LOGO}
            alt="NOVA"
            className="chat-topbar-nova"
            style={{
              height: 16,
              filter: mode === 'light' ? 'invert(1) opacity(0.5)' : 'opacity(0.6)',
            }}
          />
        )}
        <button
          className="chat-topbar-close"
          onClick={onClose}
          aria-label="Close chat"
          style={{ color: topbarColor }}
        >
          <CloseIcon color={topbarColor} />
        </button>
      </div>

      {/* Landing state: hero + chips + input */}
      {isLanding ? (
        <>
          <div className="chat-hero">
            <div className="chat-hero-logo">
              {chatLogo ? (
                <img src={chatLogo} alt={brandTheme?.brandName ?? 'AI'} />
              ) : (
                <div
                  className="chat-hero-logo-placeholder"
                  style={{
                    background: tk?.bubbleBg ?? '#111',
                    border: `1.5px solid ${tk?.bubbleBorder ?? 'rgba(100,100,200,0.2)'}`,
                    color: accentColor,
                  }}
                >
                  {(brandTheme?.brandName ?? 'AI').charAt(0)}
                </div>
              )}
            </div>
            <div className="chat-hero-title" style={{ color: titleColor }}>
              {brandTheme?.heroTitle ?? 'How can I help?'}
            </div>
            {hasCycling ? (
              <>
                <div className="chat-hero-subtitle" style={{ color: subtitleColor }}>
                  {brandTheme?.heroSubtitle ?? 'Ask me anything about'}
                </div>
                <div className="chat-hero-cycling-row">
                  <span
                    className="chat-hero-cycling-text"
                    style={{
                      color: accentColor,
                      opacity: cyclingVisible ? 1 : 0,
                      transform: cyclingVisible ? 'translateY(0)' : 'translateY(6px)',
                      transition: 'opacity 0.4s ease, transform 0.4s ease',
                    }}
                  >
                    {cyclingText}
                  </span>
                </div>
              </>
            ) : (
              <div className="chat-hero-subtitle" style={{ color: subtitleColor }}>
                {brandTheme?.heroSubtitle ?? 'Ask me anything'}
              </div>
            )}
          </div>

          <div className="chat-bottom">
            {brandTheme && brandTheme.suggestionChips.length > 0 && (
              <div className="chat-chips-row">
                {brandTheme.suggestionChips.map(chip => (
                  <button
                    key={chip}
                    className="chat-chip"
                    onClick={() => handleChipClick(chip)}
                    style={{
                      background: tk?.chipBg,
                      borderColor: tk?.chipBorder,
                      color: tk?.chipColor,
                    }}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}
            {tk && (
              <InputRow
                value={inputValue}
                onChange={setInputValue}
                onSubmit={handleSubmit}
                placeholder="Ask something..."
                tk={tk}
              />
            )}
          </div>
        </>
      ) : (
        /* Chat state: messages + input */
        <>
          <div
            className="chat-messages-area"
            style={{
              // tint scrollbar thumb with accent
              ['--scrollbar-thumb' as string]: tk ? `${tk.accentColor}30` : 'rgba(255,255,255,0.1)',
            }}
          >
            {messages.map(message => (
              <MessageBubble
                key={message.id}
                message={message}
                userMsgBg={tk?.userMsgBg ?? accentColor}
                userMsgColor={tk?.userMsgColor ?? '#fff'}
                assistantMsgBg={tk?.assistantMsgBg ?? 'rgba(255,255,255,0.08)'}
                assistantMsgColor={tk?.assistantMsgColor ?? '#fff'}
              />
            ))}

            {isTyping && (
              <div className="typing-indicator">
                <div
                  className="typing-dots"
                  style={{ background: tk?.assistantMsgBg ?? 'rgba(255,255,255,0.08)' }}
                >
                  <span className="dot" style={{ background: tk?.assistantMsgColor ?? 'rgba(255,255,255,0.6)' }} />
                  <span className="dot" style={{ background: tk?.assistantMsgColor ?? 'rgba(255,255,255,0.6)' }} />
                  <span className="dot" style={{ background: tk?.assistantMsgColor ?? 'rgba(255,255,255,0.6)' }} />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="chat-bottom">
            {tk && (
              <InputRow
                value={inputValue}
                onChange={setInputValue}
                onSubmit={handleSubmit}
                placeholder="Type your message..."
                tk={tk}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
};
