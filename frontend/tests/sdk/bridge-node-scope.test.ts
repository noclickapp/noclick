// These tests exercise the component bridge as a workflow-scoped capability.
// Author-supplied IDs must resolve in the mounted graph before any read, write,
// execution, state, or realtime side effect can cross the iframe boundary.

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mountBridge, testNode } from './helpers/mountBridge';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

let h: ReturnType<typeof mountBridge>;
let socket: MockSocket;
let teardown: () => void;

beforeEach(() => { ({ socket, teardown } = installMockSocket()); });
afterEach(() => { h?.cleanup(); teardown?.(); });

describe('SDK bridge node capability', () => {
  it('rejects an output read for an ID outside the mounted workflow', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('inside')] });
    const id = h.sendRequest('nodes.getOutput', { nodeId: 'guessed-cross-workflow-id' });

    expect(h.responsesFor(id)[0].error).toContain('outside the current workflow');
    expect(socket.hasSent('workflow:get_node_outputs')).toBe(false);
  });

  it('rejects a config write before local mutation or backend persistence', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('inside', { config: { safe: true } })] });
    const id = h.sendRequest('nodes.setConfig', { nodeId: 'outside', config: { safe: false } });

    expect(h.responsesFor(id)[0].error).toContain('outside the current workflow');
    expect(h.getNodesNow()[0].data.config).toEqual({ safe: true });
    expect(socket.hasSent('workflow:node:set_config')).toBe(false);
  });

  it('rejects unknown run and target IDs before dispatching execution', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('inside')] });
    const badRun = h.sendRequest('execution.runNodesAndGetOutput', {
      runNodes: [{ id: 'outside' }],
      targetNodes: ['inside'],
    });
    const badTarget = h.sendRequest('execution.runNodesAndGetOutput', {
      runNodes: [{ id: 'inside' }],
      targetNodes: ['outside'],
    });

    expect(h.responsesFor(badRun)[0].error).toContain('outside the current workflow');
    expect(h.responsesFor(badTarget)[0].error).toContain('outside the current workflow');
    expect(h.runFromNode).toEqual([]);
  });

  it('accepts only an in-graph state-manager as an explicit state target', () => {
    h = mountBridge({
      workflowId: 'wf-1',
      nodes: [testNode('ordinary'), testNode('state-1', {}, 'state-manager')],
    });
    const wrongType = h.sendRequest('state.get', { key: 'x', node: 'ordinary' });
    const unknown = h.sendRequest('state.get', { key: 'x', node: 'outside' });

    expect(h.responsesFor(wrongType)[0].error).toContain('requires a state-manager node');
    expect(h.responsesFor(unknown)[0].error).toContain('outside the current workflow');
    expect(socket.hasSent('workflow:state:get')).toBe(false);
  });

  it('does not treat collaborator pseudo-nodes as SDK targets', () => {
    h = mountBridge({ nodes: [testNode('collab', {}, 'collaborator-cursor')] });
    const id = h.sendRequest('nodes.getConfig', { nodeId: 'collab' });
    expect(h.responsesFor(id)[0].error).toContain('outside the current workflow');
  });

  it('uses a read-only allowlist that excludes credential and resource discovery', () => {
    h = mountBridge({ readOnly: true, nodes: [testNode('inside', { config: { ok: true } })] });
    const credentials = h.sendRequest('auth.listCredentials');
    const resources = h.sendRequest('resources.list');
    const config = h.sendRequest('nodes.getConfig', { nodeId: 'inside' });

    expect(h.responsesFor(credentials)[0].error).toContain('not available in read-only replay');
    expect(h.responsesFor(resources)[0].error).toContain('not available in read-only replay');
    expect(h.responsesFor(config)[0].result).toEqual({ ok: true });
    expect(socket.hasSent('credential:list')).toBe(false);
    expect(socket.hasSent('resource:list')).toBe(false);
  });

  it('drops realtime events for IDs outside the mounted workflow', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('inside')] });
    h.serverEmit('workflow:node:output', {
      workflow_id: 'wf-1', node_id: 'outside', output: { secret: true },
    });
    h.serverEmit('workflow:node:state', {
      workflow_id: 'wf-1', node_id: 'outside', state: 'running',
    });

    expect(h.events('node:output')).toEqual([]);
    expect(h.events('node:state')).toEqual([]);
  });
});
