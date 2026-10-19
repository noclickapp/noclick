/**
 * Event Relay WebSocket hook for cross-container real-time events.
 * Connects to the event relay (see lib/hostedDefaults) to receive events
 * from webhooks, cron jobs,
 * and other backend processes that may run on different managed workers.
 *
 * Events received via relay are injected into socket-receiver's handler system,
 * so existing useSocketEvent hooks work seamlessly with relay events.
 *
 * Reconnection strategy: delegated to `partysocket`'s ReconnectingWebSocket.
 * Handles connection-stuck detection, exponential backoff with jitter, and
 * the WebSocket spec's lack of native reconnection. We expose a global
 * `window.__ncRelayWs` so HMR-aware modules and dev tooling can inspect /
 * close the active socket without us managing all that lifecycle here.
 */

import { useEffect, useRef, useCallback } from 'react';
import ReconnectingWebSocket from 'partysocket/ws';
import { socketReceiver } from '~/lib/socket-receiver';
import type { ServerToClientEvents } from '~/types/socket-events.generated';
import { relayBaseUrl } from '~/lib/hostedDefaults';
import { forgetUserRelayToken, getUserRelayToken } from '~/lib/relayToken';

interface RelayMessage {
  type: string;
  [key: string]: unknown;
}

interface UseEventRelayOptions {
  /** User ID for connecting to the correct relay room */
  userId: string;
  /** Optional workflow ID to filter events */
  workflowId?: string;
  /** Whether the relay should be enabled (default: true when userId is provided) */
  enabled?: boolean;
}

interface RelayConnectionState {
  status: 'connecting' | 'connected' | 'disconnected' | 'error';
  error?: string;
  connectionCount?: number;
}

// Stash the active socket on window so dev tooling (SocketDebugBar) and
// HMR-aware listeners (builderHydration) can find it without dependency
// injection. Cleared on close.
function setActiveRelayWs(ws: ReconnectingWebSocket | null): void {
  if (typeof window === 'undefined') return;
  const w = window as unknown as { __ncRelayWs?: ReconnectingWebSocket };
  w.__ncRelayWs = ws ?? undefined;
}

// A failed token mint is retried after 1s, 2s, 4s… (capped), and a connection
// that still has none after this many tries starts over on a fresh one.
const MINT_RETRY_BASE_MS = 1000;
const MINT_RETRY_MAX_MS = 30000;
const MINT_ATTEMPTS_PER_CONNECTION = 4;

/**
 * Hook for connecting to the Event Relay WebSocket.
 * Auto-reconnects with exponential backoff + jitter, detects stuck CONNECTING
 * states, and pings the relay every 15s to keep idle TCP paths warm.
 */
