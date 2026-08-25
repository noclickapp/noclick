// Host-side bridge for @noclick/sdk postMessage communication.
// Listens for SDK requests from custom component iframes and translates
// them into NoClick actions (ReactFlow state reads/writes, socket events, etc).

import { useEffect, useCallback, useRef } from 'react';
import type { Node } from '@xyflow/react';
import { onSocketEvent } from '~/lib/socket-receiver';
import { sendEventAsync } from '~/lib/socket-sender';
import { sdkDebugStore } from '~/lib/sdk-debug-store';
import { normalizeNodeUpdatePayload, updateNodeInList } from '~/lib/applyNodeUpdate';
import {
  isScopedNodeId,
  requireScopedNode,
  requireScopedNodeIds,
  requireScopedStateNode,
} from '~/lib/sdkBridgeScope';

interface SDKRequest {
  type: 'noclick:request';
  id: string;
  method: string;
  params: Record<string, unknown>;
}

interface SDKResponse {
  type: 'noclick:response';
  id: string;
  result?: unknown;
  error?: string;
}

interface SDKStreamEvent {
  type: 'noclick:stream';
  id: string;
  event: 'output' | 'error' | 'done';
  nodeId?: string;
  data?: unknown;
}

interface SDKPushEvent {
  type: 'noclick:event';
  event: string;
  data: unknown;
}

interface UseSDKBridgeParams {
  /** The iframe element ref */
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
  /** This component's node ID */
  nodeId: string;
  /** The current workflow ID */
  workflowId?: string;
  /** OAuth connect function from useCredentialOAuth */
  oauthConnect?: (provider: string, name: string, scopes?: string[]) => void;
  /** Callback when OAuth credential is created (resolve pending SDK request) */
  onOAuthCreated?: (callback: (credentialId: string, provider: string) => void) => void;
  /** Callback when an OAuth attempt is cancelled (popup closed) — resolves the SDK request as null */
  onOAuthCancelled?: (callback: () => void) => void;
  /** Optional node source override; replay canvases pass their read-only graph here. */
  getNodes?: () => Node[];
  /** Optional edge source override; used to scope useInputs to upstream nodes. */
  getEdges?: () => Array<{ source: string; target: string }>;
  /** Optional node update override; omitted in read-only/replay contexts. */
  updateNodeData?: (nodeId: string, data: Record<string, unknown>) => void;
  /** When true, SDK read calls work but mutating/executing calls are rejected. */
  readOnly?: boolean;
}

// Read-only/replay contexts are an allowlist, not a mutation denylist. That keeps a
// newly-added SDK method from silently exposing credentials, resources, or backend
// calls to author code on a public/template surface.
const READ_ONLY_ALLOWED_METHODS = new Set([
  'nodes.getOutput',
  'nodes.getConfig',
  'nodes.list',
  'state.get',
  'state.keys',
  'workflow.getInfo',
]);

/**
 * Find OAuth scopes for a credential type by searching all node JSON schemas.
 * Each schema's $defs contains credential definitions with:
 *   - properties.credential_type.const = 'google_gmail_oauth' (the credential type ID)
 *   - x-oauth-scopes = ['https://...'] (the required scopes)
 *   - x-oauth-provider = 'google' (the provider key)
 */
function findOAuthScopesForCredentialType(credentialType: string): { scopes: string[]; provider: string } | null {
  try {
    const { NODE_SCHEMAS } = require('~/utils/nodeSchemas');
    for (const schema of Object.values(NODE_SCHEMAS) as any[]) {
      const defs = schema?.$defs || schema?.definitions || {};
      for (const def of Object.values(defs) as any[]) {
        if (
          def?.['x-oauth-scopes'] &&
          def?.properties?.credential_type?.const === credentialType
        ) {
          return {
            scopes: def['x-oauth-scopes'],
            provider: def['x-oauth-provider'] || '',
          };
        }
      }
    }
  } catch { /* schema lookup unavailable */ }
  return null;
}

