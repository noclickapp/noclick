// Anonymous Socket.IO connection for the public shared-agent page
// (/a/{linkId}). Deliberately separate from the authenticated app singleton:
// it authenticates with {share_link_id, visitor_id} instead of cookies (the
// backend mints a restricted session limited to shared_agent:* events), keeps
// its own request/response correlation, and never imports socket/config.ts or
// socket-receiver (which drag supabase-client + the global handler map into
// the public bundle).

import { io, type Socket } from 'socket.io-client';
import { BASE_SOCKET_OPTIONS } from './base-options';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { chunkReceiver, isChunkedWrapper, type ChunkMetadata } from './chunk-receiver';

export interface ShareSocketAuth {
  share_link_id: string;
  visitor_id: string;
}

/** Server→client events the public page consumes. Everything else the
 *  backend might emit at this sid is ignored by construction. */
const SHARE_SOCKET_EVENTS = [
  'chat:message',
  'agent:state',
  'credits:exhausted',
  'response',
  'error',
] as const;

export type ShareSocketEvent = (typeof SHARE_SOCKET_EVENTS)[number];

type Handler = (data: unknown) => void;

export type ShareSocketStatus = 'connecting' | 'connected' | 'disconnected';

interface PendingRequest {
  resolve: (data: unknown) => void;
  reject: (err: Error) => void;
  timeoutId: ReturnType<typeof setTimeout>;
}

export class ShareSocket {
  private socket: Socket;
  private handlers = new Map<string, Set<Handler>>();
  private pending = new Map<string, PendingRequest>();
  private statusListeners = new Set<(status: ShareSocketStatus) => void>();
  private disposed = false;

  constructor(auth: ShareSocketAuth) {
    this.socket = io(apiBaseUrl(), {
      ...BASE_SOCKET_OPTIONS,
      autoConnect: true,
      // Static auth object — socket.io re-sends it on every reconnect
      // handshake. Never cookies: a logged-in visitor still chats as an
      // anonymous visitor on this surface.
      auth,
    });

    // Chunk frames for >1MiB payloads (e.g. a long resume). Without this the
    // wrapper below would never resolve into the real payload.
    this.socket.on('__chunk__', (data: ChunkMetadata) => chunkReceiver.handleChunk(data));

    for (const event of SHARE_SOCKET_EVENTS) {
      this.socket.on(event, (raw: unknown) => {
        const payload = isChunkedWrapper(raw) ? chunkReceiver.handleWrapper(raw) : raw;
        if (payload == null) return;
        if (event === 'response') this.resolveResponse(payload);
        for (const handler of this.handlers.get(event) ?? []) {
          try {
            handler(payload);
          } catch (err) {
            console.error(`[ShareSocket] handler for ${event} threw`, err);
          }
        }
      });
    }

    this.socket.on('connect', () => this.emitStatus('connected'));
    this.socket.on('disconnect', () => this.emitStatus('disconnected'));
    this.socket.io.on('reconnect_attempt', () => this.emitStatus('connecting'));
  }

  private emitStatus(status: ShareSocketStatus) {
    for (const cb of this.statusListeners) cb(status);
  }

  private resolveResponse(payload: unknown) {
    const p = payload as { request_id?: string; data?: unknown; error?: string };
    if (!p || typeof p !== 'object' || !p.request_id) return;
    const pending = this.pending.get(p.request_id);
    if (!pending) return;
    this.pending.delete(p.request_id);
    clearTimeout(pending.timeoutId);
    // Mirror sendEventAsync: resolve with ResponseEvent.data (in-band errors
    // ride inside data; a top-level error with no data still resolves so the
    // caller sees the shape it asked for).
    if (p.data === undefined && p.error) {
      pending.reject(new Error(p.error));
    } else {
      pending.resolve(p.data);
    }
  }

  /** Subscribe to a server event. Returns an unsubscribe function. */
  on(event: ShareSocketEvent, handler: (data: never) => void): () => void {
    const set = this.handlers.get(event) ?? new Set();
    set.add(handler as Handler);
    this.handlers.set(event, set);
    return () => {
      set.delete(handler as Handler);
    };
  }

  /** Emit a request event and resolve with its ResponseEvent.data. `event`
   *  is a generated event-creator object carrying its own event_name. */
  request<T>(
    event: { event_name: string; request_id?: string | null; [key: string]: unknown },
    timeoutMs = 30000,
  ): Promise<T> {
    const requestId = (event.request_id as string | undefined) || crypto.randomUUID();
    const { event_name, ...data } = event;
    return new Promise<T>((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error('Request timeout'));
      }, timeoutMs);
      this.pending.set(requestId, {
        resolve: resolve as (data: unknown) => void,
        reject,
        timeoutId,
      });
      this.socket.emit(event_name, { ...data, request_id: requestId });
    });
  }

  getStatus(): ShareSocketStatus {
    if (this.socket.connected) return 'connected';
    return this.disposed ? 'disconnected' : 'connecting';
  }

  onStatus(cb: (status: ShareSocketStatus) => void): () => void {
    this.statusListeners.add(cb);
    return () => {
      this.statusListeners.delete(cb);
    };
  }

  dispose(): void {
    this.disposed = true;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timeoutId);
      pending.reject(new Error('Socket disposed'));
    }
    this.pending.clear();
    this.handlers.clear();
    this.statusListeners.clear();
    this.socket.removeAllListeners();
    this.socket.disconnect();
  }
}
