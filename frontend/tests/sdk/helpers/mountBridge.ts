// L2 "bridge contract" harness. Mounts the real useSDKBridge in jsdom against a
// FAKE iframe (its contentWindow.postMessage is spied) and the REAL socketReceiver,
// so a test can post SDK requests "from the iframe" and drive realtime backend
// events exactly as production would — without a browser. See tests/sdk/*.test.ts.

import { renderHook, act } from '@testing-library/react';
import { vi } from 'vitest';
import type { Node } from '@xyflow/react';
import { socketReceiver } from '~/lib/socket-receiver';
import { useSDKBridge } from '~/hooks/useSDKBridge';

export interface MountBridgeOptions {
  nodes?: Node[];
  edges?: Array<{ source: string; target: string }>;
  workflowId?: string;
  readOnly?: boolean;
  /** Wire OAuth so auth.requestCredential proceeds (capture success/cancel callbacks). */
  oauth?: boolean;
}

export function mountBridge(opts: MountBridgeOptions = {}) {
  const workflowId = opts.workflowId ?? 'wf-1';
  let nodes: Node[] = opts.nodes ?? [];
  const edges = opts.edges ?? [];

  const oauthConnect = opts.oauth ? vi.fn() : undefined;
  let oauthCreatedCb: ((credentialId: string, provider: string) => void) | null = null;
  let oauthCancelledCb: (() => void) | null = null;

  const postMessage = vi.fn();
  const contentWindow = { postMessage } as unknown as Window;
  const domListeners: Record<string, Array<() => void>> = {};
  const iframeRef = {
    current: {
      contentWindow,
      addEventListener: (type: string, fn: () => void) => { (domListeners[type] ||= []).push(fn); },
      removeEventListener: (type: string, fn: () => void) => {
        domListeners[type] = (domListeners[type] || []).filter((f) => f !== fn);
      },
    } as unknown as HTMLIFrameElement,
  };

  const getNodes = () => nodes;
  const updateNodeData = (id: string, data: Record<string, any>) => {
    nodes = nodes.map((n) => {
      if (n.id !== id) return n;
      const next: any = { ...n, data: { ...(n.data as any) } };
      if (data.config) next.data.config = { ...((n.data as any)?.config ?? {}), ...data.config };
      for (const k of Object.keys(data)) if (k !== 'config') next.data[k] = data[k];
      return next;
    });
  };

  // Capture the execution-trigger custom events the bridge dispatches.
  const runFromNode: any[] = [];
  const onRun = (e: Event) => runFromNode.push((e as CustomEvent).detail);
  let stops = 0;
  const onStop = () => { stops += 1; };
  document.addEventListener('noclick:run-from-node', onRun);
  document.addEventListener('noclick:stop-workflow', onStop);

  const rendered = renderHook(() =>
    useSDKBridge({
      iframeRef,
      nodeId: 'component-1',
      workflowId,
      getNodes,
      getEdges: () => edges,
      updateNodeData,
      readOnly: opts.readOnly,
      oauthConnect,
      onOAuthCreated: opts.oauth ? (cb) => { oauthCreatedCb = cb; } : undefined,
      onOAuthCancelled: opts.oauth ? (cb) => { oauthCancelledCb = cb; } : undefined,
    }),
  );

  const posted = (): any[] => postMessage.mock.calls.map((c) => c[0]);

  return {
    workflowId,
    setNodes: (ns: Node[]) => { nodes = ns; },
    getNodesNow: () => nodes,
    runFromNode,
    stops: () => stops,

    /** Simulate the iframe posting an SDK request to the host. */
    sendRequest(method: string, params: Record<string, unknown> = {}, id = `req-${method}-${Math.random().toString(36).slice(2)}`) {
      act(() => {
        window.dispatchEvent(new MessageEvent('message', {
          data: { type: 'noclick:request', id, method, params },
          source: contentWindow as any,
        }));
      });
      return id;
    },
    /** Simulate a fire-and-forget SDK message from the iframe. */
    sendFire(method: string, params: Record<string, unknown> = {}) {
      act(() => {
        window.dispatchEvent(new MessageEvent('message', {
          data: { type: 'noclick:fire', method, params },
          source: contentWindow as any,
        }));
      });
    },
    /** Post an arbitrary raw message from the iframe (e.g. the noclick:ready signal). */
    sendRaw(data: unknown) {
      act(() => {
        window.dispatchEvent(new MessageEvent('message', { data, source: contentWindow as any }));
      });
    },
    /** Drive a backend socket event into the host (the realtime path). */
    serverEmit(name: string, data: unknown) {
      act(() => { socketReceiver.injectEvent(name as never, data as never); });
    },
    /** Fire the iframe's load event, triggering the bridge's init effect. */
    fireLoad() {
      act(() => { (domListeners['load'] || []).forEach((fn) => fn()); });
    },
    /** OAuth helpers (when mounted with { oauth: true }). */
    oauthConnectCalled: () => (oauthConnect?.mock.calls.length ?? 0) > 0,
    fireOAuthCancel() { act(() => { oauthCancelledCb?.(); }); },
    fireOAuthSuccess(credentialId: string, provider = 'github') { act(() => { oauthCreatedCb?.(credentialId, provider); }); },

    posted,
    responsesFor: (id: string) => posted().filter((m) => m.type === 'noclick:response' && m.id === id),
    streamsFor: (id: string) => posted().filter((m) => m.type === 'noclick:stream' && m.id === id),
    events: (event: string) => posted().filter((m) => m.type === 'noclick:event' && m.event === event),

    cleanup() {
      document.removeEventListener('noclick:run-from-node', onRun);
      document.removeEventListener('noclick:stop-workflow', onStop);
      rendered.unmount();
    },
  };
}

/** Convenience node factory for tests. */
export function testNode(id: string, data: Record<string, unknown> = {}, type = 'automation-http-request'): Node {
  return { id, type, position: { x: 0, y: 0 }, data } as unknown as Node;
}
