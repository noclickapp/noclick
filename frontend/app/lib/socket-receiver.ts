/**
 * Centralized socket event receiver for the frontend.
 * Manages multiple socket connections and routes events based on environment configuration.
 * Mirrors the backend's receiver pattern - all socket event handling should go through here.
 */

import { io, Socket } from 'socket.io-client';
import type {
  ServerToClientEvents,
  ClientToServerEvents,
  SocketEnvironment,
  ServerDataEvent,
} from '~/types/socket-events.generated';
import {
  createSocketConfig,
  EventRouting,
  DEFAULT_EVENT_BUFFER_TTL_MS,
} from './socket/config';
import { ConnectionRegistry } from './socket/connection-registry';
import { getExistingBrowserClient } from './supabase-client';
import { EventBuffer } from './socket/event-buffer';
import type { SocketEnvironmentConfig, SocketConnectionState } from './socket/types';
import { maybeChunk } from './socket/chunking';
import {
  chunkReceiver,
  isChunkedWrapper,
  type ChunkMetadata,
} from './socket/chunk-receiver';
import { profilingStore } from './profiling-store';

// Event handler registry
type EventHandler<K extends keyof ServerToClientEvents> =
  ServerToClientEvents[K] extends (...args: infer P) => void ? (...args: P) => void : never;

type EventHandlerMap = {
  [K in keyof ServerToClientEvents]?: EventHandler<K>[];
};

class SocketReceiver {
  private readonly sockets = new Map<SocketEnvironment, Socket<ServerToClientEvents, ClientToServerEvents>>();
  private readonly lazyConfigs = new Map<SocketEnvironment, SocketEnvironmentConfig>();
  private readonly eventToEnvironment = new Map<keyof ServerToClientEvents, SocketEnvironment>();
  private readonly buffer = new EventBuffer(DEFAULT_EVENT_BUFFER_TTL_MS);
  private readonly connections = new ConnectionRegistry<SocketEnvironment>();
  private handlers: EventHandlerMap = {};
  private isInitialized = false;

  connect(): void {
    if (this.isInitialized) {
      return;
    }

    if (typeof window === 'undefined') {
      return;
    }

    const shouldConnect = this.needsSocketConnection(window.location.pathname);
    const config = createSocketConfig(shouldConnect);

    Object.entries(config).forEach(([environment, cfg]) => {
      const env = environment as SocketEnvironment;

      cfg.events.forEach(eventName => {
        this.eventToEnvironment.set(eventName, env);
      });

      if (cfg.lazy) {
        this.lazyConfigs.set(env, cfg);
        this.connections.update(env, { status: 'disconnected' });
        return;
      }

      this.initializeSocket(env, cfg);
    });

    this.isInitialized = true;
    console.log('SocketReceiver initialized with environments:', Object.keys(config));
  }

  private needsSocketConnection(pathname: string): boolean {
    const isDashboard = pathname === '/dashboard' || pathname.startsWith('/dashboard/');
    if (!isDashboard) {
      return false;
    }

    // NEVER auto-connect. Always wait for useSocketTokenRefresh to call
    // updateAllAuth() after INITIAL_SESSION fires, so the handshake's auth
    // callback has an initialized Supabase session (and thus a token) to send.
    console.log('[SocketReceiver] Dashboard detected, deferring to useSocketTokenRefresh for connection');
    return false;
  }

