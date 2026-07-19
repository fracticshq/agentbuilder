import type {
  APIError,
  CommerceCart,
  CommerceMetadata,
  DealerData,
  Message,
  Metadata,
  PageContext,
  ProductData,
  StreamingMessage,
} from '../types';

const isDev = import.meta.env.DEV;

declare global {
  interface Window {
    __APP_CONFIG__?: {
      API_BASE_URL?: string;
    };
  }
}

export const DEFAULT_API_BASE_URL = window.__APP_CONFIG__?.API_BASE_URL || import.meta.env.VITE_API_BASE_URL || window.location.origin;

export interface WidgetSession {
  conversationId: string;
  userId: string;
  sessionToken: string;
}

interface WidgetSessionResponse {
  conversation_id: string;
  user_id: string;
  session_token: string;
}

interface WidgetMetadata extends Metadata {
  products?: ProductData[];
  dealers?: DealerData[];
  commerce?: CommerceMetadata;
  cart?: CommerceCart;
}

interface APIMessageData {
  id?: string;
  message_id?: string;
  content?: string;
  message?: string;
  role?: Message['role'];
  timestamp?: string | number;
  citations?: Message['citations'];
  products?: ProductData[];
  dealers?: DealerData[];
  metadata?: WidgetMetadata;
  commerce?: CommerceMetadata;
}

interface APIHistoryResponse {
  messages?: APIMessageData[];
}

interface MessageRequestBody {
  message: string;
  user_id: string;
  conversation_id?: string;
  agent_id?: string;
  page_context?: PageContext;
  stream: boolean;
}

const mergeStreamingMetadata = (messageData: Partial<Message>, chunk: StreamingMessage): void => {
  if (chunk.citations?.length) messageData.citations = chunk.citations;
  if (chunk.products?.length) messageData.products = chunk.products;
  if (chunk.dealers?.length) messageData.dealers = chunk.dealers;
  if (chunk.metadata) messageData.metadata = { ...(messageData.metadata || {}), ...chunk.metadata };
  if (chunk.commerce) messageData.commerce = { ...(messageData.commerce || {}), ...chunk.commerce };
  if (chunk.metadata?.cart && !messageData.commerce) messageData.commerce = { cart: chunk.metadata.cart };
};

export class APIClient {
  private baseUrl: string;
  private sessionToken?: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  /** Hold the signed session token used to authorize message calls. */
  setSessionToken(token: string | undefined): void {
    this.sessionToken = token;
  }

