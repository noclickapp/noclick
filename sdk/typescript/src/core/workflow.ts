// Workflow info and context.

import { request } from './transport.js';

export interface WorkflowInfo {
  id: string;
  name: string;
  nodeCount: number;
}

/** The current component's node ID. Set by the host at init time. */
export let nodeId: string = '';

/** Get info about the current workflow. */
export function getInfo(): Promise<WorkflowInfo> {
  return request('workflow.getInfo');
}

/** @internal Called by the SDK init to set the node ID from host context. */
export function _setNodeId(id: string): void {
  nodeId = id;
}
