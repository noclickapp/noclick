// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest';

const H = vi.hoisted(() => {
  class FakeSocket {
    connected = false;
    handlers: Record<string, Function[]> = {};
    onceHandlers: Record<string, Function[]> = {};
    emit = vi.fn();
    disconnect = vi.fn();
    on(event: string, cb: Function) {
      (this.handlers[event] ||= []).push(cb);
      return this;
    }
    once(event: string, cb: Function) {
      (this.onceHandlers[event] ||= []).push(cb);
      return this;
    }
    fire(event: string, ...args: any[]) {
      (this.handlers[event] || []).slice().forEach((cb) => cb(...args));
      const once = this.onceHandlers[event] || [];
      this.onceHandlers[event] = [];
      once.forEach((cb) => cb(...args));
    }
  }
  const state: { socket: FakeSocket | null } = { socket: null };
  const io = vi.fn(() => {
    const s = new FakeSocket();
    state.socket = s;
    return s;
  });
  return { state, io };
});

vi.mock('socket.io-client', () => ({ io: H.io }));

import { init } from '../src/index';
import { getTransport, isInitialized } from '../src/core/transport';
import { PostMessageTransport } from '../src/transports/postmessage';

beforeEach(() => {
  H.state.socket = null;
  H.io.mockClear();
});

describe('init', () => {
  it('defaults to a PostMessageTransport', async () => {
    await init();
    expect(isInitialized()).toBe(true);
    expect(getTransport()).toBeInstanceOf(PostMessageTransport);
  });

  it("throws when websocket transport is requested without an apiKey", async () => {
    await expect(init({ transport: 'websocket' })).rejects.toThrow("requires 'apiKey'");
  });

  it('throws on an unknown transport name', async () => {
    await expect(init({ transport: 'bogus' as any })).rejects.toThrow('Unknown transport');
  });

  it('selects the websocket transport when an apiKey is provided', async () => {
    const p = init({ apiKey: 'nk_live_x', url: 'http://localhost:8005' });
    await vi.waitFor(() => {
      if (!H.state.socket) throw new Error('socket not created yet');
    });
    H.state.socket!.connected = true;
    H.state.socket!.fire('connect');
    await p;
    expect(H.io).toHaveBeenCalledWith('http://localhost:8005', expect.objectContaining({ auth: { api_key: 'nk_live_x' } }));
    expect(isInitialized()).toBe(true);
  });

  it('accepts a custom Transport instance', async () => {
    const fake = { send() {}, onMessage: () => () => {}, destroy() {} };
    await init({ transport: fake });
    expect(getTransport()).toBe(fake);
  });
});
