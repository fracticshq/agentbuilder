import type { Message, StreamingMessage, PageContext, APIError } from '../types';

export class APIClient {
  private baseUrl: string;
  private eventSource: EventSource | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 3;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async sendMessage(
    request: { content: string; context?: PageContext },
    conversationId?: string,
    onStream?: (chunk: StreamingMessage) => void
  ): Promise<Message> {
    try {
      const requestBody = {
        message: request.content,
        user_id: 'anonymous',
        conversation_id: conversationId,
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
    requestBody: any,
    onStream: (chunk: StreamingMessage) => void
  ): Promise<Message> {
    return new Promise((resolve, reject) => {
      const params = new URLSearchParams({
        message: requestBody.message,
        user_id: requestBody.user_id,
        conversation_id: requestBody.conversation_id || '',
        page_context: JSON.stringify(requestBody.page_context || {}),
      });

      const eventSourceUrl = 
        `${this.baseUrl}/api/v1/messages/stream?` +
        params.toString();

      this.eventSource = new EventSource(eventSourceUrl);
      let fullMessage = '';
      let messageData: Partial<Message> = {};

      this.eventSource.onmessage = (event) => {
        try {
          const chunk: StreamingMessage = JSON.parse(event.data);
          
          if (chunk.type === 'content') {
            fullMessage += chunk.content || '';
            onStream(chunk);
          } else if (chunk.type === 'metadata') {
            messageData = { ...messageData, ...chunk.data };
          } else if (chunk.type === 'complete') {
            this.eventSource?.close();
            this.eventSource = null;
            
            const finalMessage: Message = {
              id: messageData.id || Date.now().toString(),
              content: fullMessage,
              role: 'assistant',
              timestamp: new Date(),
              citations: messageData.citations,
            };
            
            resolve(finalMessage);
          } else if (chunk.type === 'error') {
            this.eventSource?.close();
            this.eventSource = null;
            reject(new Error(chunk.error || 'Streaming error'));
          }
        } catch (error) {
          console.error('Error parsing stream chunk:', error);
        }
      };

      this.eventSource.onerror = (error) => {
        console.error('EventSource error:', error);
        this.eventSource?.close();
        this.eventSource = null;
        
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
          this.reconnectAttempts++;
          setTimeout(() => {
            this.streamMessage(requestBody, onStream)
              .then(resolve)
              .catch(reject);
          }, 1000 * this.reconnectAttempts);
        } else {
          reject(new Error('Failed to connect to streaming endpoint'));
        }
      };
    });
  }

  private formatMessage(data: any): Message {
    return {
      id: data.id || Date.now().toString(),
      content: data.content || data.message || '',
      role: data.role || 'assistant',
      timestamp: new Date(data.timestamp || Date.now()),
      citations: data.citations || [],
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

  disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    this.reconnectAttempts = 0;
  }

  private handleError(error: unknown): APIError {
    if (error instanceof Error) {
      return {
        message: error.message,
        status: 500,
        timestamp: new Date().toISOString(),
      };
    }
    
    return {
      message: 'An unknown error occurred',
      status: 500,
      timestamp: new Date().toISOString(),
    };
  }
}
