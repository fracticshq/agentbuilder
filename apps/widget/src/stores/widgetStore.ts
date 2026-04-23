import { create } from 'zustand';
import type { WidgetState, Message, WidgetConfig, BrandTheme } from '../types';

interface WidgetStore extends WidgetState {
  config: WidgetConfig | null;
  isExpanded: boolean;
  brandTheme: BrandTheme | null;
  isHumanInControl: boolean;

  // Actions
  setConfig: (config: WidgetConfig) => void;
  setBrandTheme: (theme: BrandTheme) => void;
  setHumanInControl: (value: boolean) => void;
  toggleWidget: () => void;
  setOpen: (isOpen: boolean) => void;
  setIsOpen: (isOpen: boolean) => void;
  setConnected: (isConnected: boolean) => void;
  setTyping: (isTyping: boolean) => void;
  setIsTyping: (isTyping: boolean) => void;
  addMessage: (message: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  updateLastMessage: (content: string) => void;
  setConversationId: (id: string) => void;
  setError: (error: string | null) => void;
  setExpanded: (isExpanded: boolean) => void;
  toggleExpanded: () => void;
  clearMessages: () => void;
  reset: () => void;
  setMessageFeedback: (id: string, feedback: 'up' | 'down' | null) => void;
  removeMessage: (id: string) => void;
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
  isExpanded: false,
  brandTheme: null,
  isHumanInControl: false,

  setBrandTheme: (theme: BrandTheme) => set({ brandTheme: theme }),
  setHumanInControl: (value: boolean) => set({ isHumanInControl: value }),

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
  
  updateMessage: (id: string, updates: Partial<Message>) => {
    console.log('[Store] updateMessage called:', { id, updates, currentMessages: get().messages.length });
    set((state) => {
      const updatedMessages = state.messages.map(msg => 
        msg.id === id ? { ...msg, ...updates } : msg
      );
      console.log('[Store] Messages updated:', updatedMessages.find(m => m.id === id));
      return { messages: updatedMessages };
    });
  },
  
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
  
  setExpanded: (isExpanded: boolean) => set({ isExpanded }),
  
  toggleExpanded: () => set((state) => ({ isExpanded: !state.isExpanded })),
  
  clearMessages: () => set({ messages: [], conversationId: undefined }),

  reset: () => set({ ...initialState, config: get().config }),

  setMessageFeedback: (id, feedback) => set(state => ({
    messages: state.messages.map(m => m.id === id ? { ...m, feedback: feedback ?? undefined } : m)
  })),

  removeMessage: (id) => set(state => ({
    messages: state.messages.filter(m => m.id !== id)
  })),
}));
