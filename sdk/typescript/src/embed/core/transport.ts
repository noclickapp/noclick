// Abstract transport interface for SDK ↔ host communication.
// Implementations: PostMessageTransport (iframe), WebSocketTransport (external apps).

export interface TransportEventMap {
  'noclick:response': { id: string; result?: unknown; error?: string };
  'noclick:stream': { id: string; event: 'output' | 'error' | 'done'; nodeId?: string; data?: unknown };
  'noclick:event': { event: string; data: unknown };
}

export interface Transport {
  /** Send a message to the host/backend. */
  send(msg: Record<string, unknown>): void;
  /** Register a handler for incoming messages. Returns unsubscribe function. */
  onMessage(handler: (msg: TransportEventMap[keyof TransportEventMap] & { type: string }) => void): () => void;
  /** Clean up resources (close connections, remove listeners). */
  destroy(): void;
}

// --- Internal request/response infrastructure ---

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
};

type StreamHandler = {
  onOutput?: (nodeId: string, data: unknown) => void;
  onError?: (nodeId: string, error: string) => void;
  onDone?: () => void;
  allResolve?: (results: Record<string, unknown>) => void;
  allReject?: (error: Error) => void;
  collected: Record<string, unknown>;
};

type EventHandler = (data: unknown) => void;

let transport: Transport | null = null;
let reqCounter = 0;
const pending = new Map<string, PendingRequest>();
const streams = new Map<string, StreamHandler>();
const eventListeners = new Map<string, Set<EventHandler>>();
let messageUnsub: (() => void) | null = null;

const DEFAULT_TIMEOUT_MS = 30000;
const DEFAULT_STREAM_TIMEOUT_MS = 60000;

function nextId(): string {
  return `req-${++reqCounter}-${Date.now().toString(36)}`;
}

function handleIncoming(msg: TransportEventMap[keyof TransportEventMap] & { type: string }) {
  if (!msg || typeof msg !== 'object' || typeof msg.type !== 'string') return;
  if (!msg.type.startsWith('noclick:')) return;

  if (msg.type === 'noclick:response') {
    const resp = msg as TransportEventMap['noclick:response'] & { type: string };
    const req = pending.get(resp.id);
    if (!req) return;
    pending.delete(resp.id);
    if (resp.error) {
      req.reject(new Error(resp.error));
    } else {
      req.resolve(resp.result);
    }
  } else if (msg.type === 'noclick:stream') {
    const s = msg as TransportEventMap['noclick:stream'] & { type: string };
    const handler = streams.get(s.id);
    if (!handler) return;
    if (s.event === 'output' && s.nodeId) {
      handler.collected[s.nodeId] = s.data;
      handler.onOutput?.(s.nodeId, s.data);
    } else if (s.event === 'error' && s.nodeId) {
      handler.onError?.(s.nodeId, s.data as string);
      handler.allReject?.(new Error(`Stream error on node ${s.nodeId}: ${s.data}`));
      streams.delete(s.id);
    } else if (s.event === 'done') {
      handler.onDone?.();
      handler.allResolve?.(handler.collected);
      streams.delete(s.id);
    }
  } else if (msg.type === 'noclick:event') {
    const e = msg as TransportEventMap['noclick:event'] & { type: string };
    const listeners = eventListeners.get(e.event);
    if (listeners) {
      listeners.forEach(fn => fn(e.data));
    }
  }
}

// --- Public API used by all SDK modules ---

/** Set the active transport. Called by init(). */
export function setTransport(t: Transport): void {
  // Clean up previous transport
  if (messageUnsub) messageUnsub();
  if (transport) transport.destroy();

  // Reject anything in flight against the old transport — its responses can no
  // longer arrive (the handler is being rebound), so without this they'd hang
  // until their own timeout (and a stream with no .all() caller never settles).
  if (transport) {
    const err = new Error('@noclick/sdk transport was replaced');
    for (const [, req] of pending) req.reject(err);
    pending.clear();
    for (const [, s] of streams) s.allReject?.(err);
    streams.clear();
  }

  transport = t;
  messageUnsub = transport.onMessage(handleIncoming);
}

/** Get the active transport (throws if not initialized). */
export function getTransport(): Transport {
  if (!transport) throw new Error('@noclick/sdk not initialized. Call init() first.');
  return transport;
}

/** Whether the SDK has been initialized with a transport. */
export function isInitialized(): boolean {
  return transport !== null;
}

/** Send a request and wait for a response. Times out after 30s by default. */
export function request<T = unknown>(method: string, params: Record<string, unknown> = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const t = getTransport();
  const id = nextId();
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`SDK request '${method}' timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    pending.set(id, {
      resolve: (v: unknown) => { clearTimeout(timer); resolve(v as T); },
      reject: (e: Error) => { clearTimeout(timer); reject(e); },
    });
    t.send({ type: 'noclick:request', id, method, params });
  });
}

/** Send a fire-and-forget request (no response expected). */
export function send(method: string, params: Record<string, unknown> = {}): void {
  const t = getTransport();
  t.send({ type: 'noclick:fire', method, params });
}

export interface ExecutionStream {
  on(event: 'output', handler: (nodeId: string, data: unknown) => void): ExecutionStream;
  on(event: 'error', handler: (nodeId: string, error: string) => void): ExecutionStream;
  on(event: 'done', handler: () => void): ExecutionStream;
  /** Await all target outputs at once. */
  all(): Promise<Record<string, unknown>>;
}

/** Send a request that returns a stream of events. */
export function requestStream(method: string, params: Record<string, unknown> = {}, timeoutMs = DEFAULT_STREAM_TIMEOUT_MS): ExecutionStream {
  const t = getTransport();
  const id = nextId();
  const handler: StreamHandler = { collected: {} };

  const allPromise = new Promise<Record<string, unknown>>((resolve, reject) => {
    const timer = setTimeout(() => {
      streams.delete(id);
      reject(new Error(`SDK stream '${method}' timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    handler.allResolve = (results) => { clearTimeout(timer); resolve(results); };
    handler.allReject = (error) => { clearTimeout(timer); reject(error); };
  });

  streams.set(id, handler);
  t.send({ type: 'noclick:request', id, method, params });

  const stream: ExecutionStream = {
    on(event: string, fn: (...args: unknown[]) => void) {
      if (event === 'output') handler.onOutput = fn as StreamHandler['onOutput'];
      else if (event === 'error') handler.onError = fn as StreamHandler['onError'];
      else if (event === 'done') handler.onDone = fn as StreamHandler['onDone'];
      return stream;
    },
    all: () => allPromise,
  };

  return stream;
}

/** Subscribe to push events from the host. Returns an unsubscribe function. */
export function subscribe(event: string, handler: EventHandler): () => void {
  if (!eventListeners.has(event)) {
    eventListeners.set(event, new Set());
  }
  eventListeners.get(event)!.add(handler);
  return () => eventListeners.get(event)?.delete(handler);
}
