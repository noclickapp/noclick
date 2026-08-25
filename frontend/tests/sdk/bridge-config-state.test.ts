// @vitest-environment jsdom
// Config reads + state (now routed through the backend workflow:state:* events, the
// canonical store shared with the WebSocket SDK and state-manager node execution),
// plus read-only gating and unknown-method handling.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mountBridge, testNode } from './helpers/mountBridge';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

let h: ReturnType<typeof mountBridge>;
let socket: MockSocket;
let teardown: () => void;

beforeEach(() => { ({ socket, teardown } = installMockSocket()); });
afterEach(() => { h?.cleanup(); teardown?.(); });

const settled = (id: string) => vi.waitFor(() => expect(h.responsesFor(id).length).toBeGreaterThan(0));

describe('SDK bridge — config', () => {
  it('nodes.getConfig returns data.config; errors for missing nodes', () => {
    h = mountBridge({ nodes: [testNode('n1', { config: { topic: 'cats' } })] });
    const ok = h.sendRequest('nodes.getConfig', { nodeId: 'n1' });
    expect(h.responsesFor(ok)[0].result).toEqual({ topic: 'cats' });

    const miss = h.sendRequest('nodes.getConfig', { nodeId: 'nope' });
    expect(h.responsesFor(miss)[0].error).toContain('outside the current workflow');
  });
});

describe('SDK bridge — state (backend-persisted)', () => {
  it('state.get fetches from the backend state store', async () => {
    h = mountBridge({ workflowId: 'wf-1' });
    socket.replyTo('workflow:state:get', { value: 7 });
    const id = h.sendRequest('state.get', { key: 'count' });
    await settled(id);
    expect(h.responsesFor(id)[0].result).toBe(7);
    expect(socket.expectSent('workflow:state:get').data).toMatchObject({ workflow_id: 'wf-1', key: 'count' });
  });

  it('state.set persists to the backend and pushes a local state:changed', async () => {
    h = mountBridge({ workflowId: 'wf-1' });
    socket.replyTo('workflow:state:set', { success: true });
    const id = h.sendRequest('state.set', { key: 'count', value: 7 });
    await settled(id);
    expect(h.responsesFor(id)[0]).toEqual({ type: 'noclick:response', id, result: null });
    expect(socket.expectSent('workflow:state:set').data).toMatchObject({ workflow_id: 'wf-1', key: 'count', value: 7 });
    expect(h.events('state:changed')).toContainEqual({
      type: 'noclick:event', event: 'state:changed', data: { key: 'count', value: 7 },
    });
  });

  it('state.delete sends a null value (backend deletes the key)', async () => {
    h = mountBridge({ workflowId: 'wf-1' });
    socket.replyTo('workflow:state:set', { success: true });
    const id = h.sendRequest('state.delete', { key: 'count' });
    await settled(id);
    expect(socket.expectSent('workflow:state:set').data).toMatchObject({ workflow_id: 'wf-1', key: 'count', value: null });
  });

  it('state.keys fetches keys from the backend', async () => {
    h = mountBridge({ workflowId: 'wf-1' });
    socket.replyTo('workflow:state:keys', { keys: ['a', 'b'] });
    const id = h.sendRequest('state.keys');
    await settled(id);
    expect(h.responsesFor(id)[0].result).toEqual(['a', 'b']);
  });

  it('state.set errors (no silent loss) when the workflow is unsaved', () => {
    h = mountBridge({ workflowId: '' }); // unsaved workflow → no scope to persist into
    const id = h.sendRequest('state.set', { key: 'k', value: 1 });
    expect(h.responsesFor(id)[0].error).toContain('not saved');
    expect(socket.hasSent('workflow:state:set')).toBe(false);
  });
});

describe('SDK bridge — read-only + unknown', () => {
  it('read-only mode blocks state.set but allows reads (from the in-memory snapshot)', () => {
    h = mountBridge({
      readOnly: true,
      nodes: [testNode('sm', { config: { state: { count: 5 } } }, 'state-manager')],
    });

    const blocked = h.sendRequest('state.set', { key: 'k', value: 1 });
    expect(h.responsesFor(blocked)[0].error).toContain('not available in read-only replay');

    const allowed = h.sendRequest('state.get', { key: 'count' });
    expect(h.responsesFor(allowed)[0].result).toBe(5); // in-memory replay snapshot, no backend call
    expect(socket.hasSent('workflow:state:get')).toBe(false);
  });

  it('rejects unknown methods', () => {
    h = mountBridge({ nodes: [] });
    const id = h.sendRequest('bogus.method');
    expect(h.responsesFor(id)[0].error).toBe('Unknown SDK method: bogus.method');
  });
});
