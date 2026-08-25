// @vitest-environment jsdom
// Scenario (b): live execution. Backend node:output / node:state socket events must
// reach the iframe as SDK push events (node:output, node:state, inputs:changed).
import { afterEach, describe, expect, it } from 'vitest';
import { mountBridge, testNode } from './helpers/mountBridge';

let h: ReturnType<typeof mountBridge>;
afterEach(() => h?.cleanup());

describe('SDK bridge — realtime output delivery', () => {
  it('forwards workflow:node:output as a node:output push event', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('gen')] });
    h.serverEmit('workflow:node:output', { workflow_id: 'wf-1', node_id: 'gen', output: { tokens: 'hi' } });
    expect(h.events('node:output')).toContainEqual({
      type: 'noclick:event', event: 'node:output', data: { nodeId: 'gen', output: { tokens: 'hi' } },
    });
  });

  it('surfaces an UPSTREAM node output as inputs:changed so useInputs() reacts', () => {
    h = mountBridge({
      workflowId: 'wf-1',
      nodes: [testNode('gen')],
      edges: [{ source: 'gen', target: 'component-1' }],
    });
    h.serverEmit('workflow:node:output', { workflow_id: 'wf-1', node_id: 'gen', output: 42 });
    expect(h.events('inputs:changed')).toContainEqual({
      type: 'noclick:event', event: 'inputs:changed', data: { gen: 42 },
    });
  });

  it('does NOT surface a non-upstream node output as an input (scoped to wired edges)', () => {
    h = mountBridge({
      workflowId: 'wf-1',
      nodes: [testNode('gen'), testNode('other')],
      edges: [{ source: 'gen', target: 'component-1' }],
    });
    // 'other' is not wired into this component → its output is not an input...
    h.serverEmit('workflow:node:output', { workflow_id: 'wf-1', node_id: 'other', output: 99 });
    expect(h.events('inputs:changed')).toEqual([]);
    // ...but it's still delivered as a general node:output push (SDK filters by id).
    expect(h.events('node:output')).toContainEqual({
      type: 'noclick:event', event: 'node:output', data: { nodeId: 'other', output: 99 },
    });
  });

  it('forwards node state transitions as node:state push events', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('gen')] });
    h.serverEmit('workflow:node:state', { workflow_id: 'wf-1', node_id: 'gen', state: 'running' });
    expect(h.events('node:state')).toContainEqual({
      type: 'noclick:event', event: 'node:state', data: { nodeId: 'gen', state: 'running' },
    });
  });

  it('responds to a ready signal by (re)sending init (load-ordering race guard)', () => {
    h = mountBridge({ workflowId: 'wf-1', nodes: [testNode('gen')] });
    h.sendRaw({ type: 'noclick:ready' });
    expect(h.events('init')).toContainEqual({
      type: 'noclick:event', event: 'init', data: { nodeId: 'component-1' },
    });
  });

  it('ignores events scoped to a different workflow', () => {
    h = mountBridge({ workflowId: 'wf-1' });
    h.serverEmit('workflow:node:output', { workflow_id: 'wf-OTHER', node_id: 'gen', output: 1 });
    h.serverEmit('workflow:node:state', { workflow_id: 'wf-OTHER', node_id: 'gen', state: 'running' });
    expect(h.events('node:output')).toEqual([]);
    expect(h.events('node:state')).toEqual([]);
  });
});
