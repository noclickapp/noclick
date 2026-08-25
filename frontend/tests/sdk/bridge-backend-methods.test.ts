// @vitest-environment jsdom
// Bridge methods that proxy to the backend over the socket: credentials, resources,
// datasets, and config persistence. Uses the integration MockSocket so we can assert
// the exact backend event the bridge emits AND the SDK-shaped result it returns.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mountBridge, testNode } from './helpers/mountBridge';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

let h: ReturnType<typeof mountBridge>;
let socket: MockSocket;
let teardown: () => void;

beforeEach(() => { ({ socket, teardown } = installMockSocket()); });
afterEach(() => { h?.cleanup(); teardown?.(); });

const settled = (id: string) => vi.waitFor(() => expect(h.responsesFor(id).length).toBeGreaterThan(0));

describe('SDK bridge — backend-proxied methods', () => {
  it('auth.listCredentials maps backend rows to {id,type,name}', async () => {
    h = mountBridge();
    socket.replyTo('credential:list', { credentials: [{ id: 'c1', credential_type: 'github', name: 'GH' }] });
    const id = h.sendRequest('auth.listCredentials');
    await settled(id);
    expect(h.responsesFor(id)[0].result).toEqual([{ id: 'c1', type: 'github', name: 'GH' }]);
    expect(socket.hasSent('credential:list')).toBe(true);
  });

  it('resources.upload creates the resource then resolves an upload URL', async () => {
    h = mountBridge({ workflowId: 'wf-1' });
    socket.replyTo('resource:create', { resource: { id: 'r1' } });
    socket.replyTo('resource:upload_url', { upload_url: 'https://up.example/r1' });
    const id = h.sendRequest('resources.upload', { name: 'a.png', mimeType: 'image/png', sizeBytes: 10 });
    await settled(id);
    expect(h.responsesFor(id)[0].result).toEqual({ resourceId: 'r1', uploadUrl: 'https://up.example/r1' });
    expect(socket.expectSent('resource:create').data).toMatchObject({
      resource_type: 'file', name: 'a.png', mime_type: 'image/png', size_bytes: 10,
    });
  });

  it('dataset.getRows maps rows + total_count to the SDK page shape', async () => {
    h = mountBridge();
    socket.replyTo('resource:dataset:rows', { rows: [{ id: 'row1', data: { a: 1 } }], total_count: 1 });
    const id = h.sendRequest('dataset.getRows', { resourceId: 'ds1', limit: 50, offset: 0 });
    await settled(id);
    expect(h.responsesFor(id)[0].result).toEqual({ rows: [{ id: 'row1', data: { a: 1 } }], totalCount: 1 });
    expect(socket.expectSent('resource:dataset:rows').data).toMatchObject({ resource_id: 'ds1', limit: 50, offset: 0 });
  });

  it('workflow.getInfo returns the real workflow name from the backend (not empty)', async () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('a', {}), testNode('b', {})] });
    socket.replyTo('workflow:get', {
      workflow: { id: 'wf-1', name: 'Repo Dashboard', workflow_data: { nodes: [{ id: 'a' }, { id: 'b' }] } },
    });
    const id = h.sendRequest('workflow.getInfo');
    await settled(id);
    expect(h.responsesFor(id)[0].result).toMatchObject({ id: 'wf-1', name: 'Repo Dashboard', nodeCount: 2 });
  });

  it('seeds useInputs from restored UPSTREAM outputs on load (not blank until a re-run)', async () => {
    h = mountBridge({
      workflowId: 'wf-1',
      nodes: [testNode('up1'), testNode('up2'), testNode('down')],
      edges: [{ source: 'up1', target: 'component-1' }, { source: 'up2', target: 'component-1' }],
    });
    // 'down' is not upstream of this component → must be excluded from the seed.
    socket.replyTo('workflow:get_node_outputs', { outputs: { up1: { v: 1 }, up2: { v: 2 }, down: { v: 3 } } });
    h.fireLoad(); // iframe load → bridge init effect
    await vi.waitFor(() => expect(h.events('inputs:changed').length).toBeGreaterThan(0));
    expect(h.events('inputs:changed')[0].data).toEqual({ up1: { v: 1 }, up2: { v: 2 } });
  });

  it('nodes.setConfig merges in-memory config AND persists to the backend', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('n1', { config: { a: 1 } })] });
    socket.replyTo('workflow:node:set_config', { success: true });
    const id = h.sendRequest('nodes.setConfig', { nodeId: 'n1', config: { b: 2 } });

    // Acks synchronously and merges into data.config.
    expect(h.responsesFor(id)[0]).toEqual({ type: 'noclick:response', id, result: null });
    expect((h.getNodesNow()[0].data as any).config).toEqual({ a: 1, b: 2 });
    // Durable persist is emitted to the backend (best-effort).
    expect(socket.expectSent('workflow:node:set_config').data).toMatchObject({ node_id: 'n1', config: { b: 2 } });
  });
});
