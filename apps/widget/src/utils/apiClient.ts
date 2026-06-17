import type { Message, StreamingMessage, PageContext, APIError } from '../types';

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

const mergeStreamingMetadata = (messageData: Partial<Message>, chunk: StreamingMessage): void => {
  if (chunk.citations?.length) messageData.citations = chunk.citations;
  if (chunk.products?.length) messageData.products = chunk.products;
  if (chunk.dealers?.length) messageData.dealers = chunk.dealers;
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
    const data = await response.json();
    this.sessionToken = data.session_token;
    return {
      conversationId: data.conversation_id,
      userId: data.user_id,
      sessionToken: data.session_token,
    };
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

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async sendDirectMessage(requestBody: any): Promise<Message> {
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

    const data = await response.json();
    return this.formatMessage(data);
  }

  private async streamMessage(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    requestBody: any,
    onStream: (chunk: StreamingMessage) => void
  ): Promise<Message> {
    isDev && console.log('[APIClient] Starting stream with body:', requestBody);
    
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
        isDev && console.log('[APIClient] Stream response received:', response.status, response.statusText);
        
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
          isDev && console.log('[APIClient] Starting to read stream...');
          while (true) {
            const { done, value } = await reader.read();
            
            if (done) {
              isDev && console.log('[APIClient] Stream complete');
              break;
            }

            // Decode and append to buffer
            const chunk = decoder.decode(value, { stream: true });
            isDev && console.log('[APIClient] Received chunk:', chunk);
            isDev && console.log('[APIClient] Buffer before split:', buffer.length, 'chars');
            buffer += chunk;
            isDev && console.log('[APIClient] Buffer after append:', buffer.length, 'chars');
            
            // Process complete SSE messages (separated by \n\n)
            const lines = buffer.split('\n\n');
            isDev && console.log('[APIClient] Split into', lines.length, 'lines');
            buffer = lines.pop() || ''; // Keep incomplete message in buffer
            isDev && console.log('[APIClient] Lines to process:', lines.length);

            for (const line of lines) {
              isDev && console.log('[APIClient] Processing line:', line.substring(0, 100));
              // Skip empty lines
              if (!line.trim()) {
                isDev && console.log('[APIClient] Skipping empty line');
                continue;
              }
              
              // SSE format is "data: <json>"
              if (!line.startsWith('data: ')) {
                isDev && console.warn('[APIClient] Unexpected line format:', line);
                continue;
              }

              try {
                const data = line.substring(6).trim(); // Remove 'data: ' prefix and trim
                
                // Skip empty data lines
                if (!data) {
                  isDev && console.log('[APIClient] Skipping empty data');
                  continue;
                }
                
                isDev && console.log('[APIClient] Parsing SSE data:', data);
                const chunk: StreamingMessage = JSON.parse(data);
                isDev && console.log('[APIClient] Parsed chunk:', chunk);
                mergeStreamingMetadata(messageData, chunk);
                
                if (chunk.type === 'content') {
                  fullMessage += chunk.content || '';
                  onStream(chunk);
                } else if (
                  chunk.type === 'status' ||
                  chunk.type === 'context_start' ||
                  chunk.type === 'context_result' ||
                  chunk.type === 'skill_start' ||
                  chunk.type === 'skill_result' ||
                  chunk.type === 'tool_start' ||
                  chunk.type === 'tool_result' ||
                  chunk.type === 'tool_error' ||
                  chunk.type === 'citation'
                ) {
                  onStream(chunk);
                } else if (chunk.type === 'error') {
                  reject(new Error(chunk.content || 'Streaming error'));
                  return;
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
          };
          
          isDev && console.log('[APIClient] Resolving with final message:', finalMessage);
          resolve(finalMessage);
        } catch (error) {
          console.error('[APIClient] Stream reading error:', error);
          reject(error);
        }
      }).catch(reject);
    });
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private formatMessage(data: Record<string, any>): Message {
    return {
      id: data.id || Date.now().toString(),
      content: data.content || data.message || '',
      role: data.role || 'assistant',
      timestamp: new Date(data.timestamp || Date.now()),
      citations: data.citations || [],
      products: data.products || [],  // Phase 5: Product cards
      dealers: data.dealers || [],    // Phase 5: Dealer cards
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