  private initializeSocket(env: SocketEnvironment, cfg: SocketEnvironmentConfig): void {
    console.log(`[SocketReceiver] Creating socket for ${env} (autoConnect=${cfg.options?.autoConnect !== false})`);
    const socket = io(cfg.url, cfg.options);
    this.sockets.set(env, socket);

    if (socket.connected) {
      this.connections.update(env, {
        status: 'connected',
        lastConnectedAt: Date.now(),
      });
    } else {
      this.connections.update(env, {
        status: 'connecting',
        reconnectAttempt: 0,
      });
    }

    socket.on('connect', () => {
      console.log(`Socket connected to ${env}`);
      this.connections.update(env, {
        status: 'connected',
        lastConnectedAt: Date.now(),
        lastDisconnectReason: undefined,
        lastError: undefined,
        lastDisconnectedAt: undefined,
      });

      if (env === 'API') {
        console.log('[SocketReceiver] API socket handshake succeeded – connection is now fully authenticated.');
      }

      this.syncConnectionState(env);
    });

    socket.on('disconnect', (reason) => {
      console.log(`Socket disconnected from ${env}:`, reason);
      this.connections.update(env, {
        status: 'disconnected',
        lastDisconnectedAt: Date.now(),
        lastDisconnectReason: reason,
      });

      this.syncConnectionState(env);
    });

    socket.on('connect_error', (error) => {
      // Extract actual error message from Socket.IO error object
      // When backend raises ConnectionRefusedError with a payload, Socket.IO stores it in error.data
      // error.message typically contains generic transport errors (e.g., "xhr poll error")
      // error.data contains the actual auth error details from backend
      const errorData = (error as any).data as { message?: string; reason?: string; code?: string } | undefined;
      const errorMessage = errorData?.message || errorData?.reason || error.message;
      const errorCode = errorData?.code;

      // Debug: Log full error details for SSO troubleshooting
      console.error(`Socket connection error for ${env}:`, {
        message: errorMessage,
        code: errorCode,
        rawError: error.message,
        errorData: errorData,
        fullError: error,
      });

      // After CONNECT_ERROR, socket.destroy() is called by socket.io-client,
      // so the socket is no longer actively connecting. Set status to 'disconnected'
      // to allow retry on next updateAuth call.
      this.connections.update(env, {
        status: 'disconnected',
        lastError: errorMessage,
        lastDisconnectReason: errorMessage,
        lastErrorCode: errorCode,
      });

       this.syncConnectionState(env);
    });

    socket.on('error', (error) => {
      console.error(`Socket error for ${env}:`, error);
      // If the error has a request_id, resolve the pending callback with the error
      // so sendEventAsync doesn't hang until timeout (e.g. rate limit errors)
      if (error && typeof error === 'object' && error.request_id) {
        const callback = pendingCallbacks.get(error.request_id);
        if (callback) {
          callback({ error: error.message || error.type || 'Unknown error' });
          pendingCallbacks.delete(error.request_id);
        }
      }
    });

    socket.io.on('reconnect', (attempt) => {
      console.log(`Socket reconnected to ${env} after ${attempt} attempts`);
      this.connections.update(env, {
        status: 'connected',
        lastConnectedAt: Date.now(),
        reconnectAttempt: undefined,
        lastError: undefined,
      });

      this.syncConnectionState(env);

      // Builder asks/terminals are transient deltas with no replay for a
      // paused gen, so a drop that lands after a pause leaves the ask invisible
      // until a manual reload. Signal the main socket's reconnect so the canvas
      // ask-resume effect can re-reconcile pending state from the server (B9).
      if (env === 'API' && typeof document !== 'undefined') {
        document.dispatchEvent(new CustomEvent('noclick:socket:reconnected', { detail: { env } }));
      }
    });

    socket.io.on('reconnect_attempt', (attempt) => {
      console.log(`[SocketReceiver] Socket.IO reconnect attempt #${attempt} for ${env}`);
      this.connections.update(env, {
        status: 'connecting',
        reconnectAttempt: attempt,
      });

      this.syncConnectionState(env);
    });

    socket.io.on('reconnect_error', (error) => {
      // Extract actual error message (same logic as connect_error)
      const errorData = (error as any)?.data as { message?: string; reason?: string; code?: string } | undefined;
      const errorMessage = errorData?.message || errorData?.reason || error?.message || String(error);

      console.log(`Socket reconnection error for ${env}:`, {
        message: errorMessage,
        code: errorData?.code,
        rawError: error?.message,
      });

      this.connections.update(env, {
        status: 'connecting',
        lastError: errorMessage,
      });

      this.syncConnectionState(env);
    });

    socket.io.on('reconnect_failed', () => {
      console.log(`Socket reconnection failed for ${env}`);
      this.connections.update(env, {
        status: 'disconnected',
        lastError: 'Reconnection failed',
      });

      this.syncConnectionState(env);
    });

    cfg.events.forEach(eventName => {
      socket.on(eventName as string, (...args: unknown[]) => {
        this.handleEvent(eventName, args as Parameters<ServerToClientEvents[typeof eventName]>);
      });
    });
  }

