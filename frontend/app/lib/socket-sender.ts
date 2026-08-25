/**
 * Socket sender that mirrors the backend's pattern exactly.
 * Parses event_name from event objects and routes them appropriately.
 * Includes support for request/response correlation via callbacks with full type safety.
 */

import { socketReceiver, registerRequestCallback, cleanupRequestCallback } from './socket-receiver';
import type {
  ClientToServerEvents,
  SocketEnvironment,
  RequestResponseMap
} from '~/types/socket-events.generated';
import { ClientEventNames } from '~/types/socket-events.generated';
import { profilingStore } from './profiling-store';
import { trackSendDropped } from './telemetry-socket';

// Type for any event object that includes its event_name
export type EventWithName = {
  event_name: keyof ClientToServerEvents;
  request_id?: string | null;
  tag?: string; // Optional human-readable label for profiling
  [key: string]: any;
};

type InferredResponse<E extends EventWithName> =
  E extends { event_name: infer EventName }
    ? EventName extends keyof EventNameToRequestType
      ? EventNameToRequestType[EventName] extends keyof RequestResponseMap
        ? RequestResponseMap[EventNameToRequestType[EventName]]
        : unknown
      : unknown
    : unknown;

/** Every request can fail at the transport/router layer before its domain
 * response is constructed. Model that common envelope once instead of making
 * every generated Pydantic response pretend it owns transport errors. */
type WithSocketError<T> = T extends object ? T & { error?: string } : T;

/** `T` is the optional manual response override. `never` keeps inference from
 * the request event, while `sendEventAsync<MyResponse>(...)` does what its docs
 * have always promised instead of treating `MyResponse` as the event type. */
type ResolvedResponse<T, E extends EventWithName> = WithSocketError<
  [T] extends [never] ? InferredResponse<E> : T
>;

/**
 * Send an event object that contains its own event_name.
 * This exactly mirrors the backend pattern where event objects know their type.
 * 
 * @param event - Event object with event_name property
 * @param env - Optional environment override (defaults to EventRouting config)
 * @returns true if sent successfully, false if not connected
 * 
 * @example
 * import { ChatMessageRequest } from '~/types/socket-events.generated';
 *
 * // Create and send an event (just like Python)
 * const event = ChatMessageRequest.create({
 *   content: [{ type: 'text', text: 'Hello world' }],
 *   model: 'gpt-4o'
 * });
 * sendEvent(event);
 *
 * // Or inline
 * sendEvent(ChatMessageRequest.create({
 *   content: [{ type: 'text', text: 'Hello' }],
 *   model: 'gpt-4o'
 * }));
 */
export function sendEvent(event: EventWithName, env?: SocketEnvironment): boolean {
  const { event_name, tag, ...data } = event;

  // Track events that have request_id for profiling (even if they don't use callbacks)
  // These events expect responses via socket listeners (onSocketEvent pattern)
  const requestId = event.request_id;
  if (requestId && typeof requestId === 'string') {
    // Start profiling - response will be tracked by socket-receiver when it arrives
    profilingStore.startEvent(requestId, event_name as string, event, tag);
  }

  // Stamp the client-side wall clock so the BE receiver can compute the
  // FE→BE wire latency on every socket event (see receiver._stamp_wire_latency).
  // The receiver pops this key off before handler validation; Pydantic models
  // use extra='allow' anyway so this is safe even for events that route to
  // typed request schemas. Underscore prefix marks it as transport metadata.
  const clientSentAtMs = Date.now();

  // Handle events where the backend expects raw data (not an object)
  // These are events where our companion objects wrap the data in a 'data' property
  // Check if there's only one property and it's called 'data'
  const dataKeys = Object.keys(data);
  let ok: boolean;
  if (dataKeys.length === 1 && dataKeys[0] === 'data') {
    // Send the raw data directly. Only inject the timing stamp when the
    // inner value is a PLAIN object — spreading anything else corrupts it:
    // a Uint8Array (yjs:sync updates) spread into {'0':.., '1':..} and every
    // collaborative sync frame failed backend validation until 2026-07-19.
    const rawData = (data as any).data;
    const isPlainObject =
      rawData &&
      typeof rawData === 'object' &&
      !Array.isArray(rawData) &&
      !ArrayBuffer.isView(rawData) &&
      !(rawData instanceof ArrayBuffer);
    const payload = isPlainObject
      ? { ...rawData, _client_sent_at_ms: clientSentAtMs }
      : rawData;
    ok = socketReceiver.sendEvent(event_name as any, payload, env);
  } else {
    // For all other events, send the data object with timing stamp.
    ok = socketReceiver.sendEvent(
      event_name as any,
      { ...data, _client_sent_at_ms: clientSentAtMs } as any,
      env,
    );
  }
  if (!ok) {
    // Surface dropped sends so we can answer "how often does a send fail
    // because the socket was down". yjs:sync is high-volume background
    // chatter — its failures during a disconnect aren't user-actionable.
    if (event_name !== 'yjs:sync') {
      trackSendDropped(event_name as string);
    }
  }
  return ok;
}