// Access workflow nodes via __workflowTest (works in all contexts: canvas, interface tab, fullscreen).
// __reactFlowInstance.getNodes() can be empty when the canvas is not the active tab.
function getWorkflowAccessor() {
  const wt = (window as any).__workflowTest;
  const rf = (window as any).__reactFlowInstance;
  return {
    getNodes: (): Node[] => wt?.getNodes?.() ?? rf?.getNodes?.() ?? [],
    getEdges: (): Array<{ source: string; target: string }> => wt?.getEdges?.() ?? rf?.getEdges?.() ?? [],
    /** Update a single node's data (works in all contexts via __workflowTest) */
    updateNodeData: (nodeId: string, data: Record<string, unknown>) => {
      if (wt?.updateNodeData) {
        wt.updateNodeData(nodeId, data);
      } else if (rf?.setNodes) {
        const update = normalizeNodeUpdatePayload(data as Record<string, any>);
        rf.setNodes((nodes: Node[]) => updateNodeInList(nodes, nodeId, update));
      }
    },
  };
}

/**
 * Bridges @noclick/sdk postMessage calls from an iframe to NoClick's
 * ReactFlow state, socket events, and workflow execution.
 */
export function useSDKBridge(params: UseSDKBridgeParams | null) {
  const iframeRef = params?.iframeRef ?? { current: null };
  const nodeId = params?.nodeId ?? '';
  const workflowId = params?.workflowId;
  const oauthConnect = params?.oauthConnect;
  const onOAuthCreated = params?.onOAuthCreated;
  const onOAuthCancelled = params?.onOAuthCancelled;
  const customGetNodes = params?.getNodes;
  const customGetEdges = params?.getEdges;
  const customUpdateNodeData = params?.updateNodeData;
  const readOnly = !!params?.readOnly;
  const disabled = params === null;
  const getNodes = useCallback(() => customGetNodes?.() ?? getWorkflowAccessor().getNodes(), [customGetNodes]);
  const getEdges = useCallback(() => customGetEdges?.() ?? getWorkflowAccessor().getEdges(), [customGetEdges]);
  // Node IDs wired into this component's input handle (edges targeting nodeId) — the
  // set whose outputs become this component's useInputs(). Computed fresh (edges change).
  const upstreamIds = useCallback(() => {
    const nodes = getNodes();
    return new Set(
      getEdges()
        .filter((edge) => edge.target === nodeId && isScopedNodeId(nodes, edge.source))
        .map((edge) => edge.source),
    );
  }, [getEdges, getNodes, nodeId]);
  const updateNodeData = useCallback((id: string, data: Record<string, unknown>) => {
    if (readOnly) return;
    if (customUpdateNodeData) {
      customUpdateNodeData(id, data);
      return;
    }
    getWorkflowAccessor().updateNodeData(id, data);
  }, [customUpdateNodeData, readOnly]);
  // Track pending stream requests for execution tracking
  const pendingStreams = useRef<Map<string, { targetNodes: string[]; executionId?: string; completed?: Set<string>; timer?: ReturnType<typeof setTimeout> }>>(new Map());

  // On unmount, drop any in-flight stream timers + entries so a component that
  // navigates away mid-run doesn't leak timers or map entries.
  useEffect(() => {
    const streams = pendingStreams.current;
    return () => { for (const [, s] of streams) if (s.timer) clearTimeout(s.timer); streams.clear(); };
  }, []);

  const postToIframe = useCallback((msg: SDKResponse | SDKStreamEvent | SDKPushEvent) => {
    // JSON round-trip to ensure data is structured-cloneable (strips proxies, circular refs, etc.)
    try {
      const clean = JSON.parse(JSON.stringify(msg));
      iframeRef.current?.contentWindow?.postMessage(clean, '*');
    } catch {
      // If serialization fails, send without result data
      iframeRef.current?.contentWindow?.postMessage(
        { ...msg, result: null, data: null, error: 'Data too large or not serializable' },
        '*'
      );
    }
  }, [iframeRef]);

  const respond = useCallback((reqId: string, result: unknown) => {
    postToIframe({ type: 'noclick:response', id: reqId, result });
    sdkDebugStore.endCall(reqId, result);
  }, [postToIframe]);

  const respondError = useCallback((reqId: string, error: string) => {
    postToIframe({ type: 'noclick:response', id: reqId, error });
    sdkDebugStore.errorCall(reqId, error);
  }, [postToIframe]);

  // Send init event when iframe loads
  useEffect(() => {
    if (disabled) return;
    const iframe = iframeRef.current;
    if (!iframe) return;
    const handleLoad = () => {
      postToIframe({ type: 'noclick:event', event: 'init', data: { nodeId } });

      // Seed useInputs() from restored outputs so a component isn't blank on first
      // paint until a node re-emits (the same load race as nodes.getOutput). The SDK
      // merges inputs:changed, so this initial snapshot accumulates with live events.
      if (!readOnly && workflowId) {
        sendEventAsync({
          event_name: 'workflow:get_node_outputs' as const,
          request_id: `sdk-init-inputs-${Date.now()}`,
          workflow_id: workflowId,
        } as any).then((resp: any) => {
          const outputs = resp?.outputs;
          if (!outputs) return;
          // Scope to this component's upstream nodes (not the whole graph).
          const ups = upstreamIds();
          const scoped = Object.fromEntries(Object.entries(outputs).filter(([nid]) => ups.has(nid)));
          if (Object.keys(scoped).length) {
            postToIframe({ type: 'noclick:event', event: 'inputs:changed', data: scoped });
          }
        }).catch(() => {/* best-effort initial inputs */});
      }

      // Author documents intentionally have an opaque origin, so the host must
      // never reach into contentWindow to patch globals or inspect the document.
    };
    iframe.addEventListener('load', handleLoad);
    return () => iframe.removeEventListener('load', handleLoad);
  }, [disabled, iframeRef, nodeId, postToIframe, workflowId, readOnly, upstreamIds]);

  // Handle SDK requests
  const handleMessage = useCallback((event: MessageEvent) => {
    // Only accept messages from our iframe
    if (event.source !== iframeRef.current?.contentWindow) return;

    const msg = event.data as SDKRequest;
    // The SDK signals readiness once its listeners are registered — (re)send init so
    // a load-ordering race can't leave the component without its nodeId.
    if (msg && (msg as { type?: string }).type === 'noclick:ready') {
      postToIframe({ type: 'noclick:event', event: 'init', data: { nodeId } });
      return;
    }
    if (!msg || (msg.type !== 'noclick:request' && msg.type !== 'noclick:fire')) return;

    const { id, method, params = {} } = msg;

    // Track this SDK call
    sdkDebugStore.startCall(id, method, params, nodeId);

    try {
      if (readOnly && !READ_ONLY_ALLOWED_METHODS.has(method)) {
        respondError(id, `SDK method ${method} is not available in read-only replay`);
        return;
      }

      // The host-provided graph snapshot is the capability. Every author-supplied
      // target below is resolved against this same snapshot before any local
      // mutation, socket call, or execution dispatch.
      const currentNodes = getNodes();

      switch (method) {
        // --- Node operations ---
        case 'nodes.getOutput': {
          const targetId = requireScopedNode(currentNodes, params.nodeId, method).id;
          const local = currentNodes.find(n => n.id === targetId)?.data?.output;
          if (local != null) { respond(id, local); break; }
          // Not hydrated in memory yet — a component can call getOutput on mount
          // before FlowCanvas's workflow:get_node_outputs has populated node.data.output
          // on load. Read the restored output from the backend so the first call isn't
          // stuck with a premature null until a re-render. Read-only/replay carries its
          // outputs in the passed graph, so only fetch when scoped to a live workflow.
          if (readOnly || !workflowId) { respond(id, local ?? null); break; }
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'workflow:get_node_outputs' as const,
                request_id: `sdk-get-output-${Date.now()}`,
                workflow_id: workflowId,
                node_ids: [targetId],
              } as any);
              respond(id, (resp as any)?.outputs?.[targetId] ?? null);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to fetch node output');
            }
          })();
          break;
        }
        case 'nodes.getConfig': {
          const node = requireScopedNode(currentNodes, params.nodeId, method);
          // data.config is the authoritative store for user-editable config fields
          const graphNode = currentNodes.find((candidate) => candidate.id === node.id);
          respond(id, (graphNode?.data?.config as Record<string, unknown>) ?? {});
          break;
        }
        case 'nodes.setConfig': {
          const targetId = requireScopedNode(currentNodes, params.nodeId, method).id;
          const config = params.config as Record<string, unknown>;
          // Update in-memory ReactFlow state (immediate) — merge into data.config
          const existingNode = currentNodes.find(n => n.id === targetId);
          const existingConfig = ((existingNode?.data?.config as Record<string, unknown>) || {});
          updateNodeData(targetId, { config: { ...existingConfig, ...config } });
          // Also persist to backend DB (durable across tab switches and refreshes)
          if (workflowId) {
            sendEventAsync({
              event_name: 'workflow:node:set_config' as const,
              request_id: `sdk-set-config-${Date.now()}`,
              workflow_id: workflowId,
              node_id: targetId,
              config,
            } as any).catch(() => {/* best-effort backend persist */});
          }
          respond(id, null);
          break;
        }
        case 'nodes.list': {
          const allNodes = currentNodes
            .filter(n => n.type && !n.type.startsWith('collaborator'))
            .map(n => ({
              id: n.id,
              type: n.type || 'unknown',
              label: (n.data?.label as string) || n.type || 'unknown',
              hasOutput: !!n.data?.output,
            }));
          respond(id, allNodes);
          break;
        }

        // --- Execution ---
        case 'execution.runNodesAndGetOutput': {
          if (!Array.isArray(params.runNodes)) {
            throw new Error(`SDK method ${method} requires runNodes to be an array`);
          }
          const runNodes = params.runNodes as Array<{ id: string; config?: Record<string, unknown> }>;
          const runNodeIds = requireScopedNodeIds(
            currentNodes,
            runNodes.map((ref) => ref?.id),
            method,
            'runNodes',
          );
          const targetNodes = requireScopedNodeIds(currentNodes, params.targetNodes, method, 'targetNodes');
          if (!runNodeIds.length || !targetNodes.length) {
            throw new Error(`SDK method ${method} requires at least one run node and target node`);
          }

          // Apply temporary config overrides to ReactFlow state (for display) and collect for backend
          const configOverrides: Record<string, Record<string, unknown>> = {};
          runNodes.forEach(ref => {
            if (ref.config) {
              const existing = ((currentNodes.find(n => n.id === ref.id)?.data?.config as Record<string, unknown>) || {});
              updateNodeData(ref.id, { config: { ...existing, ...ref.config } });
              configOverrides[ref.id] = ref.config;
            }
          });

          // Track this stream request, with a backstop timeout so a target that
          // never reaches a terminal state (unreachable / skipped branch / stopped
          // run) can't leak the entry forever and keep re-posting stale outputs.
          const streamTimer = setTimeout(() => {
            const s = pendingStreams.current.get(id);
            if (!s) return;
            postToIframe({ type: 'noclick:stream', id, event: 'error', nodeId: s.targetNodes[0] || 'unknown', data: 'Execution timed out' });
            pendingStreams.current.delete(id);
          }, 120000);
          pendingStreams.current.set(id, { targetNodes, timer: streamTimer });
          sdkDebugStore.markStreaming(id);

          // Trigger execution via custom event (same mechanism as node hover pill "Run").
          // background: true keeps this component-scoped data fetch out of the
          // global workflow Run/Stop button — it's not an explicit user run.
          const firstNodeId = runNodeIds[0];
          if (firstNodeId) {
            document.dispatchEvent(new CustomEvent('noclick:run-from-node', {
              detail: { nodeId: firstNodeId, configOverrides: Object.keys(configOverrides).length ? configOverrides : undefined, background: true },
            }));
          }
          // Don't respond yet — stream events will be sent as outputs arrive
          break;
        }
        case 'execution.runNodesInBackground': {
          if (!Array.isArray(params.runNodes)) {
            throw new Error(`SDK method ${method} requires runNodes to be an array`);
          }
          const runNodes = params.runNodes as Array<{ id: string; config?: Record<string, unknown> }>;
          const runNodeIds = requireScopedNodeIds(
            currentNodes,
            runNodes.map((ref) => ref?.id),
            method,
            'runNodes',
          );
          if (!runNodeIds.length) {
            throw new Error(`SDK method ${method} requires at least one run node`);
          }

          // Apply temporary config overrides to ReactFlow state (for display) and collect for backend
          const configOverrides: Record<string, Record<string, unknown>> = {};
          runNodes.forEach(ref => {
            if (ref.config) {
              const existing = ((currentNodes.find(n => n.id === ref.id)?.data?.config as Record<string, unknown>) || {});
              updateNodeData(ref.id, { config: { ...existing, ...ref.config } });
              configOverrides[ref.id] = ref.config;
            }
          });

          // Fire and forget — background: true keeps this component-scoped
          // data fetch out of the global workflow Run/Stop button.
          const firstNodeId = runNodeIds[0];
          if (firstNodeId) {
            document.dispatchEvent(new CustomEvent('noclick:run-from-node', {
              detail: { nodeId: firstNodeId, configOverrides: Object.keys(configOverrides).length ? configOverrides : undefined, background: true },
            }));
          }
          // No response needed — mark as completed immediately
          sdkDebugStore.endCall(id, null);
          break;
        }
        case 'execution.stop': {
          document.dispatchEvent(new CustomEvent('noclick:stop-workflow'));
          respond(id, null);
          break;
        }

        // --- State ---
        // State persists in the backend workflow_node_state table (the SAME store the
        // WebSocket SDK and state-manager node execution use). Reading/writing the
        // in-memory node.data.config.state instead (the old behavior) was a dual store:
        // iframe-set state was lost on reload and never seen by node runs. Replay has
        // no live backend, so it reads the in-memory snapshot it was given.
        case 'state.get': {
          const key = params.key as string;
          const stateNodeId = params.node === undefined
            ? undefined
            : requireScopedStateNode(currentNodes, params.node, method).id;
          if (readOnly || !workflowId) {
            const stateNode = stateNodeId ? currentNodes.find(n => n.id === stateNodeId) : currentNodes.find(n => n.type === 'state-manager');
            const st = (stateNode?.data?.config as Record<string, any> | undefined)?.state as Record<string, unknown> | undefined;
            respond(id, st?.[key] ?? undefined);
            break;
          }
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'workflow:state:get' as const,
                request_id: `sdk-state-get-${Date.now()}`,
                workflow_id: workflowId,
                key,
                ...(stateNodeId ? { node_id: stateNodeId } : {}),
              } as any);
              respond(id, (resp as any)?.value ?? undefined);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to get state');
            }
          })();
          break;
        }
        case 'state.set': {
          const key = params.key as string;
          const value = params.value;
          const stateNodeId = params.node === undefined
            ? undefined
            : requireScopedStateNode(currentNodes, params.node, method).id;
          if (!workflowId) { respondError(id, 'Cannot persist state: workflow is not saved'); break; }
          (async () => {
            try {
              await sendEventAsync({
                event_name: 'workflow:state:set' as const,
                request_id: `sdk-state-set-${Date.now()}`,
                workflow_id: workflowId,
                key,
                value,
                ...(stateNodeId ? { node_id: stateNodeId } : {}),
              } as any);
              respond(id, null);
              postToIframe({ type: 'noclick:event', event: 'state:changed', data: { key, value } });
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to set state');
            }
          })();
          break;
        }
        case 'state.delete': {
          const key = params.key as string;
          const stateNodeId = params.node === undefined
            ? undefined
            : requireScopedStateNode(currentNodes, params.node, method).id;
          if (!workflowId) { respondError(id, 'Cannot persist state: workflow is not saved'); break; }
          (async () => {
            try {
              // null value means delete the key (backend removes it from the JSONB).
              await sendEventAsync({
                event_name: 'workflow:state:set' as const,
                request_id: `sdk-state-del-${Date.now()}`,
                workflow_id: workflowId,
                key,
                value: null,
                ...(stateNodeId ? { node_id: stateNodeId } : {}),
              } as any);
              respond(id, null);
              postToIframe({ type: 'noclick:event', event: 'state:changed', data: { key, value: undefined } });
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to delete state');
            }
          })();
          break;
        }
        case 'state.keys': {
          const stateNodeId = params.node === undefined
            ? undefined
            : requireScopedStateNode(currentNodes, params.node, method).id;
          if (readOnly || !workflowId) {
            const stateNodes = stateNodeId ? currentNodes.filter(n => n.id === stateNodeId) : currentNodes.filter(n => n.type === 'state-manager');
            const keys = new Set<string>();
            stateNodes.forEach(n => {
              const st = (n.data?.config as Record<string, any> | undefined)?.state as Record<string, unknown> | undefined;
              if (st) Object.keys(st).forEach(k => keys.add(k));
            });
            respond(id, Array.from(keys));
            break;
          }
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'workflow:state:keys' as const,
                request_id: `sdk-state-keys-${Date.now()}`,
                workflow_id: workflowId,
                ...(stateNodeId ? { node_id: stateNodeId } : {}),
              } as any);
              respond(id, (resp as any)?.keys ?? []);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to list state keys');
            }
          })();
          break;
        }

        // --- Auth ---
        case 'auth.listCredentials': {
          (async () => {
            try {
              const response = await sendEventAsync({
                event_name: 'credential:list' as const,
                request_id: `sdk-cred-list-${Date.now()}`,
              });
              const creds = ((response as any)?.credentials || []).map((c: any) => ({
                id: c.id,
                type: c.credential_type,
                name: c.name,
              }));
              respond(id, creds);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to list credentials');
            }
          })();
          break;
        }
        case 'auth.hasCredential': {
          const credType = params.credentialType as string;
          (async () => {
            try {
              const response = await sendEventAsync({
                event_name: 'credential:list' as const,
                request_id: `sdk-cred-has-${Date.now()}`,
              });
              const has = ((response as any)?.credentials || []).some(
                (c: any) => c.credential_type === credType
              );
              respond(id, has);
            } catch (e) {
              // Don't mask a lookup failure as "no credential" — the component
              // can't tell a real error from a legitimate false (no-silent-fallback).
              respondError(id, e instanceof Error ? e.message : 'Failed to check credential');
            }
          })();
          break;
        }
        case 'auth.requestCredential': {
          const credType = params.credentialType as string;
          if (!oauthConnect) {
            respondError(id, 'OAuth not available in this context');
            break;
          }
          // Look up provider and scopes from the node schema (most reliable source)
          const schemaInfo = findOAuthScopesForCredentialType(credType);

          // Fall back to provider config if schema lookup fails
          import('~/utils/oauthProviders').then(({ getProviderKeyFromCredentialType }) => {
            const providerKey = schemaInfo?.provider || getProviderKeyFromCredentialType(credType);
            if (!providerKey) {
              respondError(id, `Unknown credential type: ${credType}`);
              return;
            }
            const scopes = schemaInfo?.scopes;

            // Register a one-time callback for when the credential is created
            onOAuthCreated?.((credentialId, _provider) => {
              sendEventAsync({
                event_name: 'credential:list' as const,
                request_id: `sdk-cred-get-${Date.now()}`,
              }).then((resp: any) => {
                const cred = (resp?.credentials || []).find((c: any) => c.id === credentialId);
                respond(id, { id: credentialId, type: credType, name: cred?.name || credType });
              }).catch(() => {
                respond(id, { id: credentialId, type: credType, name: credType });
              });
            });
            // Resolve null if the user cancels (closes the popup) — matches the SDK
            // contract ("null if cancelled") instead of hanging until the 30s timeout.
            onOAuthCancelled?.(() => respond(id, null));
            // Trigger the OAuth flow — scopes from schema, readable name from credential type
            const credName = credType.replace(/_oauth$/, '').replace(/_/g, ' ');
            oauthConnect(providerKey, credName, scopes);
          }).catch((e) => {
            respondError(id, e instanceof Error ? e.message : 'Failed to load OAuth providers');
          });
          break;
        }
        case 'auth.createCredential': {
          const credType = params.credentialType as string;
          const credData = params.data as Record<string, unknown>;
          const credName = (params.name as string) || `${credType} - ${new Date().toLocaleDateString()}`;
          (async () => {
            try {
              const response = await sendEventAsync({
                event_name: 'credential:create' as const,
                request_id: `sdk-cred-create-${Date.now()}`,
                name: credName,
                credential_type: credType,
                credential_data: credData,
                metadata: {},
              } as any);
              if ((response as any)?.success && (response as any)?.credential) {
                const cred = (response as any).credential;
                respond(id, { id: cred.id, type: credType, name: cred.name || credName });
              } else {
                respondError(id, (response as any)?.message || 'Failed to create credential');
              }
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to create credential');
            }
          })();
          break;
        }

        // --- Resources (blobs/files) ---
        case 'resources.upload': {
          const { name: rName, mimeType, sizeBytes, resourceType } = params as any;
          (async () => {
            try {
              const createResp = await sendEventAsync({
                event_name: 'resource:create' as const,
                request_id: `sdk-res-create-${Date.now()}`,
                workflow_id: workflowId,
                resource_type: resourceType || 'file',
                name: rName,
                mime_type: mimeType,
                size_bytes: sizeBytes,
              } as any);
              const resource = (createResp as any)?.resource;
              if (!resource?.id) { respondError(id, 'Failed to create resource'); return; }
              const uploadResp = await sendEventAsync({
                event_name: 'resource:upload_url' as const,
                request_id: `sdk-res-upload-${Date.now()}`,
                resource_id: resource.id,
                filename: rName,
                content_type: mimeType,
              } as any);
              respond(id, {
                resourceId: resource.id,
                uploadUrl: (uploadResp as any)?.upload_url,
              });
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Upload failed');
            }
          })();
          break;
        }
        case 'resources.getUrl': {
          const resourceId = params.resourceId as string;
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'resource:download_url' as const,
                request_id: `sdk-res-dl-${Date.now()}`,
                resource_id: resourceId,
              } as any);
              respond(id, (resp as any)?.download_url || '');
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to get URL');
            }
          })();
          break;
        }
        case 'resources.remove': {
          (async () => {
            try {
              await sendEventAsync({
                event_name: 'resource:delete' as const,
                request_id: `sdk-res-del-${Date.now()}`,
                resource_id: params.resourceId as string,
              } as any);
              respond(id, null);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Delete failed');
            }
          })();
          break;
        }
        case 'resources.list': {
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'resource:list' as const,
                request_id: `sdk-res-list-${Date.now()}`,
                workflow_id: workflowId,
                resource_type: (params.resourceType as string) || undefined,
              } as any);
              const resources = ((resp as any)?.resources || []).map((r: any) => ({
                id: r.id,
                name: r.name,
                resourceType: r.resource_type,
                mimeType: r.mime_type,
                sizeBytes: r.size_bytes,
              }));
              respond(id, resources);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'List failed');
            }
          })();
          break;
        }

        // --- Dataset (tabular CRUD) ---
        case 'dataset.list': {
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'resource:list' as const,
                request_id: `sdk-ds-list-${Date.now()}`,
                workflow_id: workflowId,
                resource_type: 'dataset',
              } as any);
              const datasets = ((resp as any)?.resources || []).map((r: any) => ({
                id: r.id,
                name: r.name,
                rowCount: r.metadata?.row_count || 0,
              }));
              respond(id, datasets);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'List failed');
            }
          })();
          break;
        }
        case 'dataset.create': {
          const dsName = params.name as string;
          (async () => {
            try {
              const createResp = await sendEventAsync({
                event_name: 'resource:create' as const,
                request_id: `sdk-ds-create-${Date.now()}`,
                workflow_id: workflowId,
                resource_type: 'dataset',
                name: dsName,
              } as any);
              const resource = (createResp as any)?.resource;
              if (!resource?.id) { respondError(id, 'Failed to create dataset'); return; }
              respond(id, resource.id);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Create failed');
            }
          })();
          break;
        }
        case 'dataset.getRows': {
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'resource:dataset:rows' as const,
                request_id: `sdk-ds-rows-${Date.now()}`,
                resource_id: params.resourceId as string,
                limit: (params.limit as number) || 100,
                offset: (params.offset as number) || 0,
              } as any);
              respond(id, {
                rows: (resp as any)?.rows || [],
                totalCount: (resp as any)?.total_count || 0,
              });
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to get rows');
            }
          })();
          break;
        }
        case 'dataset.appendRows': {
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'resource:dataset:append' as const,
                request_id: `sdk-ds-append-${Date.now()}`,
                resource_id: params.resourceId as string,
                rows: params.rows as Record<string, unknown>[],
              } as any);
              respond(id, { insertedCount: (resp as any)?.inserted_count || 0 });
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Append failed');
            }
          })();
          break;
        }
        case 'dataset.updateRow': {
          (async () => {
            try {
              await sendEventAsync({
                event_name: 'resource:dataset:update_row' as const,
                request_id: `sdk-ds-update-${Date.now()}`,
                resource_id: params.resourceId as string,
                row_id: params.rowId as string,
                data: params.data as Record<string, unknown>,
              } as any);
              respond(id, null);
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Update failed');
            }
          })();
          break;
        }
        case 'dataset.deleteRows': {
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'resource:dataset:delete_rows' as const,
                request_id: `sdk-ds-delete-${Date.now()}`,
                resource_id: params.resourceId as string,
                row_ids: params.rowIds as string[],
              } as any);
              respond(id, { deletedCount: (resp as any)?.deleted_count || 0 });
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Delete failed');
            }
          })();
          break;
        }

        // --- Workflow ---
        case 'workflow.getInfo': {
          const nodeCount = currentNodes.filter(n => n.type && !n.type.startsWith('collaborator')).length;
          // Name isn't in ReactFlow state; fetch it from the backend (the in-memory
          // bridge previously returned an empty name). Skip in read-only/replay or
          // when unsaved (no workflow scope).
          if (readOnly || !workflowId) { respond(id, { id: workflowId || '', name: '', nodeCount }); break; }
          (async () => {
            try {
              const resp = await sendEventAsync({
                event_name: 'workflow:get' as const,
                request_id: `sdk-wf-info-${Date.now()}`,
                workflow_id: workflowId,
              } as any);
              const wf = (resp as any)?.workflow ?? resp;
              respond(id, { id: wf?.id ?? workflowId, name: wf?.name ?? '', nodeCount });
            } catch (e) {
              respondError(id, e instanceof Error ? e.message : 'Failed to fetch workflow info');
            }
          })();
          break;
        }

        default:
          respondError(id, `Unknown SDK method: ${method}`);
      }
    } catch (err) {
      respondError(id, err instanceof Error ? err.message : String(err));
    }
  }, [iframeRef, getNodes, updateNodeData, respond, respondError, postToIframe, nodeId, workflowId, oauthConnect, onOAuthCreated, onOAuthCancelled, readOnly]);

  // Listen for postMessage from iframe
  useEffect(() => {
    if (disabled) return;
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [disabled, handleMessage]);

  // Forward socket events to iframe: node output, node state, and inputs
  useEffect(() => {
    if (disabled) return;
    // Forward node output events — both to pending streams and as general push events
    const unsubOutput = onSocketEvent('workflow:node:output' as any, (data: any) => {
      if (data.workflow_id && data.workflow_id !== workflowId) return;
      if (!isScopedNodeId(getNodes(), data.node_id)) return;

      // General push: execution.onNodeOutput() subscribers
      postToIframe({
        type: 'noclick:event', event: 'node:output',
        data: { nodeId: data.node_id, output: data.output },
      });

      // Stream: forward to pending runNodesAndGetOutput streams
      for (const [reqId, stream] of pendingStreams.current) {
        if (stream.targetNodes.includes(data.node_id)) {
          postToIframe({
            type: 'noclick:stream', id: reqId, event: 'output',
            nodeId: data.node_id, data: data.output,
          });
          sdkDebugStore.addStreamEvent(reqId, 'output', data.node_id, data.output);
        }
      }

      // Inputs: only nodes wired into this component's input handle (edges targeting
      // nodeId) are its inputs — don't flood useInputs() with the whole graph's outputs.
      if (upstreamIds().has(data.node_id)) {
        postToIframe({
          type: 'noclick:event', event: 'inputs:changed',
          data: { [data.node_id]: data.output },
        });
      }
    });

    // Forward node state events — both general push and stream completion tracking
    const unsubState = onSocketEvent('workflow:node:state' as any, (data: any) => {
      if (data.workflow_id && data.workflow_id !== workflowId) return;
      if (!isScopedNodeId(getNodes(), data.node_id)) return;

      // General push: execution.onNodeState() subscribers
      postToIframe({
        type: 'noclick:event', event: 'node:state',
        data: { nodeId: data.node_id, state: data.state },
      });

      // Stream: forward error event to iframe so SDK's onError handler fires
      if (data.state === 'error') {
        for (const [reqId, stream] of pendingStreams.current) {
          if (stream.targetNodes.includes(data.node_id)) {
            postToIframe({
              type: 'noclick:stream', id: reqId, event: 'error',
              nodeId: data.node_id, data: data.error,
            });
            sdkDebugStore.addStreamEvent(reqId, 'error', data.node_id, data.error);
          }
        }
      }

      // Stream: check if all target nodes completed for any pending stream
      if (data.state === 'completed' || data.state === 'error' || data.state === 'skipped') {
        for (const [reqId, stream] of pendingStreams.current) {
          if (!stream.targetNodes.includes(data.node_id)) continue;
          // Use a simpler completion check: track which targets have completed
          if (!stream.completed) stream.completed = new Set();
          (stream.completed as Set<string>).add(data.node_id);
          if (stream.targetNodes.every(tid => (stream.completed as Set<string>).has(tid))) {
            postToIframe({ type: 'noclick:stream', id: reqId, event: 'done' });
            sdkDebugStore.addStreamEvent(reqId, 'done');
            if (stream.timer) clearTimeout(stream.timer);
            pendingStreams.current.delete(reqId);
          }
        }
      }
    });

    return () => { unsubOutput(); unsubState(); };
  }, [disabled, workflowId, getNodes, postToIframe, nodeId, upstreamIds]);
}
