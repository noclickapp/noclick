// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';

const R = vi.hoisted(() => ({ joined: [] as string[] }));

vi.mock('../../src/room.ts', () => ({
  Room: { join: async (name: string) => { R.joined.push(name); return { on: () => () => {}, leave() {} }; } },
}));

import { init } from '../../src/embed/index';
import { getTransport, isInitialized } from '../../src/embed/core/transport';
import { HttpTransport } from '../../src/embed/transports/http';
import { PostMessageTransport } from '../../src/embed/transports/postmessage';

describe('init', () => {
  it('defaults to a PostMessageTransport', async () => {
    await init();
    expect(isInitialized()).toBe(true);
    expect(getTransport()).toBeInstanceOf(PostMessageTransport);
  });

  it('throws when the http transport is asked for without an apiKey and a workflowId', async () => {
    await expect(init({ transport: 'http' })).rejects.toThrow("requires 'apiKey' and 'workflowId'");
    await expect(init({ apiKey: 'nk_live_x' })).rejects.toThrow("requires 'apiKey' and 'workflowId'");
  });

  it('throws on an unknown transport name, the old socket one included', async () => {
    await expect(init({ transport: 'bogus' as any })).rejects.toThrow('Unknown transport');
    await expect(init({ transport: 'websocket' as any })).rejects.toThrow("Use 'postmessage', 'http'");
  });

  it('picks the http transport when an apiKey is given, joining its pages\' room', async () => {
    await init({ apiKey: 'nk_live_x', workflowId: 'wf-1' });
    expect(getTransport()).toBeInstanceOf(HttpTransport);
    expect(R.joined).toEqual(['page:wf-1']);
  });

  it('accepts a custom Transport instance', async () => {
    const fake = { send() {}, onMessage: () => () => {}, destroy() {} };
    await init({ transport: fake });
    expect(getTransport()).toBe(fake);
  });
});
