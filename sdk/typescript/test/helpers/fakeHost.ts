// A fake Transport that stands in for the host (HtmlReactBlock bridge or backend).
// Records what the SDK sends and lets a test push host→SDK messages back through
// the exact same channel the real transports use (`onMessage` handler).

import type { Transport } from '../../src/core/transport';

export interface FakeHost {
  transport: Transport;
  /** Every raw message the SDK sent, in order. */
  sent: Array<Record<string, unknown>>;
  /** The most recent sent message. */
  lastSent(): any;
  // host → SDK
  reply(id: string, result: unknown): void;
  replyError(id: string, error: string): void;
  streamOutput(id: string, nodeId: string, data: unknown): void;
  streamError(id: string, nodeId: string, data: unknown): void;
  streamDone(id: string): void;
  emitEvent(event: string, data: unknown): void;
}

export function createFakeHost(): FakeHost {
  let handler: ((msg: any) => void) | null = null;
  const sent: Array<Record<string, unknown>> = [];

  const transport: Transport = {
    send(msg) {
      sent.push(msg);
    },
    onMessage(h) {
      handler = h as (msg: any) => void;
      return () => {
        if (handler === h) handler = null;
      };
    },
    destroy() {
      handler = null;
    },
  };

  const deliver = (msg: any) => {
    if (!handler) throw new Error('FakeHost: no message handler registered (call setTransport first)');
    handler(msg);
  };

  return {
    transport,
    sent,
    lastSent: () => sent[sent.length - 1],
    reply: (id, result) => deliver({ type: 'noclick:response', id, result }),
    replyError: (id, error) => deliver({ type: 'noclick:response', id, error }),
    streamOutput: (id, nodeId, data) => deliver({ type: 'noclick:stream', id, event: 'output', nodeId, data }),
    streamError: (id, nodeId, data) => deliver({ type: 'noclick:stream', id, event: 'error', nodeId, data }),
    streamDone: (id) => deliver({ type: 'noclick:stream', id, event: 'done' }),
    emitEvent: (event, data) => deliver({ type: 'noclick:event', event, data }),
  };
}
