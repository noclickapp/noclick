// Execution: run nodes and track output.

import { requestStream, send, request, subscribe, type ExecutionStream } from './transport.js';

export type NodeRef = string | { id: string; config: Record<string, unknown> };

function serializeNodeRefs(refs: NodeRef[]): Array<{ id: string; config?: Record<string, unknown> }> {
  return refs.map(ref =>
    typeof ref === 'string' ? { id: ref } : ref
  );
}

/**
 * Run nodes and stream output as each target node completes.
 * @param runNodes - Nodes to execute (string ID or { id, config } with temporary overrides).
 * @param targetNodes - Node IDs whose output we want to observe.
 * @returns A stream that fires 'output', 'error', and 'done' events.
 */
export function runNodesAndGetOutput(runNodes: NodeRef[], targetNodes: string[]): ExecutionStream {
  return requestStream('execution.runNodesAndGetOutput', {
    runNodes: serializeNodeRefs(runNodes),
    targetNodes,
  });
}

/**
 * Run nodes in the background (fire and forget).
 * @param runNodes - Nodes to execute (string ID or { id, config } with temporary overrides).
 */
export function runNodesInBackground(runNodes: NodeRef[]): void {
  send('execution.runNodesInBackground', {
    runNodes: serializeNodeRefs(runNodes),
  });
}

/** Stop the currently running execution. */
export function stop(): Promise<void> {
  return request('execution.stop');
}

/** Subscribe to a node's execution state changes. Returns unsubscribe function. */
export function onNodeState(
  nodeId: string,
  handler: (state: 'idle' | 'running' | 'completed' | 'error') => void
): () => void {
  return subscribe('node:state', (data: unknown) => {
    const d = data as { nodeId: string; state: string };
    if (d.nodeId === nodeId) handler(d.state as 'idle' | 'running' | 'completed' | 'error');
  });
}

/** Subscribe to a node's output as it arrives (e.g., streaming LLM tokens). Returns unsubscribe function. */
export function onNodeOutput(
  nodeId: string,
  handler: (output: unknown) => void
): () => void {
  return subscribe('node:output', (data: unknown) => {
    const d = data as { nodeId: string; output: unknown };
    if (d.nodeId === nodeId) handler(d.output);
  });
}
