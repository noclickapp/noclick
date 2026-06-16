// Exercises the external-app WebSocket transport: method→socket-event mapping,
// response transforms, execution streaming, and disconnect handling — all against
// a fake socket.io-client so no real backend is needed.
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
    off(event: string, cb: Function) {
      this.handlers[event] = (this.handlers[event] || []).filter((h) => h !== cb);
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
  const io = vi.fn((..._args: any[]) => {
    const s = new FakeSocket();
    state.socket = s;
    return s;
  });
  return { state, io };
});

vi.mock('socket.io-client', () => ({ io: H.io }));

import { WebSocketTransport } from '../src/transports/websocket';

beforeEach(() => {
  H.state.socket = null;
  H.io.mockClear();
});

/** Build a connected transport plus a captured list of host→SDK messages it emits. */
async function connected(workflowId = 'wf-1') {
  const t = new WebSocketTransport({ url: 'http://localhost:8005', apiKey: 'nk_live_test', workflowId });
  const p = t.connect();
  await vi.waitFor(() => {
    if (!H.state.socket) throw new Error('socket not created yet');
  });
  const socket = H.state.socket!;
  socket.connected = true;
  socket.fire('connect');
  await p;

  const got: any[] = [];
  t.onMessage((m) => got.push(m));
  return { t, socket, got };
}

describe('WebSocketTransport — connection', () => {
  it('connects with api_key auth over the websocket transport', async () => {
    const { socket } = await connected();
    expect(H.io).toHaveBeenCalledWith(
      'http://localhost:8005',
      expect.objectContaining({ auth: { api_key: 'nk_live_test' }, transports: ['websocket'] }),
    );
    expect(socket.connected).toBe(true);
  });

  it('destroy disconnects the socket', async () => {
    const { t, socket } = await connected();
    t.destroy();
    expect(socket.disconnect).toHaveBeenCalled();
  });
});

