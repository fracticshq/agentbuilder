export interface WidgetConfig {
  apiUrl: string;
  userId: string;
  theme?: 'light' | 'dark';
  position?: 'bottom-right' | 'bottom-left' | 'sidebar';
  pageContext?: {
    extractContent?: boolean;
    includeMetadata?: boolean;
  };
  autoOpen?: boolean;
  greeting?: string;
  branding?: {
    primaryColor?: string;
    logo?: string;
    title?: string;
  };
}

export interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant';
  timestamp: Date;
  citations?: Citation[];
  contextUsed?: number;
  confidenceScore?: number;
}

export interface Citation {
  doc_id: string;
  title?: string;
  url?: string;
  confidence: number;
  snippet?: string;
}

export interface PageContext {
  url: string;
  title?: string;
  content?: string;
  metadata?: Record<string, any>;
}

export interface StreamingMessage {
  type: 'status' | 'content' | 'metadata' | 'error';
  content: string;
  conversation_id: string;
  citations?: Citation[];
  context_used?: number;
  confidence_score?: number;
}

export interface WidgetState {
  isOpen: boolean;
  isConnected: boolean;
  isTyping: boolean;
  messages: Message[];
  conversationId?: string;
  error?: string;
}

export interface APIError {
  message: string;
  detail?: string;
  status?: number;
}