export function useEventRelay({ userId, workflowId, enabled = true }: UseEventRelayOptions) {
  const wsRef = useRef<ReconnectingWebSocket | null>(null);
  const stateRef = useRef<RelayConnectionState>({ status: 'disconnected' });
  const keepaliveRef = useRef<NodeJS.Timeout | null>(null);
  // Track pending MCP request IDs so we can relay responses back through the WS
  const pendingRelayRequests = useRef<Set<string>>(new Set());

  const getRelayUrl = useCallback(() => {
    const baseUrl = relayBaseUrl();
    let url = `${baseUrl}/${userId}`;
    if (workflowId) {
      url += `?workflowId=${encodeURIComponent(workflowId)}`;
    }
    return url;
  }, [userId, workflowId]);

  // Connect on mount, disconnect on unmount.
  useEffect(() => {
    if (!enabled || !userId) return;

    const url = getRelayUrl();
    console.log(`[EventRelay] Connecting to ${url}`);
    stateRef.current = { status: 'connecting' };

    const ws = new ReconnectingWebSocket(url, [], {
      // Connection-stuck detection: if a CONNECTING attempt doesn't transition
      // to OPEN within this window, partysocket force-closes and retries.
      // Without this, a blackholed TCP SYN (corporate proxy, dropped route)
      // would leave us hanging until the OS kernel timeout (~75s).
      connectionTimeout: 5000,
      // Exponential backoff with jitter (partysocket adds randomization).
      minReconnectionDelay: 1000,
      maxReconnectionDelay: 30000,
      reconnectionDelayGrowFactor: 2,
      maxRetries: Infinity,
      // Don't reconnect on close codes that mean "we asked to close" — e.g.
      // the dev force-disconnect (4000) and HMR supersede (4001).
      // partysocket's default is to reconnect on every non-1000 close, so we
      // keep that behavior for true unexpected drops while letting our own
      // close-with-code calls suppress reconnect when we want.
    });
    wsRef.current = ws;
    setActiveRelayWs(ws);

    // Once the relay requires auth, an unauthenticated tab receives nothing,
    // so a connection whose mint fails retries it with backoff and reconnects
    // if it keeps failing. `connection` changes on every open and close, so a
    // retry or a late token never reaches a connection it wasn't for.
    let connection = 0;
    let mintFailures = 0; // consecutive, across connections: grows the backoff
    let mintRetry: ReturnType<typeof setTimeout> | null = null;
    const clearMintRetry = () => {
      if (mintRetry) clearTimeout(mintRetry);
      mintRetry = null;
    };
    const authenticate = (conn: number, attempt: number) => {
      getUserRelayToken(userId).then(
        (token) => {
          mintFailures = 0;
          if (token && conn === connection && ws.readyState === ReconnectingWebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'auth', token }));
          }
        },
        (error: unknown) => {
          mintFailures += 1;
          if (conn !== connection) return;
          if (attempt + 1 >= MINT_ATTEMPTS_PER_CONNECTION) {
            console.error('[EventRelay] No relay token after retries; reconnecting:', error);
            ws.reconnect(4002, 'relay token unavailable');
            return;
          }
          const delay = Math.min(MINT_RETRY_BASE_MS * 2 ** (mintFailures - 1), MINT_RETRY_MAX_MS);
          console.warn(`[EventRelay] Relay token mint failed; retrying in ${delay}ms:`, error);
          mintRetry = setTimeout(() => authenticate(conn, attempt + 1), delay);
        },
      );
    };

    ws.addEventListener('open', () => {
      console.log('[EventRelay] Connected');
      stateRef.current = { status: 'connected' };
      // Dev indicator (SocketDebugBar) listens for this to show status.
      window.dispatchEvent(new CustomEvent('noclick:relay:connected'));

      // Start keepalive. Sends literal "ping" every 15s; the relay is
      // configured with setWebSocketAutoResponse("ping" -> "pong") so the
      // reply is synthesized at the runtime without waking the relay from
      // hibernation, keeping intermediaries from dropping the TCP as idle.
      if (keepaliveRef.current) clearInterval(keepaliveRef.current);
      keepaliveRef.current = setInterval(() => {
        try { ws.send('ping'); } catch { /* ignore — partysocket handles closed sockets */ }
      }, 15000);

      // Re-subscribe to the workflow on (re)connect — the relay doesn't
      // remember subscriptions across socket lifetimes.
      if (workflowId) {
        ws.send(JSON.stringify({ type: 'subscribe', workflowId }));
      }

      // Prove this tab is the user: its first frame carries a short-lived
      // token (never the URL). Each connect sends one, so a reconnect after
      // the last one lapsed mints another.
      connection += 1;
      clearMintRetry();
      authenticate(connection, 0);
    });

    ws.addEventListener('message', (event: MessageEvent) => {
      // Auto-response keepalive ack from the relay — not JSON, just skip.
      if (event.data === 'pong') return;
      try {
        const data = JSON.parse(event.data) as RelayMessage;

        if (data.type === 'connected') {
          stateRef.current = {
            status: 'connected',
            connectionCount: data.connectionCount as number,
          };
          console.log(`[EventRelay] Confirmed connection (${data.connectionCount} total connections)`);
          return;
        }

        if (data.type === 'subscribed' || data.type === 'unsubscribed') {
          return;
        }

        if (data.type === 'auth:required' || data.type === 'auth:success') {
          return;
        }
        if (data.type === 'auth:error') {
          // Drop it, so the next connect mints a fresh one.
          console.error('[EventRelay] Relay refused the token:', data.message);
          forgetUserRelayToken();
          return;
        }

        // Handle MCP request-response: inject as socket event so existing
        // handlers pick it up, and track the request_id so we can relay the
        // response back through the WS.
        if (data.type === 'mcp_request') {
          const requestId = data.request_id as string;
          pendingRelayRequests.current.add(requestId);
          console.log(`[EventRelay] MCP request received: ${data.request_type} (${requestId})`);
          socketReceiver.injectWireEvent('workflow:mcp:request', {
            request_id: requestId,
            request_type: data.request_type,
            params: data.params,
          });
          return;
        }

        // Inject all other events into socket-receiver's handler system.
        const eventType = data.type as keyof ServerToClientEvents;
        console.log(`[EventRelay] Received event: ${eventType}`, data);
        socketReceiver.injectWireEvent(eventType, data);
      } catch (error) {
        console.error('[EventRelay] Failed to parse message:', error);
      }
    });

    ws.addEventListener('close', (event: CloseEvent) => {
      console.log(`[EventRelay] Disconnected (code: ${event.code}, reason: ${event.reason || 'none'})`);
      stateRef.current = { status: 'disconnected' };
      connection += 1;
      clearMintRetry();
      if (keepaliveRef.current) {
        clearInterval(keepaliveRef.current);
        keepaliveRef.current = null;
      }
      window.dispatchEvent(new CustomEvent('noclick:relay:disconnected'));
    });

    ws.addEventListener('error', (event: Event) => {
      console.error('[EventRelay] WebSocket error:', event);
      stateRef.current = { status: 'error', error: 'Connection error' };
    });

    return () => {
      if (keepaliveRef.current) {
        clearInterval(keepaliveRef.current);
        keepaliveRef.current = null;
      }
      connection += 1;
      clearMintRetry();
      // partysocket.close() prevents further reconnection attempts.
      ws.close();
      wsRef.current = null;
      setActiveRelayWs(null);
    };
  }, [enabled, userId, getRelayUrl, workflowId]);

  // Subscribe to a specific workflow (idempotent — server tracks subscription
  // per WS, refetch on reconnect via the open handler above).
  const subscribeToWorkflow = useCallback((wfId: string) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === ReconnectingWebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'subscribe', workflowId: wfId }));
    }
  }, []);

  const unsubscribeFromWorkflow = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === ReconnectingWebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'unsubscribe' }));
    }
  }, []);

  // Listen for relay:mcp_response window events and send back through relay WS.
  useEffect(() => {
    const handler = (e: Event) => {
      const { request_id, data, error } = (e as CustomEvent).detail;
      const ws = wsRef.current;
      if (
        pendingRelayRequests.current.has(request_id)
        && ws
        && ws.readyState === ReconnectingWebSocket.OPEN
      ) {
        ws.send(JSON.stringify({ type: 'mcp_response', request_id, data, error }));
        pendingRelayRequests.current.delete(request_id);
        console.log(`[EventRelay] Sent MCP response for ${request_id}`);
      }
    };
    window.addEventListener('relay:mcp_response', handler);
    return () => window.removeEventListener('relay:mcp_response', handler);
  }, []);

  // Dev force-disconnect — exercise the reconnect path from SocketDebugBar.
  // partysocket's reconnect kicks in automatically on close.
  useEffect(() => {
    const handler = () => {
      const ws = wsRef.current;
      if (!ws) {
        console.warn('[EventRelay] DEV: force-disconnect — no active WS');
        return;
      }
      console.log('[EventRelay] DEV: force-disconnecting (readyState=%d)', ws.readyState);
      // Use reconnect() for symmetric "drop and come back" semantics. This is
      // partysocket's intended API for manual cycling.
      ws.reconnect(4000, 'dev force-disconnect');
    };
    window.addEventListener('noclick:relay:force-disconnect', handler);
    return () => window.removeEventListener('noclick:relay:force-disconnect', handler);
  }, []);

  // Re-subscribe to workflow filtering when workflowId changes (the open
  // handler covers fresh connections; this covers in-flight changes).
  useEffect(() => {
    if (workflowId) subscribeToWorkflow(workflowId);
  }, [workflowId, subscribeToWorkflow]);

  return {
    subscribeToWorkflow,
    unsubscribeFromWorkflow,
    isConnected: stateRef.current.status === 'connected',
    connectionState: stateRef.current,
  };
}
