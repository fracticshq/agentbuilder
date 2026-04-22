import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { WebSocketClient } from './wsClient';

// MockWebSocket is installed globally in src/test/setup.ts
type MockWS = InstanceType<typeof WebSocket> & {
  url: string;
  readyState: number;
  simulateMessage: (data: object) => void;
  simulateClose: () => void;
};

function lastWS(): MockWS {
  const ws = (globalThis.WebSocket as any).lastInstance as MockWS;
  if (!ws) throw new Error('No MockWebSocket instance created yet');
  return ws;
}

/**
 * Flush two microtask checkpoints so that:
 *   1. queueMicrotask(onopen) fires and resolves connect()'s inner Promise
 *   2. sendMessage's continuation after `await this.connect()` runs (sets pending state)
 */
const flushMicrotasks = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

// ─── Existing tests ────────────────────────────────────────────────────────

describe('WebSocketClient', () => {
  describe('URL conversion', () => {
    it('converts http:// baseUrl to ws://', async () => {
      const client = new WebSocketClient('http://localhost:8000');
      const p = client.sendMessage({ content: 'hi' }, undefined, undefined, undefined);
      await flushMicrotasks();
      expect(lastWS().url).toBe('ws://localhost:8000/api/v1/messages/ws');
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'c1' });
      await p;
      client.disconnect();
    });

    it('converts https:// baseUrl to wss://', async () => {
      const client = new WebSocketClient('https://example.com');
      const p = client.sendMessage({ content: 'hi' }, undefined, undefined, undefined);
      await flushMicrotasks();
      expect(lastWS().url).toBe('wss://example.com/api/v1/messages/ws');
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'c1' });
      await p;
      client.disconnect();
    });
  });

  describe('sendMessage()', () => {
    let client: WebSocketClient;

    beforeEach(() => {
      client = new WebSocketClient('http://localhost:8000');
    });
    afterEach(() => client.disconnect());

    it('opens a WebSocket connection on first call', async () => {
      const p = client.sendMessage({ content: 'hello' });
      await flushMicrotasks();
      expect(lastWS()).toBeTruthy();
      expect(lastWS().url).toBe('ws://localhost:8000/api/v1/messages/ws');
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'c1' });
      await p;
    });

    it('sends correct JSON payload (message, user_id, conversation_id, agent_id, stream: true)', async () => {
      const p = client.sendMessage(
        { content: 'test msg', userId: 'u1' },
        'conv-abc',
        'agent-xyz',
      );
      await flushMicrotasks();
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'conv-abc' });
      await p;

      expect(lastWS().send).toHaveBeenCalledOnce();
      const sent = JSON.parse((lastWS().send as any).mock.calls[0][0]);
      expect(sent).toMatchObject({
        message: 'test msg',
        user_id: 'u1',
        conversation_id: 'conv-abc',
        agent_id: 'agent-xyz',
        stream: true,
      });
    });

    it('calls onStream for each content chunk', async () => {
      const chunks: string[] = [];
      const p = client.sendMessage(
        { content: 'hi' },
        undefined,
        undefined,
        (chunk) => { if (chunk.type === 'content') chunks.push(chunk.content); }
      );
      await flushMicrotasks();
      lastWS().simulateMessage({ type: 'content', content: 'Hello', conversation_id: 'c' });
      lastWS().simulateMessage({ type: 'content', content: ' world', conversation_id: 'c' });
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p;

      expect(chunks).toEqual(['Hello', ' world']);
    });

    it('accumulates content and resolves with final Message on metadata chunk', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      lastWS().simulateMessage({ type: 'content', content: 'Part1', conversation_id: 'c' });
      lastWS().simulateMessage({ type: 'content', content: 'Part2', conversation_id: 'c' });
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });

      const result = await p;
      expect(result.content).toBe('Part1Part2');
      expect(result.role).toBe('assistant');
    });

    it('calls onStream for status chunks', async () => {
      const statusTypes: string[] = [];
      const p = client.sendMessage(
        { content: 'hi' },
        undefined,
        undefined,
        (chunk) => { if (chunk.type === 'status') statusTypes.push(chunk.type); }
      );
      await flushMicrotasks();
      lastWS().simulateMessage({ type: 'status', content: 'thinking', conversation_id: 'c' });
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p;

      expect(statusTypes).toEqual(['status']);
    });

    it('captures citations from metadata chunk', async () => {
      const citations = [{ doc_id: 'd1', title: 'Doc', confidence: 0.9 }];
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'c', citations });
      const result = await p;
      expect(result.citations).toEqual(citations);
    });

    it('captures products and dealers from metadata chunk', async () => {
      const products = [{ sku: 'P1', name: 'Widget', price: 9.99 }];
      const dealers = [{ dealer_id: 'D1', name: 'Acme', city: 'NYC' }];
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      lastWS().simulateMessage({ type: 'metadata', content: '', conversation_id: 'c', products, dealers });
      const result = await p;
      expect(result.products).toEqual(products);
      expect(result.dealers).toEqual(dealers);
    });

    it('rejects the Promise on an error chunk', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      lastWS().simulateMessage({ type: 'error', content: 'Something went wrong', conversation_id: 'c' });
      await expect(p).rejects.toThrow('Something went wrong');
    });

    it('resolves with partial content if the socket closes after streaming has started', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      lastWS().simulateMessage({ type: 'content', content: 'Partial answer', conversation_id: 'c' });
      lastWS().simulateClose();

      await expect(p).resolves.toMatchObject({
        content: 'Partial answer',
        role: 'assistant',
      });
    });
  });

  describe('connection reuse', () => {
    it('reuses the same WebSocket instance for a second sendMessage() call', async () => {
      const client = new WebSocketClient('http://localhost:8000');

      const p1 = client.sendMessage({ content: 'first' });
      await flushMicrotasks();
      const ws1 = lastWS();
      ws1.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p1;

      const p2 = client.sendMessage({ content: 'second' });
      await flushMicrotasks();
      const ws2 = lastWS();
      expect(ws2).toBe(ws1);
      ws1.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p2;

      client.disconnect();
    });
  });

  describe('reconnection', () => {
    it('opens a new connection if previous was closed before sendMessage()', async () => {
      const client = new WebSocketClient('http://localhost:8000');

      const p1 = client.sendMessage({ content: 'first' });
      await flushMicrotasks();
      const ws1 = lastWS();
      ws1.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p1;
      ws1.simulateClose();

      const p2 = client.sendMessage({ content: 'second' });
      await flushMicrotasks();
      const ws2 = lastWS();
      expect(ws2).not.toBe(ws1);
      ws2.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p2;

      client.disconnect();
    });
  });

  // ─── Heartbeat ───────────────────────────────────────────────────────────

  describe('heartbeat', () => {
    let client: WebSocketClient;

    beforeEach(() => {
      vi.useFakeTimers();
      client = new WebSocketClient('http://localhost:8000', {
        heartbeatInterval: 1_000,
        pongTimeout: 500,
      });
    });
    afterEach(() => {
      client.disconnect();
      vi.useRealTimers();
    });

    it('sends ping after heartbeat interval', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      const ws = lastWS();
      ws.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p;

      ws.send.mockClear();
      vi.advanceTimersByTime(1_000);
      expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: 'ping' }));
    });

    it('does not close connection when pong is received within timeout', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      const ws = lastWS();
      ws.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p;

      vi.advanceTimersByTime(1_000);   // heartbeat fires → ping sent, pong timeout starts
      ws.simulateMessage({ type: 'pong' }); // pong clears the timeout
      vi.advanceTimersByTime(500);     // pong timeout would have fired — but it's cancelled
      expect(ws.close).not.toHaveBeenCalled();
    });

    it('closes connection when pong is not received within timeout', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      const ws = lastWS();
      ws.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p;

      vi.advanceTimersByTime(1_000);  // heartbeat fires → ping sent
      // no pong
      vi.advanceTimersByTime(500);   // pong timeout fires → close
      expect(ws.close).toHaveBeenCalled();
    });
  });

  // ─── Auto-reconnect ──────────────────────────────────────────────────────

  describe('auto-reconnect', () => {
    let client: WebSocketClient;

    beforeEach(() => {
      vi.useFakeTimers();
      client = new WebSocketClient('http://localhost:8000', {
        reconnectBaseDelay: 100,
        heartbeatInterval: 60_000, // keep heartbeat out of the way
      });
    });
    afterEach(() => {
      client.disconnect();
      vi.useRealTimers();
    });

    it('auto-reconnects after unexpected close', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      const ws1 = lastWS();
      ws1.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p;

      ws1.simulateClose();           // triggers scheduleReconnect (100ms delay)
      vi.advanceTimersByTime(100);   // fires the reconnect timeout → new WebSocket created
      await flushMicrotasks();       // drains queueMicrotask(onopen)

      expect(lastWS()).not.toBe(ws1);
    });

    it('does not auto-reconnect after intentional disconnect()', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      const ws1 = lastWS();
      ws1.simulateMessage({ type: 'metadata', content: '', conversation_id: 'c' });
      await p;

      client.disconnect();           // intentional — should NOT reconnect
      vi.advanceTimersByTime(1_000);
      await flushMicrotasks();

      expect(lastWS()).toBe(ws1);    // no new WS created
    });

    it('preserves a pending partial stream when connection drops mid-stream', async () => {
      const p = client.sendMessage({ content: 'hi' });
      await flushMicrotasks();
      const ws1 = lastWS();

      // Partial stream content received, then connection drops
      ws1.simulateMessage({ type: 'content', content: 'partial...', conversation_id: 'c' });
      ws1.simulateClose();

      await expect(p).resolves.toMatchObject({
        content: 'partial...',
        role: 'assistant',
      });
    });
  });
});
