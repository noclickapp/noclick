// PostMessage transport for iframe-hosted custom components.
// Communicates with the NoClick host (HtmlReactBlock) via window.parent.postMessage.

import type { Transport } from '../core/transport.js';

export class PostMessageTransport implements Transport {
  private handlers = new Set<(msg: any) => void>();
  private listener: ((e: MessageEvent) => void) | null = null;

  constructor() {
    this.listener = (e: MessageEvent) => {
      const msg = e.data;
      if (!msg || typeof msg !== 'object' || typeof msg.type !== 'string') return;
      if (!msg.type.startsWith('noclick:')) return;
      this.handlers.forEach(fn => fn(msg));
    };
    window.addEventListener('message', this.listener);
  }

  send(msg: Record<string, unknown>): void {
    window.parent.postMessage(msg, '*');
  }

  onMessage(handler: (msg: any) => void): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  destroy(): void {
    if (this.listener) {
      window.removeEventListener('message', this.listener);
      this.listener = null;
    }
    this.handlers.clear();
  }
}