  private handleEvent<E extends keyof ServerToClientEvents>(
    event: E,
    args: Parameters<ServerToClientEvents[E]>
  ): void {
    this.bufferCleanup(event);

    // Handle chunk events (backend -> frontend chunking)
    if (event === '__chunk__' && args.length > 0) {
      chunkReceiver.handleChunk(args[0] as ChunkMetadata);
      return; // Don't process further - chunks are internal
    }

    // Check if this is a chunked wrapper and reassemble
    if (args.length > 0 && isChunkedWrapper(args[0])) {
      const reassembled = chunkReceiver.handleWrapper(args[0]);
      if (reassembled !== null) {
        // Replace args with reassembled payload
        args = [reassembled] as Parameters<ServerToClientEvents[E]>;
        console.log(`[SocketReceiver] Reassembled chunked message for event '${String(event)}'`);
      } else {
        console.error(`[SocketReceiver] Failed to reassemble chunked message for event '${String(event)}'`);
        return; // Don't process incomplete/failed reassembly
      }
    }

    // Check if this event has a request_id for profiling correlation
    // This handles events sent via sendEvent() with request_id that expect responses via listeners
    if (args.length > 0) {
      const firstArg = args[0];
      if (firstArg && typeof firstArg === 'object' && 'request_id' in firstArg) {
        const eventData = firstArg as unknown as { request_id?: unknown; error?: unknown; [key: string]: unknown };
        if (typeof eventData.request_id === 'string') {
          // Check if response contains error
          const hasError = 'error' in eventData &&
                          eventData.error !== null &&
                          eventData.error !== undefined &&
                          eventData.error !== '';
          profilingStore.endEvent(
            eventData.request_id,
            !hasError,
            hasError ? String(eventData.error) : undefined,
            eventData
          );
        }
      }
    }

    const handlers = this.handlers[event];
    if (!handlers?.length) {
      this.buffer.store(event, args);
      const quietEvents: Array<keyof ServerToClientEvents> = ['yjs:sync'];
      if (!quietEvents.includes(event)) {
        console.debug(`📥 Received event '${event}' but no handlers registered`);
      }
      return;
    }

    handlers.forEach(handler => {
      try {
        handler(...args);
      } catch (error) {
        console.error(`Error in handler for event '${event}':`, error);
      }
    });
  }

  private bufferCleanup<E extends keyof ServerToClientEvents>(event: E): void {
    this.buffer.compact(event);
  }

  private syncConnectionState(env: SocketEnvironment): SocketConnectionState {
    const socket = this.sockets.get(env);
    const current = this.connections.get(env);

    if (!socket) {
      if (current.status !== 'disconnected') {
        return this.connections.update(env, {
          status: 'disconnected',
          reconnectAttempt: undefined,
        });
      }
      return current;
    }

    const isConnected = socket.connected;
    const isActive = (socket as Socket & { active?: boolean }).active ?? false;
    const derivedStatus: SocketConnectionState['status'] = isConnected
      ? 'connected'
      : isActive
        ? 'connecting'
        : 'disconnected';

    if (current.status === derivedStatus) {
      return current;
    }

    const updates: Partial<SocketConnectionState> = {
      status: derivedStatus,
    };

    if (derivedStatus === 'connected') {
      updates.lastConnectedAt = Date.now();
      updates.reconnectAttempt = undefined;
      updates.lastError = undefined;
    } else if (derivedStatus === 'connecting') {
      updates.reconnectAttempt = current.reconnectAttempt ?? 0;
    } else if (derivedStatus === 'disconnected') {
      updates.lastDisconnectedAt = Date.now();
    }

    return this.connections.update(env, updates);
  }

