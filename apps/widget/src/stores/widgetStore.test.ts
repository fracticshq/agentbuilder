import { describe, it, expect, beforeEach } from 'vitest';
import { useWidgetStore } from './widgetStore';
import { buildBrandTheme } from '../utils/brandTheme';
import type { Message } from '../types';

// Helper to reset store between tests
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

describe('widgetStore', () => {
  beforeEach(() => {
    resetStore();
  });

  describe('brandTheme', () => {
    it('starts with null brandTheme', () => {
      expect(useWidgetStore.getState().brandTheme).toBeNull();
    });

    it('setBrandTheme stores the theme', () => {
      const theme = buildBrandTheme('Antara', {
        primary_color: '#00c864',
        default_mode: 'dark',
        hero_title: "I'm Antara AI",
        suggestion_chips: 'Communities,Care,Visit',
      });

      useWidgetStore.getState().setBrandTheme(theme);
      const state = useWidgetStore.getState();

      expect(state.brandTheme).not.toBeNull();
      expect(state.brandTheme!.brandName).toBe('Antara');
      expect(state.brandTheme!.mode).toBe('dark');
      expect(state.brandTheme!.suggestionChips).toEqual(['Communities', 'Care', 'Visit']);
      expect(state.brandTheme!.tokens.accentColor).toBe('#00c864');
    });

    it('setBrandTheme can be called multiple times (brand switch)', () => {
      const antara = buildBrandTheme('Antara', { primary_color: '#00c864', default_mode: 'dark' });
      const usha = buildBrandTheme('Usha', { primary_color: '#cc0000', default_mode: 'light' });

      useWidgetStore.getState().setBrandTheme(antara);
      expect(useWidgetStore.getState().brandTheme!.brandName).toBe('Antara');

      useWidgetStore.getState().setBrandTheme(usha);
      expect(useWidgetStore.getState().brandTheme!.brandName).toBe('Usha');
      expect(useWidgetStore.getState().brandTheme!.mode).toBe('light');
    });
  });

  describe('messages', () => {
    it('addMessage appends to list', () => {
      const msg: Message = {
        id: '1',
        content: 'Hello',
        role: 'user',
        timestamp: new Date(),
      };

      useWidgetStore.getState().addMessage(msg);
      expect(useWidgetStore.getState().messages).toHaveLength(1);
      expect(useWidgetStore.getState().messages[0].content).toBe('Hello');
    });

    it('updateMessage patches a specific message', () => {
      const msg: Message = {
        id: 'a1',
        content: '',
        role: 'assistant',
        timestamp: new Date(),
      };

      useWidgetStore.getState().addMessage(msg);
      useWidgetStore.getState().updateMessage('a1', { content: 'streaming...' });

      expect(useWidgetStore.getState().messages[0].content).toBe('streaming...');
    });

    it('clearMessages resets messages and conversationId', () => {
      useWidgetStore.getState().addMessage({
        id: '1', content: 'hi', role: 'user', timestamp: new Date(),
      });
      useWidgetStore.getState().setConversationId('conv_123');

      useWidgetStore.getState().clearMessages();

      expect(useWidgetStore.getState().messages).toHaveLength(0);
      expect(useWidgetStore.getState().conversationId).toBeUndefined();
    });
  });

  describe('open/close/expand', () => {
    it('toggleWidget flips isOpen', () => {
      expect(useWidgetStore.getState().isOpen).toBe(false);
      useWidgetStore.getState().toggleWidget();
      expect(useWidgetStore.getState().isOpen).toBe(true);
      useWidgetStore.getState().toggleWidget();
      expect(useWidgetStore.getState().isOpen).toBe(false);
    });

    it('setExpanded sets isExpanded', () => {
      useWidgetStore.getState().setExpanded(true);
      expect(useWidgetStore.getState().isExpanded).toBe(true);
    });
  });

  describe('reset', () => {
    it('resets state but preserves config', () => {
      useWidgetStore.getState().setConfig({
        apiUrl: 'http://localhost:8000',
        userId: 'u1',
      });
      useWidgetStore.getState().addMessage({
        id: '1', content: 'hi', role: 'user', timestamp: new Date(),
      });
      useWidgetStore.getState().setIsOpen(true);

      useWidgetStore.getState().reset();

      expect(useWidgetStore.getState().messages).toHaveLength(0);
      expect(useWidgetStore.getState().isOpen).toBe(false);
      expect(useWidgetStore.getState().config).not.toBeNull();
    });
  });
});
