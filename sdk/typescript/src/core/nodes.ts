// Node operations: read/write any node's output or config.

import { request } from './transport.js';

export interface NodeInfo {
  id: string;
  type: string;
  label: string;
  hasOutput: boolean;
}

/** Read a node's last output (may be from any previous run). */
export function getOutput(nodeId: string): Promise<unknown> {
  return request('nodes.getOutput', { nodeId });
}

/** Read a node's config. */
export function getConfig(nodeId: string): Promise<Record<string, unknown>> {
  return request('nodes.getConfig', { nodeId });
}

/** Set config fields on a node (merges with existing config). */
export function setConfig(nodeId: string, config: Record<string, unknown>): Promise<void> {
  return request('nodes.setConfig', { nodeId, config });
}

/** List all nodes in the workflow. */
export function list(): Promise<NodeInfo[]> {
  return request('nodes.list');
}