describe('WebSocketTransport — request mapping + response transforms', () => {
  it('nodes.getOutput → workflow:get_node_outputs, unwraps first output value', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r1', method: 'nodes.getOutput', params: { nodeId: 'n1' } });
    expect(socket.emit).toHaveBeenCalledWith('workflow:get_node_outputs', {
      workflow_id: 'wf-1',
      node_ids: ['n1'],
      request_id: 'r1',
    });
    socket.fire('response', { request_id: 'r1', data: { outputs: { n1: 'hello' } } });
    expect(got).toContainEqual({ type: 'noclick:response', id: 'r1', result: 'hello' });
  });

  it('state.get → workflow:state:get, unwraps bare value', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r2', method: 'state.get', params: { key: 'k' } });
    expect(socket.emit).toHaveBeenCalledWith('workflow:state:get', { workflow_id: 'wf-1', key: 'k', request_id: 'r2' });
    socket.fire('response', { request_id: 'r2', data: { value: 42 } });
    expect(got).toContainEqual({ type: 'noclick:response', id: 'r2', result: 42 });
  });

  it('state.set emits a synthetic state:changed event after success', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r3', method: 'state.set', params: { key: 'k', value: 7 } });
    socket.fire('response', { request_id: 'r3', data: { ok: true } });
    expect(got).toContainEqual({ type: 'noclick:event', event: 'state:changed', data: { key: 'k', value: 7 } });
    expect(got).toContainEqual(expect.objectContaining({ type: 'noclick:response', id: 'r3' }));
  });

  it('auth.hasCredential → credential:list, transforms to boolean using request params', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r4', method: 'auth.hasCredential', params: { credentialType: 'github' } });
    expect(socket.emit).toHaveBeenCalledWith('credential:list', { request_id: 'r4' });
    socket.fire('response', { request_id: 'r4', data: { credentials: [{ credential_type: 'github' }] } });
    expect(got).toContainEqual({ type: 'noclick:response', id: 'r4', result: true });
  });

  it('nodes.list fetches graph + outputs and derives label/hasOutput (two-step)', async () => {
    const { t, socket, got } = await connected();
    const lastEmit = (event: string) => socket.emit.mock.calls.filter((c) => c[0] === event).slice(-1)[0]?.[1] as any;

    t.send({ type: 'noclick:request', id: 'r5', method: 'nodes.list', params: {} });

    await vi.waitFor(() => expect(socket.emit).toHaveBeenCalledWith('workflow:get', expect.anything()));
    socket.fire('response', {
      request_id: lastEmit('workflow:get').request_id,
      data: { workflow: { workflow_data: { nodes: [
        { id: 'a', type: 'automation-http-request', config: { label: 'Fetch' } },
        { id: 'c', type: 'collaborator-1' },
      ] } } },
    });

    // hasOutput now comes from a real node-outputs fetch, not the (absent) config.output
    await vi.waitFor(() => expect(socket.emit).toHaveBeenCalledWith('workflow:get_node_outputs', expect.anything()));
    socket.fire('response', { request_id: lastEmit('workflow:get_node_outputs').request_id, data: { outputs: { a: { x: 1 } } } });

    await vi.waitFor(() => expect(got.some((m) => m.id === 'r5' && m.type === 'noclick:response')).toBe(true));
    expect(got.find((m) => m.id === 'r5').result).toEqual([
      { id: 'a', type: 'automation-http-request', label: 'Fetch', hasOutput: true },
    ]);
  });

  it('resources.list maps backend rows to camelCase ResourceInfo', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r-rl', method: 'resources.list', params: {} });
    socket.fire('response', { request_id: 'r-rl', data: { resources: [
      { id: 'x', name: 'f.png', resource_type: 'file', mime_type: 'image/png', size_bytes: 5 },
    ] } });
    expect(got).toContainEqual({
      type: 'noclick:response', id: 'r-rl',
      result: [{ id: 'x', name: 'f.png', resourceType: 'file', mimeType: 'image/png', sizeBytes: 5 }],
    });
  });

  it('dataset.list includes rowCount', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r-dl', method: 'dataset.list', params: {} });
    socket.fire('response', { request_id: 'r-dl', data: { resources: [{ id: 'd1', name: 'Leads', metadata: { row_count: 3 } }] } });
    expect(got).toContainEqual({ type: 'noclick:response', id: 'r-dl', result: [{ id: 'd1', name: 'Leads', rowCount: 3 }] });
  });

  it('resources.upload does the two-step create + presigned URL', async () => {
    const { t, socket, got } = await connected();
    const lastEmit = (event: string) => socket.emit.mock.calls.filter((c) => c[0] === event).slice(-1)[0]?.[1] as any;

    t.send({ type: 'noclick:request', id: 'r-up', method: 'resources.upload', params: { name: 'a.png', mimeType: 'image/png', sizeBytes: 10 } });

    await vi.waitFor(() => expect(socket.emit).toHaveBeenCalledWith('resource:create', expect.objectContaining({ name: 'a.png' })));
    socket.fire('response', { request_id: lastEmit('resource:create').request_id, data: { resource: { id: 'res-1' } } });

    await vi.waitFor(() => expect(socket.emit).toHaveBeenCalledWith('resource:upload_url', expect.objectContaining({ resource_id: 'res-1' })));
    socket.fire('response', { request_id: lastEmit('resource:upload_url').request_id, data: { upload_url: 'https://up/res-1' } });

    await vi.waitFor(() => expect(got).toContainEqual({
      type: 'noclick:response', id: 'r-up', result: { resourceId: 'res-1', uploadUrl: 'https://up/res-1' },
    }));
  });

  it('rejects auth.requestCredential as unsupported without emitting', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r6', method: 'auth.requestCredential', params: { credentialType: 'x' } });
    expect(socket.emit).not.toHaveBeenCalled();
    expect(got[0]).toMatchObject({ type: 'noclick:response', id: 'r6' });
    expect(got[0].error).toContain('not supported');
  });

  it('rejects unknown methods', async () => {
    const { t, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r7', method: 'bogus.method', params: {} });
    expect(got[0]).toMatchObject({ type: 'noclick:response', id: 'r7' });
    expect(got[0].error).toContain('not supported');
  });

  it('execution.stop is acked locally and emits workflow:stop', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r8', method: 'execution.stop', params: {} });
    expect(socket.emit).toHaveBeenCalledWith('workflow:stop', { workflow_id: 'wf-1' });
    expect(got).toContainEqual({ type: 'noclick:response', id: 'r8', result: null });
  });
});

