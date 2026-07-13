export type BrandMode = 'dark' | 'light';

/** Resolved theme tokens used throughout the widget */
export interface BrandThemeTokens {
  mode: BrandMode;
  panelBg: string;
  sceneBorder: string;
  sceneShad: string;
  bubbleBg: string;
  bubbleBorder: string;
  bubbleShad: string;
  bubbleRing: string;
  orbBg: string;
  titleColor: string;
  subtitleColor: string;
  accentColor: string;       // the primary brand accent (button fill, chip border, etc.)
  chipBg: string;
  chipBorder: string;
  chipColor: string;
  inputBg: string;
  inputBorder: string;
  inputColor: string;
  dividerColor: string;
  voiceBg: string;
  voiceBorder: string;
  voiceIconColor: string;
  sendBg: string;
  sendShad: string;
  // User message bubble (uses accent)
  userMsgBg: string;
  userMsgColor: string;
  // Assistant message bubble
  assistantMsgBg: string;
  assistantMsgColor: string;
}

/** Brand identity pulled from admin Brand.colors */
export interface BrandTheme {
  brandName: string;
  primaryColor: string;
  mode: BrandMode;
  hideNovaLogo: boolean;
  chatLogoDarkUrl?: string;
  chatLogoLightUrl?: string;
  heroTitle?: string;
  heroSubtitle?: string;
  suggestionChips: string[];
  cyclingCategories?: string[];
  darkBgGradient?: string;
  lightBgGradient?: string;
  tokens: BrandThemeTokens;
}

export interface WidgetConfig {
  apiUrl: string;
  userId: string;
  agentId?: string;
  enableHumanTakeover?: boolean;
  showSources?: boolean;
  showProductCards?: boolean;
  position?: 'bottom-right' | 'bottom-left' | 'sidebar';
  pageContext?: {
    extractContent?: boolean;
    includeMetadata?: boolean;
  };
  autoOpen?: boolean;
  greeting?: string;
}

export interface Message {
  id: string;
  content: string;
  role: 'user' | 'assistant' | 'system';
  timestamp: Date;
  citations?: Citation[];
  contextUsed?: number;
  confidenceScore?: number;
  products?: ProductData[];  // Phase 5: Product cards
  dealers?: DealerData[];    // Phase 5: Dealer cards
  metadata?: Record<string, any>;
  feedback?: 'up' | 'down';
  activitySteps?: ActivityStep[];  // Live "what happened in the background" trace
}

/** A single line in the live background-activity timeline. */
export interface ActivityStep {
  id: string;
  label: string;
  detail?: string;
  status: 'running' | 'done' | 'error';
}

export interface ActivityControl {
  type: 'choice' | 'multi_choice' | 'text' | 'date' | 'time' | 'place' | 'number' | 'form' | 'confirmation' | string;
  id: string;
  label: string;
  value?: string;
  options?: Array<{ label: string; value?: string }>;
}

/** A candidate birthplace offered when a place name is ambiguous. */
export interface PlaceCandidate {
  placeId?: string;
  label: string;
  name?: string;
  adminRegion?: string;
  country?: string;
}

/** Resolved activity-timeline state derived from the streaming events. */
export interface ActivityState {
  steps: ActivityStep[];
  disambiguation?: { question: string; candidates: PlaceCandidate[] };
  prompt?: { question: string; controls: ActivityControl[] };
}

export interface Citation {
  doc_id: string;
  title?: string;
  url?: string;
  confidence: number;
  snippet?: string;
}

// Phase 5: Product card data
export interface ProductVariantData {
  id?: string;
  variant_id?: string;
  sku?: string;
  variant_sku?: string;
  name?: string;
  title?: string;
  variant_title?: string;
  variant_options?: Record<string, string>;
  price?: number;
  currency?: string;
  currency_source?: string;
  image_url?: string;
  image?: string;
  product_url?: string;
  variant_url?: string;
  in_stock?: boolean;
  is_default?: boolean;
}

export interface ProductData {
  id?: string;
  sku?: string;
  product_group_id?: string;
  handle?: string;
  name: string;
  price?: number;
  currency?: string;
  currency_source?: string;
  category?: string;
  in_stock?: boolean;
  features?: string[];
  image_url?: string;
  image?: string;
  product_url?: string;
  description?: string;
  has_variants?: boolean;
  variant_count?: number;
  price_min?: number;
  price_max?: number;
  default_variant_id?: string;
  variant_id?: string;
  variant_sku?: string;
  variant_title?: string;
  variant_options?: Record<string, string>;
  variant_url?: string;
  variants?: ProductVariantData[];
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
  path?: string;
  sku?: string;
  category?: string;
  content?: string;
  metadata?: Record<string, any>;
}

export type StreamingMessageType =
  | 'activity'
  | 'status'
  | 'context_start'
  | 'context_result'
  | 'skill_start'
  | 'skill_result'
  | 'tool_start'
  | 'tool_result'
  | 'tool_error'
  | 'connector_start'
  | 'connector_result'
  | 'connector_error'
  | 'geocode_start'
  | 'geocode_result'
  | 'place_disambiguation'
  | 'api_context'
  | 'rag_context'
  | 'missing_input'
  | 'citation'
  | 'content'
  | 'final_answer'
  | 'metadata'
  | 'done'
  | 'error';

export interface StreamingMessage {
  type: StreamingMessageType;
  content: string;
  conversation_id: string;
  citations?: Citation[];
  context_used?: number;
  confidence_score?: number;
  products?: ProductData[];  // Phase 5: Product cards in metadata
  dealers?: DealerData[];    // Phase 5: Dealer cards in metadata
  metadata?: Record<string, any>;
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

// Lal Kitab kundali chart (visual artifact rendered by KundaliChart)
export interface KundaliHouse {
  house: number;
  sign_number?: number | null;
  rashi?: string | null;
  rashi_hindi?: string | null;
  planets: string[];
}

export interface KundaliChartData {
  style?: string;
  ascendant?: { sign_number: number; name: string; hindi?: string } | null;
  houses: KundaliHouse[];
  birth?: { name?: string | null; date?: string | null; time?: string | null; place?: string | null } | null;
}
