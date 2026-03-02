import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatWindow } from './ChatWindow';
import { useWidgetStore } from '../stores/widgetStore';
import { buildBrandTheme } from '../utils/brandTheme';
import type { Message } from '../types';

function resetStore() {
  useWidgetStore.setState({
    isOpen: false,
    isConnected: false,
    isTyping: false,
    messages: [],
    conversationId: undefined,
    error: undefined,
    config: null,
    isExpanded: false,
    brandTheme: null,
  });
}

function setBrand(overrides: Record<string, unknown> = {}) {
  const theme = buildBrandTheme('TestBrand', {
    primary_color: '#00c864',
    default_mode: 'dark',
    hero_title: "I'm TestBrand AI",
    hero_subtitle: 'Ask me about testing',
    suggestion_chips: 'Chip A,Chip B,Chip C',
    ...overrides,
  });
  useWidgetStore.setState({ brandTheme: theme });
  return theme;
}

const noopClose = () => {};
const noopExpand = () => {};

describe('ChatWindow', () => {
  beforeEach(() => {
    resetStore();
  });

  describe('landing state (no messages)', () => {
    it('shows NOVA logo image', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByAltText('NOVA')).toBeInTheDocument();
    });

    it('hides NOVA logo when hideNovaLogo is true', () => {
      setBrand({ hide_nova_logo: true });
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.queryByAltText('NOVA')).not.toBeInTheDocument();
    });

    it('shows hero title and subtitle', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText("I'm TestBrand AI")).toBeInTheDocument();
      expect(screen.getByText('Ask me about testing')).toBeInTheDocument();
    });

    it('shows suggestion chips', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('Chip A')).toBeInTheDocument();
      expect(screen.getByText('Chip B')).toBeInTheDocument();
      expect(screen.getByText('Chip C')).toBeInTheDocument();
    });

    it('clicking a chip fires onSendMessage with chip text', () => {
      setBrand();
      const onSend = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={onSend} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      fireEvent.click(screen.getByText('Chip B'));
      expect(onSend).toHaveBeenCalledWith('Chip B');
    });

    it('shows brand logo when chatLogoDarkUrl is set', () => {
      setBrand({ chat_logo_dark_url: 'https://example.com/logo.png' });
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const img = screen.getByAltText('TestBrand');
      expect(img).toHaveAttribute('src', 'https://example.com/logo.png');
    });

    it('shows placeholder initial when no logo', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('T')).toBeInTheDocument(); // first letter of 'TestBrand'
    });

    it('sends message via input on Enter', () => {
      setBrand();
      const onSend = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={onSend} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const input = screen.getByPlaceholderText('Ask something...');
      fireEvent.change(input, { target: { value: 'Hello AI' } });
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(onSend).toHaveBeenCalledWith('Hello AI');
    });

    it('does not send empty message on Enter', () => {
      setBrand();
      const onSend = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={onSend} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const input = screen.getByPlaceholderText('Ask something...');
      fireEvent.keyDown(input, { key: 'Enter' });
      expect(onSend).not.toHaveBeenCalled();
    });

    it('sends message via send button click', () => {
      setBrand();
      const onSend = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={onSend} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const input = screen.getByPlaceholderText('Ask something...');
      fireEvent.change(input, { target: { value: 'Test message' } });
      fireEvent.click(screen.getByLabelText('Send'));
      expect(onSend).toHaveBeenCalledWith('Test message');
    });

    it('close button calls onClose', () => {
      setBrand();
      const onClose = vi.fn();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={onClose} onToggleExpand={noopExpand} />
      );
      fireEvent.click(screen.getByLabelText('Close chat'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('chat state (messages present)', () => {
    const messages: Message[] = [
      { id: '1', content: 'Hello', role: 'user', timestamp: new Date() },
      { id: '2', content: 'Hi there!', role: 'assistant', timestamp: new Date() },
    ];

    it('renders messages instead of hero', () => {
      setBrand();
      render(
        <ChatWindow messages={messages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      // Hero should not be visible
      expect(screen.queryByText("I'm TestBrand AI")).not.toBeInTheDocument();
      // Messages should be visible
      expect(screen.getByText('Hello')).toBeInTheDocument();
    });

    it('still shows NOVA logo in chat state', () => {
      setBrand();
      render(
        <ChatWindow messages={messages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByAltText('NOVA')).toBeInTheDocument();
    });

    it('shows typing indicator with dots', () => {
      setBrand();
      render(
        <ChatWindow messages={messages} isTyping={true} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const dots = document.querySelectorAll('.typing-dots .dot');
      expect(dots.length).toBe(3);
    });

    it('chat input shows "Type your message..." placeholder', () => {
      setBrand();
      render(
        <ChatWindow messages={messages} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByPlaceholderText('Type your message...')).toBeInTheDocument();
    });
  });

  describe('cycling subtitle', () => {
    it('shows cycling accent span when cyclingCategories are set', () => {
      setBrand({ cycling_categories: 'Senior living,Memory care,Dining' });
      const { container } = render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(container.querySelector('.chat-hero-cycling-text')).toBeInTheDocument();
    });

    it('shows first cycling category as initial text', () => {
      setBrand({ cycling_categories: 'Senior living,Memory care,Dining' });
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('Senior living')).toBeInTheDocument();
    });

    it('does not show cycling row when cyclingCategories is not set', () => {
      setBrand();
      const { container } = render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(container.querySelector('.chat-hero-cycling-text')).not.toBeInTheDocument();
    });

    it('shows static subtitle when no cycling categories', () => {
      setBrand();
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('Ask me about testing')).toBeInTheDocument();
    });

    it('shows static subtitle line alongside cycling row when categories are set', () => {
      setBrand({ cycling_categories: 'Senior living,Memory care' });
      render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      expect(screen.getByText('Ask me about testing')).toBeInTheDocument();
    });
  });

  describe('light mode', () => {
    it('uses light mode tokens for panel background', () => {
      setBrand({ default_mode: 'light' });
      const { container } = render(
        <ChatWindow messages={[]} isTyping={false} onSendMessage={vi.fn()} onClose={noopClose} onToggleExpand={noopExpand} />
      );
      const panel = container.querySelector('.chat-panel');
      // Light mode gradient should contain light colors
      expect(panel?.getAttribute('style')).toContain('linear-gradient');
    });
  });
});
