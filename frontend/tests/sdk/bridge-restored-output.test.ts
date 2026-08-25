// @vitest-environment jsdom
// Scenario (a): a background run stored an output; the user opens the UI later
// and nodes.getOutput must return it. Two timing cases matter:
//   - node.data.output already hydrated  → fast in-memory read (no backend hit)
//   - NOT yet hydrated (initial load race) → bridge must fetch from the backend
//     rather than return a premature null that only "fixes itself" on a re-render.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mountBridge, testNode } from './helpers/mountBridge';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

let h: ReturnType<typeof mountBridge>;
let socket: MockSocket;
let teardown: () => void;

beforeEach(() => { ({ socket, teardown } = installMockSocket()); });
afterEach(() => { h?.cleanup(); teardown?.(); });

const settled = (id: string) => vi.waitFor(() => expect(h.responsesFor(id).length).toBeGreaterThan(0));

describe('SDK bridge — restored outputs (nodes.getOutput)', () => {
  it('returns an already-hydrated output from memory without hitting the backend', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('data-1', { output: { rows: [1, 2, 3] } })] });
    const id = h.sendRequest('nodes.getOutput', { nodeId: 'data-1' });
    expect(h.responsesFor(id)).toEqual([{ type: 'noclick:response', id, result: { rows: [1, 2, 3] } }]);
    expect(socket.hasSent('workflow:get_node_outputs')).toBe(false); // fast path, no fetch
  });

  // Regression for the initial-load race: a component mounts and calls getOutput
  // BEFORE FlowCanvas's workflow:get_node_outputs has hydrated node.data.output.
  // The bridge must fetch the restored output from the backend, not return null.
  it('fetches the restored output from the backend when not yet hydrated in memory', async () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('github-rest_dgqj', {})] });
    socket.replyTo('workflow:get_node_outputs', { outputs: { 'github-rest_dgqj': { stars: 42 } } });

    const id = h.sendRequest('nodes.getOutput', { nodeId: 'github-rest_dgqj' });
    await settled(id);

    expect(h.responsesFor(id)[0].result).toEqual({ stars: 42 });
    expect(socket.expectSent('workflow:get_node_outputs').data).toMatchObject({
      workflow_id: 'wf-1', node_ids: ['github-rest_dgqj'],
    });
  });

  it('rejects output reads for a node outside the mounted graph capability', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [] });
    const id = h.sendRequest('nodes.getOutput', { nodeId: 'late-node' });
    expect(h.responsesFor(id)[0].error).toContain('outside the current workflow');
    expect(socket.hasSent('workflow:get_node_outputs')).toBe(false);
  });

  it('returns null when the node has no stored output anywhere', async () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('data-1', {})] });
    socket.replyTo('workflow:get_node_outputs', { outputs: {} });
    const id = h.sendRequest('nodes.getOutput', { nodeId: 'data-1' });
    await settled(id);
    expect(h.responsesFor(id)[0].result).toBeNull();
  });

  it('nodes.list reflects which nodes have restored output', () => {
    h = mountBridge({
      nodes: [testNode('a', { output: { x: 1 }, label: 'A' }), testNode('b', { label: 'B' })],
    });
    const id = h.sendRequest('nodes.list');
    const list = h.responsesFor(id)[0].result as any[];
    expect(list).toContainEqual({ id: 'a', type: 'automation-http-request', label: 'A', hasOutput: true });
    expect(list).toContainEqual({ id: 'b', type: 'automation-http-request', label: 'B', hasOutput: false });
  });
});
