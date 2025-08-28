import React from 'react';
import { MessageCircle, X } from 'lucide-react';
import { useWidgetStore } from '../stores/widgetStore';

interface WidgetButtonProps {
  onClick: () => void;
}

export const WidgetButton: React.FC<WidgetButtonProps> = ({ onClick }) => {
  const { isOpen, config } = useWidgetStore();

  const buttonStyle = config?.branding?.primaryColor 
    ? { backgroundColor: config.branding.primaryColor }
    : {};

  return (
    <button
      onClick={onClick}
      className="widget-button"
      style={buttonStyle}
      aria-label={isOpen ? "Close chat" : "Open chat"}
    >
      {isOpen ? (
        <X size={24} />
      ) : (
        <MessageCircle size={24} />
      )}
    </button>
  );
};
