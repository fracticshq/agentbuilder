export interface WidgetConfig {
  apiUrl: string;
  userId: string;
  agentId?: string;  // Agent ID for custom agent configuration
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
  products?: ProductData[];  // Phase 5: Product cards
  dealers?: DealerData[];    // Phase 5: Dealer cards
}

export interface Citation {
  doc_id: string;
  title?: string;
  url?: string;
  confidence: number;
  snippet?: string;
}

// Phase 5: Product card data
export interface ProductData {
  sku: string;
  name: string;
  price?: number;
  currency?: string;
  category?: string;
  in_stock?: boolean;
  features?: string[];
  image_url?: string;
  product_url?: string;
  description?: string;
}

// Phase 5: Dealer card data
export interface DealerData {
  dealer_id: string;
  name: string;
  city: string;
  state?: string;
  phone?: string;
  email?: string;
  address?: string;
  map_url?: string;
  hours?: string;
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
  products?: ProductData[];  // Phase 5: Product cards in metadata
  dealers?: DealerData[];    // Phase 5: Dealer cards in metadata
  timestamp?: string;
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
