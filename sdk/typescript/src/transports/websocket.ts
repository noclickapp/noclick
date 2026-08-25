// WebSocket transport for external apps via Socket.IO.
// Connects directly to the NoClick backend using an API key.

import type { Transport } from '../core/transport.js';

interface WebSocketTransportOptions {
  /** NoClick backend URL (e.g. 'https://api.noclick.io' or 'http://localhost:8005') */
  url: string;
  /** API key for authentication (format: nk_live_...) */
  apiKey: string;
  /** Workflow ID to scope operations to (optional — uses key's default scope if not set) */
  workflowId?: string;
}

// Normalize backend responses to match postMessage bridge contracts
// Normalize backend responses to match postMessage bridge contracts.
// Second arg (params) provides the original request params when needed.
const responseTransforms: Record<string, (data: any, params?: Record<string, unknown>) => any> = {
  'state.get': (data) => data?.value,
  'state.keys': (data) => data?.keys ?? [],
  'nodes.getConfig': (data) => data?.config ?? data,
  // nodes.list is handled as a two-step special case in send() (needs node outputs
  // for hasOutput), so it has no response transform here.
  'nodes.getOutput': (data) => {
    // Backend returns { outputs: { nodeId: output } } or similar
    if (data?.outputs) {
      const values = Object.values(data.outputs);
      return values[0] ?? null;
    }
    return data;
  },
  'auth.listCredentials': (data) => {
    // Backend returns { credentials: [...] }, SDK expects CredentialInfo[]
    return (data?.credentials ?? []).map((c: any) => ({
      id: c.id,
      type: c.credential_type,
      name: c.name,
    }));
  },
  'auth.hasCredential': (data, params) => {
    // Backend returns credential list; SDK expects boolean
    const credType = params?.credentialType as string;
    return (data?.credentials ?? []).some((c: any) => c.credential_type === credType);
  },
  'auth.createCredential': (data) => {
    // Backend returns { success, credential: { id, credential_type, name } }
    const c = data?.credential;
    if (!c) return null;
    return { id: c.id, type: c.credential_type, name: c.name };
  },
  'workflow.getInfo': (data) => {
    // Backend returns { workflow: { id, name, workflow_data: { nodes } } }
    const wf = data?.workflow ?? data;
    const nodeList = wf?.workflow_data?.nodes ?? wf?.nodes ?? [];
    return { id: wf?.id, name: wf?.name, nodeCount: nodeList.length };
  },
  'resources.list': (data) => {
    // Backend returns { resources: [...] } with snake_case fields; map to ResourceInfo
    // (camelCase) so the result matches the postMessage bridge + the SDK type.
    return (data?.resources ?? []).map((r: any) => ({
      id: r.id,
      name: r.name,
      resourceType: r.resource_type,
      mimeType: r.mime_type,
      sizeBytes: r.size_bytes,
    }));
  },
  // resources.upload is a two-step special case in send() (create + presigned URL),
  // so it has no response transform here.
  'dataset.create': (data) => {
    // Backend returns { success, resource: { id, ... } }; SDK expects just the ID string
    return data?.resource?.id ?? data?.id;
  },
  'dataset.list': (data) => {
    // Backend returns { resources: [...] }; map to DatasetInfo { id, name, rowCount }
    // to match the postMessage bridge + the SDK type (was returning {type} / no rowCount).
    return (data?.resources ?? []).map((r: any) => ({
      id: r.id,
      name: r.name,
      rowCount: r.metadata?.row_count ?? 0,
    }));
  },
  'resources.getUrl': (data) => data?.url ?? data?.download_url ?? data,
  'dataset.getRows': (data) => data,
  'dataset.appendRows': (data) => data,
  'dataset.updateRow': (data) => data,
  'dataset.deleteRows': (data) => data,
};

/**
 * Socket.IO transport for external SDK connections.
 *
 * Requires the `socket.io-client` package:
 *   npm install socket.io-client
 *
 * Usage:
 *   import { init } from '@noclick/sdk';
 *   import { WebSocketTransport } from '@noclick/sdk/transports/websocket';
 *
 *   init({
 *     transport: new WebSocketTransport({
 *       url: 'http://localhost:8005',
 *       apiKey: 'nk_live_...',
 *       workflowId: '...',
 *     })
 *   });
 */
export class WebSocketTransport implements Transport {
  private socket: any = null; // socket.io-client Socket
  private handlers = new Set<(msg: any) => void>();
  private options: WebSocketTransportOptions;
  // Track pending streams: requestId → { targetNodes, completed, latestOutput }
  private pendingStreams = new Map<string, { targetNodes: string[]; completed: Set<string>; latestOutput?: Record<string, unknown> }>();
  // Track which method + params each request ID maps to (for response transforms)
  private _requestMethods = new Map<string, { method: string; params: Record<string, unknown> }>();