/**
 * Send an event with a callback for the response.
 * Automatically generates a request_id and tracks the callback.
 * If the event has a known request type, the response type is automatically inferred.
 * 
 * @param event - Event object with event_name property
 * @param callback - Function to call when response is received
 * @param env - Optional environment override
 * @returns Cleanup function to cancel the callback
 * 
 * @example
 * // With automatic type inference (for known request types)
 * sendEventWithCallback(
 *   UserDatabaseListTablesRequest.create({}),
 *   (response) => {
 *     // response is automatically typed as UserDatabaseListTablesResponse
 *     setTables(response.tables);
 *   }
 * );
 * 
 * // With manual type specification (for custom types)
 * sendEventWithCallback<CustomType>(
 *   someEvent,
 *   (response) => {
 *     // response is typed as CustomType
 *   }
 * );
 */
export function sendEventWithCallback<
  T = never,
  E extends EventWithName = EventWithName,
>(
  event: E,
  callback: (data: ResolvedResponse<T, E>) => void,
  env?: SocketEnvironment,
  _internalRequestId?: string // Internal use only for timeout tracking
): () => void {
  const requestId = _internalRequestId || crypto.randomUUID();
  const eventWithId = { ...event, request_id: requestId };

  // Start profiling with request data and optional tag
  profilingStore.startEvent(requestId, event.event_name as string, event, event.tag);

  // Wrap callback to record completion
  const wrappedCallback = (data: ResolvedResponse<T, E>) => {
    // Check if response contains error
    const hasError = data && typeof data === 'object' && 'error' in data && data.error;
    profilingStore.endEvent(
      requestId,
      !hasError,
      hasError ? String((data as any).error) : undefined,
      data // Store response data
    );
    callback(data);
  };

  registerRequestCallback(requestId, (data) => {
    wrappedCallback(data as ResolvedResponse<T, E>);
  });

  // Send event
  sendEvent(eventWithId, env);

  // Return cleanup function
  return () => {
    cleanupRequestCallback(requestId);
  };
}

/**
 * Send an event and wait for the response.
 * Returns a Promise that resolves with the response data.
 * If the event has a known request type, the response type is automatically inferred.
 * 
 * @param event - Event object with event_name property
 * @param env - Optional environment override
 * @param timeout - Optional timeout in milliseconds (default: 30000)
 * @returns Promise resolving to the response data
 * 
 * @example
 * // With automatic type inference (for known request types)
 * const response = await sendEventAsync(
 *   SqlExecuteRequest.create({ query: 'SELECT * FROM users' })
 * );
 * // response is automatically typed as SqlExecuteResponse
 * console.log(response.rows);
 * 
 * // With manual type specification (for custom types)
 * const response = await sendEventAsync<CustomType>(someEvent);
 */
export async function sendEventAsync<
  T = never,
  E extends EventWithName = EventWithName,
>(
  event: E,
  env?: SocketEnvironment,
  timeout = 30000,
  // Pre-generated request_id from the caller. Lets callers correlate the
  // wire request_id with their own bookkeeping (e.g. telemetry latency
  // spans) instead of having to read it back from a generated id they
  // never get to see.
  presetRequestId?: string,
): Promise<ResolvedResponse<T, E>> {
  const requestId = presetRequestId || crypto.randomUUID();

  return new Promise<ResolvedResponse<T, E>>((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      cleanup();
      // Record timeout in profiling (no response data)
      profilingStore.endEvent(requestId, false, 'Request timeout', undefined);
      reject(new Error('Request timeout'));
    }, timeout);

    const cleanup = sendEventWithCallback<T, E>(
      event,
      (data) => {
        clearTimeout(timeoutId);
        resolve(data);
      },
      env,
      requestId // Pass requestId to avoid generating a new one
    );
  });
}

// Re-export all event creators and types from generated file
export * from '~/types/socket-events.generated';

// Create reverse mapping from event names to request types using existing generated data
type EventNameToRequestType = {
  [K in keyof typeof ClientEventNames as typeof ClientEventNames[K]]: K;
};
