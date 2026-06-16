import { describe, expect, it, vi } from 'vitest';
import { setTransport, request, send, requestStream, subscribe, isInitialized } from '../src/core/transport';
import { createFakeHost } from './helpers/fakeHost';

describe('core transport — request/response', () => {
  it('sends a noclick:request and resolves with the matching response result', async () => {
    const host = createFakeHost();
    setTransport(host.transport);

    const p = request('nodes.getOutput', { nodeId: 'n1' });
    const msg = host.lastSent();
    expect(msg.type).toBe('noclick:request');
    expect(msg.method).toBe('nodes.getOutput');
    expect(msg.params).toEqual({ nodeId: 'n1' });
    expect(typeof msg.id).toBe('string');

    host.reply(msg.id, { value: 42 });
    await expect(p).resolves.toEqual({ value: 42 });
  });

  it('rejects with an Error carrying the response error string', async () => {
    const host = createFakeHost();
    setTransport(host.transport);

    const p = request('nodes.getOutput', { nodeId: 'n1' });
    host.replyError(host.lastSent().id, 'boom');
    await expect(p).rejects.toThrow('boom');
  });

  it('ignores responses whose id does not match a pending request', async () => {
    const host = createFakeHost();
    setTransport(host.transport);

    const p = request('x');
    host.reply('some-other-id', 'wrong');
    host.reply(host.lastSent().id, 'right');
    await expect(p).resolves.toBe('right');
  });

  it('correlates concurrent requests independently by id', async () => {
    const host = createFakeHost();
    setTransport(host.transport);

    const a = request('m', { which: 'a' });
    const idA = host.lastSent().id;
    const b = request('m', { which: 'b' });
    const idB = host.lastSent().id;
    expect(idA).not.toBe(idB);

    host.reply(idB, 'B');
    host.reply(idA, 'A');
    await expect(a).resolves.toBe('A');
    await expect(b).resolves.toBe('B');
  });

  it('times out a request after 30s with a descriptive message', async () => {
    vi.useFakeTimers();
    try {
      const host = createFakeHost();
      setTransport(host.transport);
      const p = request('slow.method');
      const assertion = expect(p).rejects.toThrow("SDK request 'slow.method' timed out after 30000ms");
      await vi.advanceTimersByTimeAsync(30000);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it('send() emits a fire-and-forget message with no id', () => {
    const host = createFakeHost();
    setTransport(host.transport);
    send('execution.runNodesInBackground', { runNodes: [{ id: 'a' }] });
    expect(host.lastSent()).toEqual({
      type: 'noclick:fire',
      method: 'execution.runNodesInBackground',
      params: { runNodes: [{ id: 'a' }] },
    });
  });
});

describe('core transport — streams', () => {
  it('collects per-node outputs and resolves all() on done', async () => {
    const host = createFakeHost();
    setTransport(host.transport);

    const stream = requestStream('execution.runNodesAndGetOutput', { targetNodes: ['a', 'b'] });
    const outputs: Array<[string, unknown]> = [];
    let done = false;
    stream.on('output', (nodeId, data) => outputs.push([nodeId, data]));
    stream.on('done', () => { done = true; });

    const id = host.lastSent().id;
    host.streamOutput(id, 'a', 1);
    host.streamOutput(id, 'b', 2);
    host.streamDone(id);

    const all = await stream.all();
    expect(outputs).toEqual([['a', 1], ['b', 2]]);
    expect(done).toBe(true);
    expect(all).toEqual({ a: 1, b: 2 });
  });

  it('fires the error handler and rejects all() on a stream error', async () => {
    const host = createFakeHost();
    setTransport(host.transport);

    const stream = requestStream('execution.runNodesAndGetOutput', {});
    const errs: Array<[string, string]> = [];
    stream.on('error', (nodeId, e) => errs.push([nodeId, e]));

    const id = host.lastSent().id;
    const assertion = expect(stream.all()).rejects.toThrow('Stream error on node a: kaboom');
    host.streamError(id, 'a', 'kaboom');
    await assertion;
    expect(errs).toEqual([['a', 'kaboom']]);
  });

  it('times out a stream after 60s', async () => {
    vi.useFakeTimers();
    try {
      const host = createFakeHost();
      setTransport(host.transport);
      const stream = requestStream('execution.runNodesAndGetOutput', {});
      const assertion = expect(stream.all()).rejects.toThrow(
        "SDK stream 'execution.runNodesAndGetOutput' timed out after 60000ms",
      );
      await vi.advanceTimersByTimeAsync(60000);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('core transport — events', () => {
  it('dispatches noclick:event to subscribers and supports unsubscribe', () => {
    const host = createFakeHost();
    setTransport(host.transport);

    const seen: unknown[] = [];
    const unsub = subscribe('node:state', (d) => seen.push(d));
    host.emitEvent('node:state', { nodeId: 'n1', state: 'running' });
    unsub();
    host.emitEvent('node:state', { nodeId: 'n1', state: 'completed' });

    expect(seen).toEqual([{ nodeId: 'n1', state: 'running' }]);
  });
});

describe('core transport — replacement', () => {
  it('rejects in-flight requests and streams when the transport is replaced', async () => {
    const host = createFakeHost();
    setTransport(host.transport);

    const req = request('slow.method');
    const stream = requestStream('execution.runNodesAndGetOutput', {});
    const reqAssertion = expect(req).rejects.toThrow('transport was replaced');
    const streamAssertion = expect(stream.all()).rejects.toThrow('transport was replaced');

    setTransport(createFakeHost().transport); // re-init swaps the transport

    await reqAssertion;
    await streamAssertion;
  });
});

describe('core transport — uninitialized', () => {
  it('throws if a request is made before init', async () => {
    vi.resetModules();
    const mod = await import('../src/core/transport');
    expect(mod.isInitialized()).toBe(false);
    expect(() => mod.request('x')).toThrow('@noclick/sdk not initialized');
  });

  it('isInitialized reflects setTransport', () => {
    const host = createFakeHost();
    setTransport(host.transport);
    expect(isInitialized()).toBe(true);
  });
});