  private ensureSocketConnected(env: SocketEnvironment): boolean {
    const socket = this.sockets.get(env);

    if (socket && !socket.connected) {
      const isSocketActive = (socket as Socket & { active?: boolean }).active ?? false;

      if (isSocketActive) {
        console.log(`[SocketReceiver] ${env} socket reconnecting via Socket.IO manager (no manual connect needed)`);
        return true;
      }

      console.log(`[SocketReceiver] Attempting manual reconnect for ${env} socket`);
      this.connections.update(env, { status: 'connecting', reconnectAttempt: 0 });
      socket.connect();
      return true;
    }

    if (socket?.connected) {
      this.syncConnectionState(env);
      return true;
    }

    const lazyConfig = this.lazyConfigs.get(env);
    if (lazyConfig) {
      console.log(`Initializing ${env} socket on-demand`);
      this.connections.update(env, { status: 'connecting', reconnectAttempt: 0 });
      this.initializeSocket(env, lazyConfig);
      const initialized = this.sockets.get(env);
      if (initialized && !initialized.connected) {
        const isSocketActive = (initialized as Socket & { active?: boolean }).active ?? false;
        if (!isSocketActive) {
          console.log(`[SocketReceiver] Lazy socket ${env} initialized but inactive, connecting now`);
          initialized.connect();
        } else {
          console.log(`[SocketReceiver] Lazy socket ${env} initialized and auto-reconnecting`);
        }
      }
      return this.sockets.get(env)?.connected ?? false;
    }

    this.syncConnectionState(env);
    return false;
  }

  updateAuth(env: SocketEnvironment): void {
    // Note: we intentionally do NOT overwrite `socket.auth` here anymore.
    // The auth callback installed at socket creation (see socket/config.ts)
    // already does an async `getSession()` pre-flight on every reconnect,
    // which is the canonical Supabase pattern for keeping a long-lived
    // socket authenticated as tokens refresh.
    //
    // This function now exists for two narrower purposes:
    //   1. Trigger a connect when SIGNED_IN/INITIAL_SESSION fires while the
    //      socket is idle (autoConnect: false).
    //   2. Stash auth on the lazy config so a not-yet-created socket picks
    //      it up at construction time.
    // The `newAuth` argument is retained for API compatibility but is no
    // longer the source of truth for what gets sent — `getSession()` is.
    const socket = this.sockets.get(env);
    if (socket) {
      console.log(`Updated auth for ${env} socket`);

      if (!socket.connected) {
        // Check socket.active to see if already connecting.
        // socket.active = true means socket is subscribed to Manager and waiting to connect.
        // After CONNECT_ERROR, socket.destroy() is called which sets active = false.
        // This allows retry after failure while preventing duplicate packets during active connection.
        const isSocketActive = (socket as Socket & { active?: boolean }).active ?? false;
        if (isSocketActive) {
          console.log(`[SocketReceiver] ${env} already connecting (socket.active=true), auth refresh will be applied on next handshake`);
          return;
        }

        console.log(`[SocketReceiver] ${env} socket not connected, triggering connect with new auth...`);
        this.connections.update(env, { status: 'connecting', reconnectAttempt: 0 });
        socket.connect();
      }
      this.syncConnectionState(env);
      return;
    }

    // Lazy path: socket hasn't been created yet. The original async auth
    // callback set by createSocketConfig is still in lazyConfig.options.auth
    // and will fire at handshake time when the socket is eventually built —
    // it'll do its own getSession() pre-flight then. Don't overwrite it
    // with a sync snapshot: that's exactly the regression we fixed for the
    // already-created socket case.
    this.syncConnectionState(env);
  }

  updateAllAuth(): void {
    // No payload: the handshake's async auth callback sources the token
    // itself. This exists to trigger connect() on idle sockets when the
    // session becomes available (see updateAuth).
    this.sockets.forEach((_, env) => {
      this.updateAuth(env);
    });
  }

