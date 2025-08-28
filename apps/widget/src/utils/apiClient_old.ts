import type { Message, StreamingMessage, WidgetConfig, PageContext, APIError } from '../types';

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
        message,
        user_id: this.config.userId,
        conversation_id: conversationId,
        page_context: pageContext,
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
    const response = await fetch(`${this.config.apiUrl}/api/v1/messages/`, {
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
    
    return {
      id: data.conversation_id + '-' + Date.now(),
      content: data.message,
      role: 'assistant',
      timestamp: new Date(data.timestamp),
      citations: data.citations,
      contextUsed: data.context_used,
      confidenceScore: data.confidence_score,
    };
  }

  private async streamMessage(
    requestBody: any,
    onStream: (chunk: StreamingMessage) => void
  ): Promise<Message> {
    return new Promise((resolve, reject) => {
      const eventSource = new EventSource(
        `${this.config.apiUrl}/api/v1/messages/stream?` + 
        new URLSearchParams({
          message: requestBody.message,
          user_id: requestBody.user_id,
          conversation_id: requestBody.conversation_id || '',
        })
      );

      let fullMessage = '';
      let messageData: Partial<Message> = {};

      eventSource.onmessage = (event) => {
        try {
          const chunk: StreamingMessage = JSON.parse(event.data);
          
          onStream(chunk);

          if (chunk.type === 'content') {
            fullMessage += chunk.content;
          } else if (chunk.type === 'metadata') {
            messageData = {
              citations: chunk.citations,
              contextUsed: chunk.context_used,
              confidenceScore: chunk.confidence_score,
            };
          }
        } catch (error) {
          console.error('Error parsing stream data:', error);
        }
      };

      eventSource.onerror = (error) => {
        eventSource.close();
        
        if (fullMessage) {
          // Partial success - return what we have
          resolve({
            id: messageData.conversationId + '-' + Date.now(),
            content: fullMessage,
            role: 'assistant',
            timestamp: new Date(),
            ...messageData,
          } as Message);
        } else {
          reject(this.handleError(error));
        }
      };

      eventSource.addEventListener('end', () => {
        eventSource.close();
        resolve({
          id: (requestBody.conversation_id || 'new') + '-' + Date.now(),
          content: fullMessage,
          role: 'assistant',
          timestamp: new Date(),
          ...messageData,
        } as Message);
      });

      // Timeout after 30 seconds
      setTimeout(() => {
        eventSource.close();
        if (fullMessage) {
          resolve({
            id: (requestBody.conversation_id || 'new') + '-' + Date.now(),
            content: fullMessage,
            role: 'assistant',
            timestamp: new Date(),
            ...messageData,
          } as Message);
        } else {
          reject(new Error('Request timeout'));
        }
      }, 30000);
    });
  }

  async healthCheck(): Promise<boolean> {
    try {
      const response = await fetch(`${this.config.apiUrl}/health`);
      return response.ok;
    } catch {
      return false;
    }
  }

  private handleError(error: any): APIError {
    if (error instanceof TypeError && error.message.includes('fetch')) {
      return {
        message: 'Network error. Please check your connection.',
        detail: 'Unable to connect to the server',
        status: 0,
      };
    }

    if (error.status >= 400 && error.status < 500) {
      return {
        message: 'Invalid request. Please try again.',
        detail: error.message,
        status: error.status,
      };
    }

    if (error.status >= 500) {
      return {
        message: 'Server error. Please try again later.',
        detail: error.message,
        status: error.status,
      };
    }

    return {
      message: error.message || 'An unexpected error occurred',
      detail: 'Please try again or contact support',
    };
  }

  disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}
