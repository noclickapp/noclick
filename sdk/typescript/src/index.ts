// @noclick/sdk — main entry point.
// Initialize with init(), then use the API modules.

import * as nodes from './core/nodes.js';
import * as execution from './core/execution.js';
import * as state from './core/state.js';
import * as auth from './core/auth.js';
import * as workflow from './core/workflow.js';
import * as resources from './core/resources.js';
import * as dataset from './core/dataset.js';
import { _setNodeId } from './core/workflow.js';
import { setTransport, subscribe, isInitialized } from './core/transport.js';
import { PostMessageTransport } from './transports/postmessage.js';

export { nodes, execution, state, auth, workflow, resources, dataset };
export type { ExecutionStream } from './core/transport.js';
export type { NodeRef } from './core/execution.js';
export type { NodeInfo } from './core/nodes.js';
export type { CredentialInfo } from './core/auth.js';
export type { WorkflowInfo } from './core/workflow.js';
export type { ResourceInfo, UploadResult } from './core/resources.js';
export type { DatasetRow, DatasetPage, DatasetInfo } from './core/dataset.js';
export type { Transport } from './core/transport.js';

// Input subscriptions — both framework-agnostic and React hook.
// In iframe context, React is always available via import map.
// For external apps without React, useInputs will be tree-shaken by bundlers
// since React is marked as an external/optional peer dep.
export { onInputsChanged } from './inputs.js';
export { useInputs } from './react.js';

export interface InitOptions {
  /**
   * Transport to use. Defaults to 'postmessage' (for iframe components).
   * Pass a Transport instance for custom transports (e.g., WebSocket).
   */
  transport?: 'postmessage' | import('./core/transport.js').Transport;
  /** Node ID of the custom component (set automatically in iframe context). */
  nodeId?: string;
}

/**
 * Initialize the SDK. Must be called before using any API.
 * In iframe context (custom components), this is called automatically.
 */
export function init(options: InitOptions = {}): void {
  const { transport = 'postmessage', nodeId } = options;

  if (typeof transport === 'string') {
    switch (transport) {
      case 'postmessage':
        setTransport(new PostMessageTransport());
        break;
      default:
        throw new Error(`Unknown transport: ${transport}. Pass a Transport instance for custom transports.`);
    }
  } else {
    setTransport(transport);
  }

  if (nodeId) _setNodeId(nodeId);
}

// Auto-initialize with postMessage transport when running in a browser iframe context.
// External apps should call init() explicitly with their transport config.
if (typeof window !== 'undefined' && window.parent !== window) {
  init({ transport: 'postmessage' });
}

// Listen for init event from host (sets node ID and initial context)
subscribe('init', (data: unknown) => {
  const d = data as { nodeId?: string };
  if (d.nodeId) _setNodeId(d.nodeId);
});