  async sendAuthUpdate(): Promise<{ success: boolean; error?: string }> {
    const socket = this.sockets.get('API');

    if (!socket || !socket.connected) {
      console.warn('Cannot send auth update: API socket not connected');
      return { success: false, error: 'Socket not connected' };
    }

    // The payload is the fresh Supabase access token — same contract as the
    // handshake auth callback (docs/auth-refactor-spec.md). Sourced here
    // rather than passed in so no caller can ship a stale token.
    let token: string | undefined;
    try {
      const client = getExistingBrowserClient();
      if (client) {
        const { data } = await client.auth.getSession();
        token = data.session?.access_token;
      }
    } catch { /* fall through to the no-token error below */ }
    if (!token) {
      console.warn('Cannot send auth update: no active Supabase session');
      return { success: false, error: 'No active session' };
    }

    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        console.error('Auth update timeout - no response from server');
        resolve({ success: false, error: 'Request timeout' });
      }, 5000);

      const authData: Record<string, unknown> = { token };

      const emitAuthUpdate = socket.emit.bind(socket) as (
        event: 'update_auth',
        data: Record<string, unknown>,
        callback: (response: { success: boolean; error?: string; message?: string }) => void,
      ) => void;
      emitAuthUpdate('update_auth', authData, (response) => {
        clearTimeout(timeout);

        if (response.success) {
          console.log('✅ Auth update successful:', response.message);
        } else {
          console.error('❌ Auth update failed:', response.error);
        }

        resolve(response);
      });
    });
  }

  getSocket(env: SocketEnvironment): Socket<ServerToClientEvents, ClientToServerEvents> | null {
    this.ensureSocketConnected(env);
    return this.sockets.get(env) ?? null;
  }

  subscribeConnection(env: SocketEnvironment, handler: (state: SocketConnectionState) => void): () => void {
    this.syncConnectionState(env);
    return this.connections.subscribe(env, handler);
  }

  getConnectionState(env: SocketEnvironment): SocketConnectionState {
    return this.syncConnectionState(env);
  }

  sendEvent<K extends keyof ClientToServerEvents>(
    event: K,
    ...args: ClientToServerEvents[K] extends (data: infer D) => void ? [data: D, env?: SocketEnvironment] : [env?: SocketEnvironment]
  ): boolean {
    const payload = args[0];
    const envOverride = args.length > 1 ? (args[1] as SocketEnvironment | undefined) : undefined;
    const routing = EventRouting as Partial<Record<keyof ClientToServerEvents, SocketEnvironment>>;
    const env: SocketEnvironment = envOverride || routing[event] || 'API';

    if (!this.ensureSocketConnected(env)) {
      if (event !== 'yjs:sync') {
        console.warn(`Cannot send event '${String(event)}': ${env} socket not connected`);
      }
      return false;
    }

    const socket = this.sockets.get(env);
    if (!socket) {
      return false;
    }

    try {
      if (process.env.NODE_ENV === 'development') {
        const quietEvents = ['yjs:sync', 'chat:audio:chunk'];
        if (!quietEvents.includes(event as string)) {
          console.debug(`📤 Sending event '${String(event)}' via ${env}:`, payload);
        }
      }

      // Chunk payload if needed (transparent for all events)
      const chunkedPayload = typeof payload === 'undefined'
        ? payload
        : maybeChunk((chunk) => socket.emit('__chunk__', chunk), payload);
      const payloadArgs: unknown[] = typeof chunkedPayload === 'undefined' ? [] : [chunkedPayload];
      socket.emit(event, ...(payloadArgs as Parameters<ClientToServerEvents[K]>));
      return true;
    } catch (error) {
      console.error(`Failed to send event '${String(event)}':`, error);
      return false;
    }
  }

  on<K extends keyof ServerToClientEvents>(event: K, handler: EventHandler<K>): () => void {
    if (!this.handlers[event]) {
      this.handlers[event] = [];
    }

    const handlers = this.handlers[event] as EventHandler<K>[];
    handlers.push(handler);

    this.buffer.replay(event, handler as (...args: Parameters<ServerToClientEvents[K]>) => void);

    return () => {
      const current = this.handlers[event];
      if (!current) {
        return;
      }

      const typed = current as EventHandler<K>[];
      const index = typed.indexOf(handler);
      if (index !== -1) {
        typed.splice(index, 1);
      }
    };
  }

  off<K extends keyof ServerToClientEvents>(event: K, handler: EventHandler<K>): void {
    const current = this.handlers[event];
    if (!current) {
      return;
    }

    const typed = current as EventHandler<K>[];
    const index = typed.indexOf(handler);
    if (index !== -1) {
      typed.splice(index, 1);
    }
  }

  removeAllListeners(event?: keyof ServerToClientEvents): void {
    if (event) {
      delete this.handlers[event];
      this.buffer.clear(event);
      return;
    }

    this.handlers = {};
    this.buffer.clear();
  }

  /**
   * Inject an event from an external source (e.g., Event Relay WebSocket).
   * This allows non-Socket.IO connections to route events through the same handler system.
   */
  injectEvent<K extends keyof ServerToClientEvents>(
    event: K,
    ...args: Parameters<ServerToClientEvents[K]>
  ): void {
    this.handleEvent(event, args);
  }

  /** Bridge an event decoded from an untyped JSON transport. Callers must
   * validate the event name before reaching this boundary; Socket.IO's typed
   * path should continue to use injectEvent so name/payload correlation is
   * checked at compile time. */
  injectWireEvent(event: keyof ServerToClientEvents, payload: unknown): void {
    const handleWireEvent = this.handleEvent.bind(this) as (
      event: keyof ServerToClientEvents,
      args: [unknown],
    ) => void;
    handleWireEvent(event, [payload]);
  }
}