  // Event map: SDK method → { socket event name, param transform }
  private eventMap: Record<string, { event: string; transform: (p: Record<string, unknown>) => Record<string, unknown> }>;
  // Cached connection promise to prevent duplicate socket creation from concurrent send() calls
  private _connectPromise: Promise<void> | null = null;

  constructor(options: WebSocketTransportOptions) {
    this.options = options;
    this.eventMap = this._buildEventMap();
  }

  private _buildEventMap() {
    return {
      // Nodes
      'nodes.getOutput': {
        event: 'workflow:get_node_outputs',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          node_ids: [p.nodeId],
        }),
      },
      'nodes.setConfig': {
        event: 'workflow:node:set_config',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          node_id: p.nodeId,
          config: p.config,
        }),
      },
      'nodes.getConfig': {
        event: 'workflow:node:get_config',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          node_id: p.nodeId,
        }),
      },

      // Execution
      'execution.runNodesInBackground': {
        event: 'workflow:execute',
        transform: (p: Record<string, unknown>) => {
          const runNodes = p.runNodes as Array<{ id: string; config?: Record<string, unknown> }>;
          const configOverrides: Record<string, Record<string, unknown>> = {};
          for (const ref of runNodes) {
            if (ref.config) configOverrides[ref.id] = ref.config;
          }
          return {
            workflow_id: this.options.workflowId,
            start_node_id: runNodes[0]?.id,
            ...(Object.keys(configOverrides).length > 0 && { config_overrides: configOverrides }),
          };
        },
      },

      // State
      'state.get': {
        event: 'workflow:state:get',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          key: p.key,
          ...(p.node && { node_id: p.node }),
        }),
      },
      'state.set': {
        event: 'workflow:state:set',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          key: p.key,
          value: p.value,
          ...(p.node && { node_id: p.node }),
        }),
      },
      'state.delete': {
        event: 'workflow:state:set',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          key: p.key,
          value: null,
          ...(p.node && { node_id: p.node }),
        }),
      },
      'state.keys': {
        event: 'workflow:state:keys',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          ...(p.node && { node_id: p.node }),
        }),
      },

      // Workflow
      'workflow.getInfo': {
        event: 'workflow:get',
        transform: () => ({
          workflow_id: this.options.workflowId,
        }),
      },

      // Credentials
      'auth.listCredentials': {
        event: 'credential:list',
        transform: () => ({}),
      },
      'auth.hasCredential': {
        event: 'credential:list',
        transform: () => ({}),
      },
      'auth.createCredential': {
        event: 'credential:create',
        transform: (p: Record<string, unknown>) => ({
          credential_type: p.credentialType,
          credential_data: p.data,
          name: p.name,
        }),
      },

      // Resources
      'resources.list': {
        event: 'resource:list',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          resource_type: p.resourceType,
        }),
      },
      'resources.getUrl': {
        event: 'resource:download_url',
        transform: (p: Record<string, unknown>) => ({
          resource_id: p.resourceId,
        }),
      },
      'resources.remove': {
        event: 'resource:delete',
        transform: (p: Record<string, unknown>) => ({
          resource_id: p.resourceId,
        }),
      },

      // Dataset
      'dataset.create': {
        event: 'resource:create',
        transform: (p: Record<string, unknown>) => ({
          workflow_id: this.options.workflowId,
          resource_type: 'dataset',
          name: p.name,
        }),
      },
      'dataset.getRows': {
        event: 'resource:dataset:rows',
        transform: (p: Record<string, unknown>) => ({
          resource_id: p.resourceId,
          limit: p.limit || 100,
          offset: p.offset || 0,
        }),
      },
      'dataset.appendRows': {
        event: 'resource:dataset:append',
        transform: (p: Record<string, unknown>) => ({
          resource_id: p.resourceId,
          rows: p.rows,
        }),
      },
      'dataset.updateRow': {
        event: 'resource:dataset:update_row',
        transform: (p: Record<string, unknown>) => ({
          resource_id: p.resourceId,
          row_id: p.rowId,
          data: p.data,
        }),
      },
      'dataset.deleteRows': {
        event: 'resource:dataset:delete_rows',
        transform: (p: Record<string, unknown>) => ({
          resource_id: p.resourceId,
          row_ids: p.rowIds,
        }),
      },
      'dataset.list': {
        event: 'resource:list',
        transform: () => ({
          workflow_id: this.options.workflowId,
          resource_type: 'dataset',
        }),
      },
    };
  }

  /** Connect to the backend. Called automatically on first send(). */
  async connect(): Promise<void> {
    if (this.socket?.connected) return;
    // If socket exists but is disconnected, let socket.io's built-in reconnection handle it
    // (don't create a duplicate socket that orphans the old one's event listeners)
    if (this.socket) return;
    // Return existing connection attempt if one is in progress (prevents duplicate sockets)
    if (this._connectPromise) return this._connectPromise;
    this._connectPromise = this._doConnect();
    try {
      await this._connectPromise;
    } finally {
      this._connectPromise = null;
    }
  }

  private async _doConnect(): Promise<void> {

    // Dynamic import of socket.io-client to avoid bundling it in the iframe SDK
    const { io } = await import('socket.io-client');

    return new Promise((resolve, reject) => {
      this.socket = io(this.options.url, {
        auth: {
          api_key: this.options.apiKey,
        },
        transports: ['websocket'],
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
      });

      this.socket.on('connect', () => {
        resolve();
      });

      this.socket.on('connect_error', (err: Error) => {
        reject(new Error(`SDK connection failed: ${err.message}`));
      });

      // On disconnect, reject all pending requests and streams so promises don't hang
      this.socket.on('disconnect', () => {
        const error = 'WebSocket disconnected';
        for (const [reqId] of this._requestMethods) {
          this.handlers.forEach(fn => fn({ type: 'noclick:response', id: reqId, error }));
        }
        for (const [reqId, stream] of this.pendingStreams) {
          // Send error with a nodeId so transport.ts processes it (rejects the stream promise)
          const firstTarget = stream.targetNodes[0] || 'unknown';
          this.handlers.forEach(fn => fn({ type: 'noclick:stream', id: reqId, event: 'error', nodeId: firstTarget, data: error }));
        }
        this._requestMethods.clear();
        this.pendingStreams.clear();
      });

      // Forward ALL response events as noclick:response messages.
      // The core transport layer handles request ID matching via its pending map.
      this.socket.on('response', (data: any) => {
        if (!data?.request_id) return;

        // Execution error responses arrive with 'exec-' prefixed request_id.
        // Forward as stream error so the core transport can reject the all() promise.
        if (data.error && typeof data.request_id === 'string' && data.request_id.startsWith('exec-')) {
          const coreReqId = data.request_id.slice(5); // strip 'exec-' prefix
          const stream = this.pendingStreams.get(coreReqId);
          if (stream) {
            const errorMsg = typeof data.error === 'string' ? data.error : JSON.stringify(data.error);
            const firstTarget = stream.targetNodes[0] || 'unknown';
            this.handlers.forEach(fn => fn({ type: 'noclick:stream', id: coreReqId, event: 'error', nodeId: firstTarget, data: errorMsg }));
            this.pendingStreams.delete(coreReqId);
            return;
          }
        }

        if (data.error) {
          this._requestMethods.delete(data.request_id);
          this.handlers.forEach(fn => fn({
            type: 'noclick:response',
            id: data.request_id,
            error: typeof data.error === 'string' ? data.error : JSON.stringify(data.error),
          }));
        } else {
          let result = data.data ?? data;
          const tracked = this._requestMethods.get(data.request_id);
          if (tracked) {
            this._requestMethods.delete(data.request_id);
            const transform = responseTransforms[tracked.method];
            if (transform) {
              result = transform(result, tracked.params);
            }
            // Emit state:changed events so onChange subscribers are notified
            if (tracked.method === 'state.set' || tracked.method === 'state.delete') {
              const key = tracked.params.key as string;
              const value = tracked.method === 'state.delete' ? undefined : tracked.params.value;
              this.handlers.forEach(fn => fn({
                type: 'noclick:event',
                event: 'state:changed',
                data: { key, value },
              }));
            }
          }
          this.handlers.forEach(fn => fn({
            type: 'noclick:response',
            id: data.request_id,
            result,
          }));
        }
      });

      // Forward workflow execution events
      this.socket.on('workflow:node:output', (data: any) => {
        // General push event for onNodeOutput subscribers
        this.handlers.forEach(fn => fn({
          type: 'noclick:event',
          event: 'node:output',
          data: { nodeId: data.node_id, output: data.output },
        }));

        // Forward as stream events for pending runNodesAndGetOutput requests.
        // Don't mark completed here — wait for workflow:node:state 'completed'.
        for (const [reqId, stream] of this.pendingStreams) {
          if (stream.targetNodes.includes(data.node_id)) {
            // Store latest output for this node
            stream.latestOutput = stream.latestOutput || {};
            stream.latestOutput[data.node_id] = data.output;
            this.handlers.forEach(fn => fn({
              type: 'noclick:stream',
              id: reqId,
              event: 'output',
              nodeId: data.node_id,
              data: data.output,
            }));
          }
        }
      });

      this.socket.on('workflow:node:state', (data: any) => {
        // General push event
        this.handlers.forEach(fn => fn({
          type: 'noclick:event',
          event: 'node:state',
          data: { nodeId: data.node_id, state: data.state },
        }));

        // Check stream completion or error. 'skipped' is terminal too (a target
        // node that didn't run) — without it the stream would hang until timeout,
        // diverging from the postMessage bridge which treats skipped as complete.
        if (data.state === 'completed' || data.state === 'error' || data.state === 'skipped') {
          for (const [reqId, stream] of this.pendingStreams) {
            if (stream.targetNodes.includes(data.node_id)) {
              if (data.state === 'error') {
                // Node errored — reject the stream immediately
                this.handlers.forEach(fn => fn({
                  type: 'noclick:stream',
                  id: reqId,
                  event: 'error',
                  nodeId: data.node_id,
                  data: data.error || `Node ${data.node_id} failed`,
                }));
                this.pendingStreams.delete(reqId);
              } else {
                stream.completed.add(data.node_id);
                if (stream.targetNodes.every(t => stream.completed.has(t))) {
                  this.handlers.forEach(fn => fn({
                    type: 'noclick:stream',
                    id: reqId,
                    event: 'done',
                  }));
                  this.pendingStreams.delete(reqId);
                }
              }
            }
          }
        }
      });

      this.socket.on('workflow:complete', (data: any) => {
        this.handlers.forEach(fn => fn({
          type: 'noclick:event',
          event: 'workflow:complete',
          data,
        }));
      });

      // Forward cross-client state change notifications
      this.socket.on('state:changed', (data: any) => {
        this.handlers.forEach(fn => fn({
          type: 'noclick:event',
          event: 'state:changed',
          data,
        }));
      });
    });
  }

  /**
   * Send an SDK request by translating it to a Socket.IO event.
   * The noclick:request is mapped to the appropriate socket event.
   */
  send(msg: Record<string, unknown>): void {
    if (!this.socket?.connected) {
      if (this.socket) {
        // Socket exists but not yet connected — initial handshake or socket.io
        // reconnection in flight. Wait for the actual 'connect' event instead of
        // calling connect().then(...) which can resolve before the socket opens
        // (connect() returns early at `if (this.socket) return`). That .then-retry
        // pattern can starve the event loop in a microtask spin if send() is
        // called from a useEffect that fires before the handshake completes.
        this.socket.once('connect', () => this.send(msg));
        return;
      }
      // No socket yet — kick off connection.
      this.connect().then(() => this.send(msg)).catch(console.error);
      return;
    }

    // Handle fire-and-forget messages
    if (msg.type === 'noclick:fire') {
      const method = msg.method as string;
      const params = msg.params as Record<string, unknown>;
      const mapping = this.eventMap[method];
      if (mapping) {
        this.socket.emit(mapping.event, mapping.transform(params));
      }
      return;
    }

    if (msg.type !== 'noclick:request') return;

    const method = msg.method as string;
    const params = msg.params as Record<string, unknown>;
    const requestId = msg.id as string;

    // auth.requestCredential requires browser OAuth popup — not supported in WebSocket transport
    if (method === 'auth.requestCredential') {
      this.handlers.forEach(fn => fn({
        type: 'noclick:response', id: requestId,
        error: 'auth.requestCredential (OAuth flow) is not supported by the WebSocket transport. Use auth.createCredential for API key credentials, or pre-configure OAuth credentials in the workflow editor.',
      }));
      return;
    }

    // execution.stop is fire-and-forget on the backend (no response sent)
    if (method === 'execution.stop') {
      this.socket.emit('workflow:stop', {
        workflow_id: this.options.workflowId,
      });
      this.handlers.forEach(fn => fn({ type: 'noclick:response', id: requestId, result: null }));
      return;
    }

    // Special handling for streaming methods
    if (method === 'execution.runNodesAndGetOutput') {
      const runNodes = params.runNodes as Array<{ id: string; config?: Record<string, unknown> }>;
      const targetNodes = params.targetNodes as string[];

      // Register stream targets
      this.pendingStreams.set(requestId, { targetNodes, completed: new Set() });

      // Build config_overrides from NodeRef objects with inline config
      const configOverrides: Record<string, Record<string, unknown>> = {};
      for (const ref of runNodes) {
        if (ref.config) configOverrides[ref.id] = ref.config;
      }

      // Emit workflow:execute
      this.socket.emit('workflow:execute', {
        workflow_id: this.options.workflowId,
        start_node_id: runNodes[0]?.id,
        request_id: `exec-${requestId}`,
        ...(Object.keys(configOverrides).length > 0 && { config_overrides: configOverrides }),
      });
      return; // Don't go through the normal event map
    }

    // resources.upload is two backend calls (the single eventMap mapping returned an
    // undefined uploadUrl — resource:create doesn't issue the presigned URL).
    if (method === 'resources.upload') {
      const p = params as any;
      (async () => {
        try {
          const created = await this._emitAndWait('resource:create', {
            workflow_id: this.options.workflowId,
            resource_type: p.resourceType || 'file',
            name: p.name,
            mime_type: p.mimeType,
            size_bytes: p.sizeBytes,
          });
          const resourceId = created?.resource?.id;
          if (!resourceId) throw new Error('Failed to create resource');
          const up = await this._emitAndWait('resource:upload_url', {
            resource_id: resourceId,
            filename: p.name,
            content_type: p.mimeType,
          });
          this.handlers.forEach(fn => fn({ type: 'noclick:response', id: requestId, result: { resourceId, uploadUrl: up?.upload_url } }));
        } catch (e) {
          this.handlers.forEach(fn => fn({ type: 'noclick:response', id: requestId, error: e instanceof Error ? e.message : 'Upload failed' }));
        }
      })();
      return;
    }

    // nodes.list needs the graph AND the node outputs to populate hasOutput
    // (workflow:get doesn't carry outputs — they live in the CAS).
    if (method === 'nodes.list') {
      (async () => {
        try {
          const wfResp = await this._emitAndWait('workflow:get', { workflow_id: this.options.workflowId });
          const wf = wfResp?.workflow ?? wfResp;
          const nodeList = wf?.workflow_data?.nodes ?? wf?.nodes ?? [];
          let outputs: Record<string, unknown> = {};
          try {
            const outResp = await this._emitAndWait('workflow:get_node_outputs', { workflow_id: this.options.workflowId });
            outputs = outResp?.outputs ?? {};
          } catch { /* hasOutput is best-effort enrichment; the node list still resolves */ }
          const result = nodeList
            .filter((n: any) => n.type && !n.type.startsWith('collaborator'))
            .map((n: any) => ({
              id: n.id,
              type: n.type || 'unknown',
              label: n.config?.label || n.type || 'unknown',
              hasOutput: n.id in outputs,
            }));
          this.handlers.forEach(fn => fn({ type: 'noclick:response', id: requestId, result }));
        } catch (e) {
          this.handlers.forEach(fn => fn({ type: 'noclick:response', id: requestId, error: e instanceof Error ? e.message : 'Failed to list nodes' }));
        }
      })();
      return;
    }

    // Track method + params for response transforms
    this._requestMethods.set(requestId, { method, params });

    const mapping = this.eventMap[method];
    if (!mapping) {
      this._requestMethods.delete(requestId);
      // Unknown method — respond with error
      this.handlers.forEach(fn => fn({
        type: 'noclick:response',
        id: requestId,
        error: `Method '${method}' not supported in WebSocket transport`,
      }));
      return;
    }

    const payload = {
      ...mapping.transform(params),
      request_id: requestId,
    };

    this.socket.emit(mapping.event, payload);
  }

  /** Emit one backend event and resolve with its response data — for methods that
   *  need multiple backend calls (resources.upload, nodes.list). Uses an internal
   *  request id the SDK core doesn't know about (the global 'response' handler
   *  forwards it harmlessly; the core ignores the unknown id). */
  private _internalSeq = 0;
  private _emitAndWait(event: string, payload: Record<string, unknown>): Promise<any> {
    const reqId = `int-${++this._internalSeq}-${Date.now().toString(36)}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.socket?.off('response', onResp);
        reject(new Error(`SDK request '${event}' timed out`));
      }, 30000);
      const onResp = (data: any) => {
        if (data?.request_id !== reqId) return;
        this.socket?.off('response', onResp);
        clearTimeout(timer);
        if (data.error) reject(new Error(typeof data.error === 'string' ? data.error : JSON.stringify(data.error)));
        else resolve(data.data ?? data);
      };
      this.socket.on('response', onResp);
      this.socket.emit(event, { ...payload, request_id: reqId });
    });
  }

  onMessage(handler: (msg: any) => void): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  destroy(): void {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
    this._requestMethods.clear();
    this.pendingStreams.clear();
    this.handlers.clear();
  }
}