  getSessionToken(): string | undefined {
    return this.sessionToken;
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  setBaseUrl(baseUrl: string): void {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  /**
   * Start or resume a server-issued widget session. The server mints (or
   * resumes, when a valid prior token is supplied) a conversation_id + user_id
   * bound to a signed token, which must accompany every subsequent message.
   */
  async startSession(agentId: string, priorToken?: string): Promise<WidgetSession> {
    const response = await fetch(`${this.baseUrl}/api/v1/messages/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId, session_token: priorToken }),
    });
    if (!response.ok) {
      throw new Error(`Failed to start session: HTTP ${response.status}`);
    }
    const data = await response.json() as WidgetSessionResponse;
    this.sessionToken = data.session_token;
    return {
      conversationId: data.conversation_id,
      userId: data.user_id,
      sessionToken: data.session_token,
    };
  }

  async getHistory(limit = 100): Promise<Message[]> {
    const response = await fetch(`${this.baseUrl}/api/v1/messages/history?limit=${limit}`, {
      headers: {
        ...(this.sessionToken ? { 'X-Widget-Session': this.sessionToken } : {}),
      },
    });
    if (!response.ok) {
      throw new Error(`Failed to load conversation history: HTTP ${response.status}`);
    }
    const data = await response.json() as APIHistoryResponse;
    return (data.messages || []).map((message) => this.formatMessage({
      id: message.message_id,
      content: message.content,
      role: message.role,
      timestamp: message.timestamp,
      metadata: message.metadata,
      products: message.metadata?.products || [],
      dealers: message.metadata?.dealers || [],
      commerce: message.metadata?.commerce || (message.metadata?.cart ? { cart: message.metadata.cart } : undefined),
    }));
  }

  async sendMessage(
    request: { content: string; context?: PageContext; userId?: string },  // Add userId to request
    conversationId?: string,
    agentId?: string,  // Add agentId parameter
    onStream?: (chunk: StreamingMessage) => void
  ): Promise<Message> {
    try {
      const requestBody = {
        message: request.content,
        user_id: request.userId || 'anonymous',  // Use provided userId or default
        conversation_id: conversationId,
        agent_id: agentId,  // Include agent_id in request
        page_context: request.context,
        stream: !!onStream,
      };

      if (onStream) {
        return this.streamMessage(requestBody, onStream);
      } else {
        return this.sendDirectMessage(requestBody);
      }
    } catch (error) {
      console.error('Error sending message:', error);
      throw this.handleError(error);
    }
  }

  private async sendDirectMessage(requestBody: MessageRequestBody): Promise<Message> {
    const response = await fetch(`${this.baseUrl}/api/v1/messages/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(this.sessionToken ? { 'X-Widget-Session': this.sessionToken } : {}),
      },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json() as APIMessageData;
    return this.formatMessage(data);
  }

  private async streamMessage(
    requestBody: MessageRequestBody,
    onStream: (chunk: StreamingMessage) => void
  ): Promise<Message> {
    if (isDev) {
      console.log('[APIClient] Starting stream with body:', requestBody);
    }
    
    return new Promise((resolve, reject) => {
      // Use fetch API for POST streaming (EventSource doesn't support POST)
      fetch(`${this.baseUrl}/api/v1/messages/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          ...(this.sessionToken ? { 'X-Widget-Session': this.sessionToken } : {}),
        },
        body: JSON.stringify(requestBody),
      }).then(async (response) => {
        if (isDev) {
          console.log('[APIClient] Stream response received:', response.status, response.statusText);
        }
        
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        
        if (!reader) {
          throw new Error('No response body');
        }

        let fullMessage = '';
        const messageData: Partial<Message> = {};
        let buffer = '';

        try {
          if (isDev) {
            console.log('[APIClient] Starting to read stream...');
          }
          while (true) {
            const { done, value } = await reader.read();
            
            if (done) {
              if (isDev) {
                console.log('[APIClient] Stream complete');
              }
              break;
            }

            // Decode and append to buffer
            const chunk = decoder.decode(value, { stream: true });
            if (isDev) {
              console.log('[APIClient] Received chunk:', chunk);
              console.log('[APIClient] Buffer before split:', buffer.length, 'chars');
            }
            buffer += chunk;
            if (isDev) {
              console.log('[APIClient] Buffer after append:', buffer.length, 'chars');
            }
            
            // Process complete SSE messages (separated by \n\n)
            const lines = buffer.split('\n\n');
            if (isDev) {
              console.log('[APIClient] Split into', lines.length, 'lines');
            }
            buffer = lines.pop() || ''; // Keep incomplete message in buffer
            if (isDev) {
              console.log('[APIClient] Lines to process:', lines.length);
            }

            for (const line of lines) {
              if (isDev) {
                console.log('[APIClient] Processing line:', line.substring(0, 100));
              }
              // Skip empty lines
              if (!line.trim()) {
                if (isDev) {
                  console.log('[APIClient] Skipping empty line');
                }
                continue;
              }
              
              // SSE format is "data: <json>"
              if (!line.startsWith('data: ')) {
                if (isDev) {
                  console.warn('[APIClient] Unexpected line format:', line);
                }
                continue;
              }

              try {
                const data = line.substring(6).trim(); // Remove 'data: ' prefix and trim
                
                // Skip empty data lines
                if (!data) {
                  if (isDev) {
                    console.log('[APIClient] Skipping empty data');
                  }
                  continue;
                }
                
                if (isDev) {
                  console.log('[APIClient] Parsing SSE data:', data);
                }
                const chunk: StreamingMessage = JSON.parse(data);
                if (isDev) {
                  console.log('[APIClient] Parsed chunk:', chunk);
                }
                mergeStreamingMetadata(messageData, chunk);
                
                if (chunk.type === 'content') {
                  fullMessage += chunk.content || '';
                  onStream(chunk);
                } else if (chunk.type === 'final_answer' && typeof chunk.content === 'string' && chunk.content.length >= fullMessage.length) {
                  // Authoritative full answer — recover from any dropped chunk.
                  fullMessage = chunk.content;
                  onStream(chunk);
                } else if (chunk.type === 'error') {
                  reject(new Error(chunk.content || 'Streaming error'));
                  return;
                } else {
                  // Everything else is background activity for any agent
                  // (status, *_start, *_result, connector_*, geocode_*,
                  // rag_context, place_disambiguation, metadata, …). The SSE
                  // stream end resolves the message; just forward to the UI.
                  onStream(chunk);
                }
              } catch (parseError) {
                console.error('[APIClient] Error parsing stream chunk:', parseError, 'Data:', line);
              }
            }
          }

          // If we exit the loop without a 'complete' message, resolve with what we have
          const finalMessage: Message = {
            id: messageData.id || Date.now().toString(),
            content: fullMessage,
            role: 'assistant',
            timestamp: new Date(),
            citations: messageData.citations,
            products: messageData.products || [],  // Phase 5: Product cards
            dealers: messageData.dealers || [],    // Phase 5: Dealer cards
            metadata: messageData.metadata,
            commerce: messageData.commerce,
          };
          
          if (isDev) {
            console.log('[APIClient] Resolving with final message:', finalMessage);
          }
          resolve(finalMessage);
        } catch (error) {
          console.error('[APIClient] Stream reading error:', error);
          reject(error);
        }
      }).catch(reject);
    });
  }

  private formatMessage(data: APIMessageData): Message {
    return {
      id: data.id || Date.now().toString(),
      content: data.content || data.message || '',
      role: data.role || 'assistant',
      timestamp: new Date(data.timestamp || Date.now()),
      citations: data.citations || [],
      products: data.products || [],  // Phase 5: Product cards
      dealers: data.dealers || [],    // Phase 5: Dealer cards
      metadata: data.metadata,
      commerce: data.commerce || (data.metadata?.cart ? { cart: data.metadata.cart } : undefined),
    };
  }

  async healthCheck(): Promise<{ status: string; timestamp: string }> {
    try {
      const response = await fetch(`${this.baseUrl}/health`);
      
      if (!response.ok) {
        throw new Error(`Health check failed: ${response.status}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error('Health check error:', error);
      throw this.handleError(error);
    }
  }

  private handleError(error: unknown): APIError {
    if (error instanceof Error) {
      return {
        message: error.message,
        status: 500,
      };
    }
    
    return {
      message: 'An unknown error occurred',
      status: 500,
    };
  }
}
