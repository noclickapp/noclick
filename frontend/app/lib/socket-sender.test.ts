// The raw-data emit path (single 'data' key) must never SPREAD a typed array:
// { ...uint8array } becomes {'0': 0, '1': 2, ...} and every yjs:sync collab
// frame failed backend validation until 2026-07-19. The timing stamp is only
// injected into PLAIN objects.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const sent: Array<{ event: string; payload: unknown }> = [];
vi.mock('~/lib/socket-receiver', () => ({
  socketReceiver: {
    sendEvent: (event: string, payload: unknown) => {
      sent.push({ event, payload });
      return true;
    },
  },
}));
vi.mock('~/lib/profilingStore', () => ({
  profilingStore: { startEvent: vi.fn() },
}));

import { sendEvent } from '~/lib/socket-sender';

describe('sendEvent raw-data path', () => {
  beforeEach(() => { sent.length = 0; });

  it('passes Uint8Array payloads through untouched (yjs:sync)', () => {
    const update = new Uint8Array([0, 2, 98, 115, 1, 0]);
    sendEvent({ event_name: 'yjs:sync', data: update } as never);
    expect(sent).toHaveLength(1);
    const payload = sent[0].payload;
    expect(payload).toBe(update);           // same reference — never spread
    expect(ArrayBuffer.isView(payload)).toBe(true);
  });

  it('passes plain arrays through untouched', () => {
    const arr = [1, 2, 3];
    sendEvent({ event_name: 'yjs:sync', data: arr } as never);
    expect(sent[0].payload).toBe(arr);
  });

  it('stamps timing only into plain objects', () => {
    sendEvent({ event_name: 'some:event', data: { a: 1 } } as never);
    const payload = sent[0].payload as Record<string, unknown>;
    expect(payload.a).toBe(1);
    expect(typeof payload._client_sent_at_ms).toBe('number');
  });
});