class SocketReceiverSingleton extends SocketReceiver {
  constructor() {
    super();
    if (typeof window !== 'undefined') {
      // Start chunk receiver cleanup task
      chunkReceiver.start();

      queueMicrotask(() => {
        this.connect();
      });
    }
  }
}

export const socketReceiver = new SocketReceiverSingleton();

export function onSocketEvent<K extends keyof ServerToClientEvents>(
  event: K,
  handler: EventHandler<K>
): () => void {
  return socketReceiver.on(event, handler);
}

export function offSocketEvent<K extends keyof ServerToClientEvents>(
  event: K,
  handler: EventHandler<K>
): void {
  socketReceiver.off(event, handler);
}

const pendingCallbacks = new Map<string, (data: unknown) => void>();

export function registerRequestCallback(requestId: string, callback: (data: unknown) => void): void {
  pendingCallbacks.set(requestId, callback);
}

export function cleanupRequestCallback(requestId: string): void {
  pendingCallbacks.delete(requestId);
}

onSocketEvent('response', (response) => {
  console.log(`[SOCKET_RECEIVER] Received response for request_id: ${response.request_id}`);
  const callback = pendingCallbacks.get(response.request_id);
  if (callback) {
    if (response.error) {
      console.error(`Request ${response.request_id} failed:`, response.error);
      // Call callback with error so handlers can process it (e.g., idempotent operations)
      console.log(`[SOCKET_RECEIVER] Calling callback with error:`, { error: response.error });
      callback({ error: response.error });
    } else {
      console.log(`[SOCKET_RECEIVER] Calling callback with data:`, response.data);
      callback(response.data);
    }
    pendingCallbacks.delete(response.request_id);
  } else {
    console.warn(`[SOCKET_RECEIVER] No callback found for request_id: ${response.request_id}`);
  }
});

export function onServerData(dataType: string, callback: (data: ServerDataEvent['data']) => void): () => void {
  const handler = (event: ServerDataEvent) => {
    if (event.data_type === dataType && !event.error) {
      callback(event.data);
    }
  };

  return onSocketEvent('server:data', handler);
}

export type { SocketEnvironment };
export type { SocketConnectionState } from './socket/types';
