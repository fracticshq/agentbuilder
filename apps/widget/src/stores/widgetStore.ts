import { create } from 'zustand';
import type { WidgetState, Message, WidgetConfig } from '../types';

interface WidgetStore extends WidgetState {
  config: WidgetConfig | null;
  
  // Actions
  setConfig: (config: WidgetConfig) => void;
  toggleWidget: () => void;
  setOpen: (isOpen: boolean) => void;
  setIsOpen: (isOpen: boolean) => void;
  setConnected: (isConnected: boolean) => void;
  setTyping: (isTyping: boolean) => void;
  setIsTyping: (isTyping: boolean) => void;
  addMessage: (message: Message) => void;
  updateLastMessage: (content: string) => void;
  setConversationId: (id: string) => void;
  setError: (error: string | null) => void;
  clearMessages: () => void;
  reset: () => void;
}

const initialState: WidgetState = {
  isOpen: false,
  isConnected: false,
  isTyping: false,
  messages: [],
  conversationId: undefined,
  error: undefined,
};

export const useWidgetStore = create<WidgetStore>((set, get) => ({
  ...initialState,
  config: null,

  setConfig: (config: WidgetConfig) => {
    set({ config });
    
    // Auto-open if configured
    if (config.autoOpen) {
      set({ isOpen: true });
    }
    
    // Add greeting message if configured
    if (config.greeting) {
      const greetingMessage: Message = {
        id: 'greeting',
        content: config.greeting,
        role: 'assistant',
        timestamp: new Date(),
      };
      set({ messages: [greetingMessage] });
    }
  },

  toggleWidget: () => set((state) => ({ isOpen: !state.isOpen })),
  
  setOpen: (isOpen: boolean) => set({ isOpen }),
  
  setIsOpen: (isOpen: boolean) => set({ isOpen }),
  
  setConnected: (isConnected: boolean) => set({ isConnected }),
  
  setTyping: (isTyping: boolean) => set({ isTyping }),
  
  setIsTyping: (isTyping: boolean) => set({ isTyping }),
  
  addMessage: (message: Message) => set((state) => ({
    messages: [...state.messages, message]
  })),
  
  updateLastMessage: (content: string) => set((state) => {
    const messages = [...state.messages];
    const lastMessage = messages[messages.length - 1];
    
    if (lastMessage && lastMessage.role === 'assistant') {
      lastMessage.content += content;
    }
    
    return { messages };
  }),
  
  setConversationId: (conversationId: string) => set({ conversationId }),
  
  setError: (error: string | null) => set({ error: error || undefined }),
  
  clearMessages: () => set({ messages: [], conversationId: undefined }),
  
  reset: () => set({ ...initialState, config: get().config }),
}));
