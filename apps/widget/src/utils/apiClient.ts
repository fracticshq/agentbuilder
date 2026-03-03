import type { Message, StreamingMessage, PageContext, APIError } from '../types';

export class APIClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
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
    console.log('[APIClient] Starting stream with body:', requestBody);

    return new Promise((resolve, reject) => {
      // Use fetch API for POST streaming (EventSource doesn't support POST)
      fetch(`${this.baseUrl}/api/v1/messages/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify(requestBody),
      }).then(async (response) => {
        console.log('[APIClient] Stream response received:', response.status, response.statusText);

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
          console.log('[APIClient] Starting to read stream...');
          while (true) {
            const { done, value } = await reader.read();

            if (done) {
              console.log('[APIClient] Stream complete');
              break;
            }

            // Decode and append to buffer
            const chunk = decoder.decode(value, { stream: true });
            console.log('[APIClient] Received chunk:', chunk);
            console.log('[APIClient] Buffer before split:', buffer.length, 'chars');
            buffer += chunk;
            console.log('[APIClient] Buffer after append:', buffer.length, 'chars');

            // Process complete SSE messages (separated by \n\n)
            const lines = buffer.split('\n\n');
            console.log('[APIClient] Split into', lines.length, 'lines');
            buffer = lines.pop() || ''; // Keep incomplete message in buffer
            console.log('[APIClient] Lines to process:', lines.length);

            for (const line of lines) {
              console.log('[APIClient] Processing line:', line.substring(0, 100));
              // Skip empty lines
              if (!line.trim()) {
                console.log('[APIClient] Skipping empty line');
                continue;
              }

              // SSE format is "data: <json>"
              if (!line.startsWith('data: ')) {
                console.warn('[APIClient] Unexpected line format:', line);
                continue;
              }

              try {
                const data = line.substring(6).trim(); // Remove 'data: ' prefix and trim

                // Skip empty data lines
                if (!data) {
                  console.log('[APIClient] Skipping empty data');
                  continue;
                }

                console.log('[APIClient] Parsing SSE data:', data);
                const chunk: StreamingMessage = JSON.parse(data);
                console.log('[APIClient] Parsed chunk:', chunk);

                if (chunk.type === 'content') {
                  fullMessage += chunk.content || '';
                  onStream(chunk);
                } else if (chunk.type === 'status') {
                  onStream(chunk);
                } else if (chunk.type === 'metadata') {
                  // Phase 5: Store metadata (citations, products, dealers)
                  if (chunk.citations) {
                    messageData.citations = chunk.citations;
                  }
                  if (chunk.products) {
                    messageData.products = chunk.products;
                  }
                  if (chunk.dealers) {
                    messageData.dealers = chunk.dealers;
                  }
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

          console.log('[APIClient] Resolving with final message:', finalMessage);
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

  connectWebSocket(
    conversationId: string,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onMessage: (data: any) => void
  ): WebSocket {
    const wsUrl = this.baseUrl.replace(/^http/, 'ws');
    const ws = new WebSocket(`${wsUrl}/api/v1/messages/ws/chat/${conversationId}`);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error('[APIClient] Error parsing WebSocket message:', e);
      }
    };

    ws.onopen = () => {
      console.log('[APIClient] WebSocket connected for conversation:', conversationId);
    };

    ws.onclose = () => {
      console.log('[APIClient] WebSocket disconnected');
    };

    return ws;
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
