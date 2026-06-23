import type { Message, StreamingMessage, PageContext } from '../types';

const DEFAULT_HEARTBEAT_INTERVAL = 30_000;
// Generous so a server busy generating/streaming a long answer is not treated
// as a dead connection (which would close the socket and truncate the reply).
const DEFAULT_PONG_TIMEOUT = 20_000;
const DEFAULT_RECONNECT_BASE_DELAY = 1_000;
const DEFAULT_MAX_RECONNECT_ATTEMPTS = 5;

export interface WebSocketClientOptions {
  heartbeatInterval?: number;
  pongTimeout?: number;
  reconnectBaseDelay?: number;
  maxReconnectAttempts?: number;
}

export class WebSocketClient {
  private readonly baseUrl: string;
  private readonly heartbeatInterval: number;
  private readonly pongTimeout: number;
  private readonly reconnectBaseDelay: number;
  private readonly maxReconnectAttempts: number;

  private ws: WebSocket | null = null;
  private connectPromise: Promise<void> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private intentionalClose = false;

  // Active pending stream state (one in-flight message at a time)
  private pendingResolve: ((msg: Message) => void) | null = null;
  private pendingReject: ((err: Error) => void) | null = null;
  private pendingCallback: ((chunk: StreamingMessage) => void) | null = null;
  private accumulatedContent = '';
  private pendingMeta: Partial<Pick<Message, 'citations' | 'products' | 'dealers' | 'metadata'>> = {};
  private sessionToken?: string;

  /** Hold the signed session token included with every outbound message frame. */
  setSessionToken(token: string | undefined): void {
    this.sessionToken = token;
  }

  constructor(baseUrl: string, options: WebSocketClientOptions = {}) {
    this.baseUrl = baseUrl;
    this.heartbeatInterval = options.heartbeatInterval ?? DEFAULT_HEARTBEAT_INTERVAL;
    this.pongTimeout = options.pongTimeout ?? DEFAULT_PONG_TIMEOUT;
    this.reconnectBaseDelay = options.reconnectBaseDelay ?? DEFAULT_RECONNECT_BASE_DELAY;
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECT_ATTEMPTS;
  }

  private get wsUrl(): string {
    return this.baseUrl.replace(/^http/, 'ws') + '/api/v1/messages/ws';
  }

  private mergeChunkMetadata(chunk: StreamingMessage): void {
    if (chunk.citations?.length) this.pendingMeta.citations = chunk.citations;
    if (chunk.products?.length) this.pendingMeta.products = chunk.products;
    if (chunk.dealers?.length) this.pendingMeta.dealers = chunk.dealers;
    if (chunk.metadata) this.pendingMeta.metadata = { ...(this.pendingMeta.metadata || {}), ...chunk.metadata };
  }

  // Central message router — set once per connection in connect()
  private handleMessage = (event: MessageEvent): void => {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(event.data as string);
    } catch {
      return;
    }

    // Heartbeat pong — clear the dead-connection timeout
    if (msg.type === 'pong') {
      if (this.pongTimeoutId !== null) {
        clearTimeout(this.pongTimeoutId);
        this.pongTimeoutId = null;
      }
      return;
    }

    if (!this.pendingResolve) return;

    const chunk = msg as unknown as StreamingMessage;
    this.mergeChunkMetadata(chunk);

