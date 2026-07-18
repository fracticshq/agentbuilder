import '@testing-library/jest-dom';
import { vi } from 'vitest';

// jsdom doesn't implement scrollIntoView
Element.prototype.scrollIntoView = () => {};

class MockWebSocket {
  static lastInstance: MockWebSocket | null = null;
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  url: string;
  readyState = 0; // CONNECTING
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = 3; });

  constructor(url: string) {
    this.url = url;
    MockWebSocket.lastInstance = this;
    queueMicrotask(() => {
      this.readyState = 1; // OPEN
      this.onopen?.(new Event('open'));
    });
  }

  simulateMessage(data: object) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }));
  }
  simulateClose() {
    this.readyState = 3;
    this.onclose?.(new CloseEvent('close'));
  }
}
globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
