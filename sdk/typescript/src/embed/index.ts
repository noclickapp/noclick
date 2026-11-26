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
import { setTransport, subscribe, isInitialized, getTransport } from './core/transport.js';
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
// In iframe context, React is available via the import map. The published npm
// package declares React as a required peer because this root entry point
// exports useInputs and therefore imports React at module evaluation time.
export { onInputsChanged } from './inputs.js';
export { useInputs } from './react.js';

export interface InitOptions {
  /**
   * Transport to use. Defaults to 'postmessage' (for iframe components), or to 'http' when an apiKey is given.
   * 'http' (apiKey + workflowId) is for a page outside NoClick: the calls go to the platform API.
   * Pass a Transport instance for fully custom transports.
   */
  transport?: 'postmessage' | 'http' | import('./core/transport.js').Transport;
  /** NoClick API URL for 'http' (default 'https://api.noclick.com'). */
  url?: string;
  /** API key for authentication (required for 'http' transport). */
  apiKey?: string;
  /** Workflow ID to scope operations to. */
  workflowId?: string;
  /** Node ID of the custom component (set automatically in iframe context). */
  nodeId?: string;
}

/**
 * Initialize the SDK. Must be called before using any API.
 *
 * Iframe (automatic):
 *   Auto-initializes with postMessage when running inside an iframe.
 *
 * External app:
 *   import { init } from 'noclick/embed';
 *   await init({ transport: 'http', apiKey: 'nk_live_...', workflowId: '...' });
 */
export async function init(options: InitOptions = {}): Promise<void> {
  // Auto-detect transport: if apiKey is provided, use http; otherwise postmessage (iframe)
  const { transport = options.apiKey ? 'http' : 'postmessage', nodeId } = options;

  if (typeof transport === 'string') {
    switch (transport) {
      case 'postmessage':
        setTransport(new PostMessageTransport());
        break;
      case 'http': {
        if (!options.apiKey || !options.workflowId) {
          throw new Error("HTTP transport requires 'apiKey' and 'workflowId' options.");
        }
        const { HttpTransport } = await import('./transports/http.js');
        const http = new HttpTransport({ url: options.url, apiKey: options.apiKey, workflowId: options.workflowId });
        setTransport(http);
        await http.connect();
        break;
      }
      default:
        throw new Error(`Unknown transport: ${transport}. Use 'postmessage', 'http', or pass a Transport instance.`);
    }
  } else {
    setTransport(transport);
  }

  if (nodeId) _setNodeId(nodeId);
}

// Listen for init event from host (sets node ID and initial context).
// Registered before the ready signal below so the host's reply can't be missed.
subscribe('init', (data: unknown) => {
  const d = data as { nodeId?: string };
  if (d.nodeId) _setNodeId(d.nodeId);
});

// Auto-initialize with postMessage transport when running in a browser iframe context.
// External apps should call init() explicitly with their transport config.
if (typeof window !== 'undefined' && window.parent !== window) {
  init({ transport: 'postmessage' }).then(() => {
    // Signal readiness so the host (re)sends init even if our subscribe() above
    // registered after the host's load-time init fired — a load-ordering race that
    // otherwise leaves workflow.nodeId empty for the life of the component.
    try { getTransport().send({ type: 'noclick:ready' }); } catch { /* transport not ready */ }
  });
}