    if (chunk.type === 'content') {
      this.accumulatedContent += chunk.content || '';
      this.pendingCallback?.(chunk);
    } else if (chunk.type === 'metadata' || chunk.type === 'done') {
      // Both terminate the turn: the normal path sends `metadata` (carrying
      // citations/products) then `done`; some paths (e.g. a clarifying question)
      // send only `done`. Whichever lands first resolves the pending message.
      const resolve = this.pendingResolve;
      const content = this.accumulatedContent;
      const meta = { ...this.pendingMeta };
      this.clearPending();
      resolve({
        id: Date.now().toString(),
        content,
        role: 'assistant',
        timestamp: new Date(),
        citations: meta.citations,
        products: meta.products ?? [],
        dealers: meta.dealers ?? [],
        metadata: meta.metadata,
      });
    } else if (chunk.type === 'final_answer') {
      // Authoritative full answer. Replace the accumulated text so the resolved
      // message is complete even if some `content` chunks were dropped.
      if (typeof chunk.content === 'string' && chunk.content.length >= this.accumulatedContent.length) {
        this.accumulatedContent = chunk.content;
      }
      this.pendingCallback?.(chunk);
    } else if (chunk.type === 'error') {
      const reject = this.pendingReject;
      this.clearPending();
      reject?.(new Error((chunk.content as string) || 'WebSocket stream error'));
    } else {
      // Any other event is background activity (status, *_start, *_result,
      // connector_*, geocode_*, rag_context, api_context, place_disambiguation,
      // missing_input, citation, …). Forward it so the UI can show real progress.
      this.pendingCallback?.(chunk);
    }
  };

  private clearPending(): void {
    this.pendingResolve = null;
    this.pendingReject = null;
    this.pendingCallback = null;
    this.accumulatedContent = '';
    this.pendingMeta = {};
  }

  private hasPendingResponseData(): boolean {
    return (
      this.accumulatedContent.trim().length > 0 ||
      (this.pendingMeta.citations?.length ?? 0) > 0 ||
      (this.pendingMeta.products?.length ?? 0) > 0 ||
      (this.pendingMeta.dealers?.length ?? 0) > 0
    );
  }

  private buildPendingMessage(): Message {
    return {
      id: Date.now().toString(),
      content: this.accumulatedContent,
      role: 'assistant',
      timestamp: new Date(),
      citations: this.pendingMeta.citations,
      products: this.pendingMeta.products ?? [],
      dealers: this.pendingMeta.dealers ?? [],
      metadata: this.pendingMeta.metadata,
    };
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
        this.pongTimeoutId = setTimeout(() => {
          this.pongTimeoutId = null;
          this.ws?.close();
        }, this.pongTimeout);
      }
    }, this.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.pongTimeoutId !== null) {
      clearTimeout(this.pongTimeoutId);
      this.pongTimeoutId = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;
    const delay = this.reconnectBaseDelay * Math.pow(2, this.reconnectAttempts);
    this.reconnectAttempts++;
    this.reconnectTimeoutId = setTimeout(() => {
      this.reconnectTimeoutId = null;
      this.connect().catch(() => {});
    }, delay);
  }

  private connect(): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN) return Promise.resolve();
    if (this.connectPromise) return this.connectPromise;

    this.connectPromise = new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(this.wsUrl);
      let opened = false;

      ws.onopen = () => {
        opened = true;
        this.ws = ws;
        this.connectPromise = null;
        this.reconnectAttempts = 0;
        // Cancel any pending reconnect timer now that we're connected
        if (this.reconnectTimeoutId !== null) {
          clearTimeout(this.reconnectTimeoutId);
          this.reconnectTimeoutId = null;
        }
        this.startHeartbeat();
        resolve();
      };

      ws.onmessage = this.handleMessage;

      ws.onerror = () => {
        if (!opened) {
          this.connectPromise = null;
          reject(new Error('WebSocket connection failed'));
        } else if (this.pendingReject) {
          const r = this.pendingReject;
          this.clearPending();
          r(new Error('WebSocket error'));
        }
      };

      ws.onclose = () => {
        if (this.ws === ws) this.ws = null;
        this.connectPromise = null;
        this.stopHeartbeat();
        if (this.pendingResolve && this.hasPendingResponseData()) {
          const resolve = this.pendingResolve;
          const message = this.buildPendingMessage();
          this.clearPending();
          resolve(message);
        } else if (this.pendingReject) {
          const reject = this.pendingReject;
          this.clearPending();
          reject(new Error('WebSocket connection closed'));
        }
        if (!this.intentionalClose) {
          this.scheduleReconnect();
        }
      };
    });

    return this.connectPromise;
  }

  async sendMessage(
    request: { content: string; context?: PageContext; userId?: string },
    conversationId?: string,
    agentId?: string,
    onStream?: (chunk: StreamingMessage) => void,
  ): Promise<Message> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      await this.connect();
    }
    const ws = this.ws!;

    return new Promise<Message>((resolve, reject) => {
      this.pendingResolve = resolve;
      this.pendingReject = reject;
      this.pendingCallback = onStream ?? null;
      this.accumulatedContent = '';
      this.pendingMeta = {};

      ws.send(JSON.stringify({
        message: request.content,
        user_id: request.userId || 'anonymous',
        conversation_id: conversationId,
        agent_id: agentId,
        page_context: request.context,
        stream: true,
        session_token: this.sessionToken,
      }));
    });
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.stopHeartbeat();
    if (this.reconnectTimeoutId !== null) {
      clearTimeout(this.reconnectTimeoutId);
      this.reconnectTimeoutId = null;
    }
    this.ws?.close();
    this.ws = null;
    this.connectPromise = null;
  }
}
