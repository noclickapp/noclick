// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PostMessageTransport } from '../src/transports/postmessage';

describe('PostMessageTransport', () => {
  let t: PostMessageTransport | null = null;

  afterEach(() => {
    t?.destroy();
    t = null;
    vi.restoreAllMocks();
  });

  it('send() posts to window.parent with a wildcard origin', () => {
    const spy = vi.spyOn(window.parent, 'postMessage');
    t = new PostMessageTransport();
    const msg = { type: 'noclick:request', id: 'r1', method: 'nodes.getOutput', params: { nodeId: 'n1' } };
    t.send(msg);
    expect(spy).toHaveBeenCalledWith(msg, '*');
  });

  it('delivers only noclick:-prefixed object messages to handlers', () => {
    t = new PostMessageTransport();
    const seen: unknown[] = [];
    t.onMessage((m) => seen.push(m));

    window.dispatchEvent(new MessageEvent('message', { data: { type: 'noclick:event', event: 'init', data: {} } }));
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'other:thing' } }));
    window.dispatchEvent(new MessageEvent('message', { data: 'a bare string' }));
    window.dispatchEvent(new MessageEvent('message', { data: null }));

    expect(seen).toEqual([{ type: 'noclick:event', event: 'init', data: {} }]);
  });

  it('supports multiple handlers and unsubscribe', () => {
    t = new PostMessageTransport();
    const a: unknown[] = [];
    const b: unknown[] = [];
    const unsubA = t.onMessage((m) => a.push(m));
    t.onMessage((m) => b.push(m));

    window.dispatchEvent(new MessageEvent('message', { data: { type: 'noclick:event', event: 'x', data: 1 } }));
    unsubA();
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'noclick:event', event: 'y', data: 2 } }));

    expect(a).toHaveLength(1);
    expect(b).toHaveLength(2);
  });

  it('destroy() stops delivering messages', () => {
    t = new PostMessageTransport();
    const seen: unknown[] = [];
    t.onMessage((m) => seen.push(m));
    t.destroy();
    t = null;
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'noclick:event', event: 'x', data: 1 } }));
    expect(seen).toEqual([]);
  });
});
