// @vitest-environment jsdom
// Scenario (c): execute and wait. runNodesAndGetOutput triggers a background run
// and resolves only when every target node reaches a terminal state. This is the
// host half of the completion logic the SDK's stream.all() depends on.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mountBridge } from './helpers/mountBridge';

let h: ReturnType<typeof mountBridge>;
afterEach(() => h?.cleanup());

describe('SDK bridge — execute and wait (runNodesAndGetOutput)', () => {
  it('triggers a background run, streams output, then signals done on completion', () => {
    h = mountBridge({ workflowId: 'wf-1' });
    const id = h.sendRequest('execution.runNodesAndGetOutput', { runNodes: [{ id: 'gen' }], targetNodes: ['gen'] });

    // Runs via the same custom event as the node hover "Run" pill, scoped background.
    expect(h.runFromNode).toContainEqual(expect.objectContaining({ nodeId: 'gen', background: true }));
    // No response is sent up front — the stream stays open.
    expect(h.responsesFor(id)).toEqual([]);

    h.serverEmit('workflow:node:output', { workflow_id: 'wf-1', node_id: 'gen', output: { answer: 42 } });
    expect(h.streamsFor(id)).toContainEqual({ type: 'noclick:stream', id, event: 'output', nodeId: 'gen', data: { answer: 42 } });

    h.serverEmit('workflow:node:state', { workflow_id: 'wf-1', node_id: 'gen', state: 'completed' });
    expect(h.streamsFor(id)).toContainEqual({ type: 'noclick:stream', id, event: 'done' });
  });

  it('signals done only after ALL target nodes complete', () => {
    h = mountBridge({ workflowId: 'wf-1' });
    const id = h.sendRequest('execution.runNodesAndGetOutput', { runNodes: [{ id: 'a' }], targetNodes: ['a', 'b'] });

    h.serverEmit('workflow:node:state', { workflow_id: 'wf-1', node_id: 'a', state: 'completed' });
    expect(h.streamsFor(id).some((m) => m.event === 'done')).toBe(false);

    h.serverEmit('workflow:node:state', { workflow_id: 'wf-1', node_id: 'b', state: 'completed' });
    expect(h.streamsFor(id)).toContainEqual({ type: 'noclick:stream', id, event: 'done' });
  });

  it('forwards a node failure as a stream error', () => {
    h = mountBridge({ workflowId: 'wf-1' });
    const id = h.sendRequest('execution.runNodesAndGetOutput', { runNodes: [{ id: 'gen' }], targetNodes: ['gen'] });
    h.serverEmit('workflow:node:state', { workflow_id: 'wf-1', node_id: 'gen', state: 'error', error: 'kaboom' });
    expect(h.streamsFor(id)).toContainEqual({ type: 'noclick:stream', id, event: 'error', nodeId: 'gen', data: 'kaboom' });
  });

  it('applies inline config overrides to the run-from-node trigger', () => {
    h = mountBridge({ workflowId: 'wf-1' });
    h.sendRequest('execution.runNodesAndGetOutput', { runNodes: [{ id: 'gen', config: { topic: 'cats' } }], targetNodes: ['gen'] });
    expect(h.runFromNode).toContainEqual(expect.objectContaining({
      nodeId: 'gen', background: true, configOverrides: { gen: { topic: 'cats' } },
    }));
  });

  it('runNodesInBackground fires a background run and sends no response', () => {
    h = mountBridge({ workflowId: 'wf-1' });
    h.sendFire('execution.runNodesInBackground', { runNodes: [{ id: 'gen' }] });
    expect(h.runFromNode).toContainEqual(expect.objectContaining({ nodeId: 'gen', background: true }));
    expect(h.posted().filter((m) => m.type === 'noclick:response')).toEqual([]);
  });

  it('times out and cleans up a stream whose target never reaches a terminal state', async () => {
    vi.useFakeTimers();
    try {
      h = mountBridge({ workflowId: 'wf-1' });
      const id = h.sendRequest('execution.runNodesAndGetOutput', { runNodes: [{ id: 'gen' }], targetNodes: ['gen'] });
      // No completion/error ever arrives (unreachable / stopped run).
      await vi.advanceTimersByTimeAsync(120000);
      expect(h.streamsFor(id)).toContainEqual(
        expect.objectContaining({ type: 'noclick:stream', id, event: 'error', data: 'Execution timed out' }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('execution.stop dispatches the stop-workflow event and acks', () => {
    h = mountBridge({ workflowId: 'wf-1' });
    const id = h.sendRequest('execution.stop');
    expect(h.stops()).toBe(1);
    expect(h.responsesFor(id)).toEqual([{ type: 'noclick:response', id, result: null }]);
  });
});