describe('WebSocketTransport — execution streaming', () => {
  it('runNodesAndGetOutput emits exec-prefixed workflow:execute and streams to done', async () => {
    const { t, socket, got } = await connected();
    t.send({
      type: 'noclick:request',
      id: 'r9',
      method: 'execution.runNodesAndGetOutput',
      params: { runNodes: [{ id: 'a' }], targetNodes: ['a'] },
    });
    expect(socket.emit).toHaveBeenCalledWith(
      'workflow:execute',
      expect.objectContaining({ workflow_id: 'wf-1', start_node_id: 'a', request_id: 'exec-r9' }),
    );

    socket.fire('workflow:node:output', { node_id: 'a', output: { v: 1 } });
    expect(got).toContainEqual({ type: 'noclick:stream', id: 'r9', event: 'output', nodeId: 'a', data: { v: 1 } });

    socket.fire('workflow:node:state', { node_id: 'a', state: 'completed' });
    expect(got).toContainEqual({ type: 'noclick:stream', id: 'r9', event: 'done' });
  });

  it('only signals done once ALL target nodes complete (execute-and-wait)', async () => {
    const { t, socket, got } = await connected();
    t.send({
      type: 'noclick:request',
      id: 'r10',
      method: 'execution.runNodesAndGetOutput',
      params: { runNodes: [{ id: 'a' }], targetNodes: ['a', 'b'] },
    });
    socket.fire('workflow:node:state', { node_id: 'a', state: 'completed' });
    expect(got.some((m) => m.id === 'r10' && m.event === 'done')).toBe(false);
    socket.fire('workflow:node:state', { node_id: 'b', state: 'completed' });
    expect(got).toContainEqual({ type: 'noclick:stream', id: 'r10', event: 'done' });
  });

  it('treats a skipped target node as terminal (sends done)', async () => {
    const { t, socket, got } = await connected();
    t.send({
      type: 'noclick:request',
      id: 'r-skip',
      method: 'execution.runNodesAndGetOutput',
      params: { runNodes: [{ id: 'a' }], targetNodes: ['a'] },
    });
    socket.fire('workflow:node:state', { node_id: 'a', state: 'skipped' });
    expect(got).toContainEqual({ type: 'noclick:stream', id: 'r-skip', event: 'done' });
  });

  it('routes exec-prefixed error responses to the stream', async () => {
    const { t, socket, got } = await connected();
    t.send({
      type: 'noclick:request',
      id: 'r11',
      method: 'execution.runNodesAndGetOutput',
      params: { runNodes: [{ id: 'a' }], targetNodes: ['a'] },
    });
    socket.fire('response', { request_id: 'exec-r11', error: 'kaboom' });
    expect(got).toContainEqual({ type: 'noclick:stream', id: 'r11', event: 'error', nodeId: 'a', data: 'kaboom' });
  });

  it('runNodesInBackground (fire) emits workflow:execute with config_overrides', async () => {
    const { t, socket } = await connected();
    t.send({
      type: 'noclick:fire',
      method: 'execution.runNodesInBackground',
      params: { runNodes: [{ id: 'a', config: { x: 1 } }] },
    });
    expect(socket.emit).toHaveBeenCalledWith('workflow:execute', {
      workflow_id: 'wf-1',
      start_node_id: 'a',
      config_overrides: { a: { x: 1 } },
    });
  });
});

describe('WebSocketTransport — disconnect', () => {
  it('errors pending requests and streams on disconnect', async () => {
    const { t, socket, got } = await connected();
    t.send({ type: 'noclick:request', id: 'r12', method: 'nodes.getOutput', params: { nodeId: 'n' } });
    t.send({
      type: 'noclick:request',
      id: 'r13',
      method: 'execution.runNodesAndGetOutput',
      params: { runNodes: [{ id: 'a' }], targetNodes: ['a'] },
    });

    socket.connected = false;
    socket.fire('disconnect');

    expect(got).toContainEqual({ type: 'noclick:response', id: 'r12', error: 'WebSocket disconnected' });
    expect(got).toContainEqual({ type: 'noclick:stream', id: 'r13', event: 'error', nodeId: 'a', data: 'WebSocket disconnected' });
  });
});
