// MockSocket — fake Socket.IO client that the test drives.
//
// Why this exists: integration tests need to mount real React, real
// Valtio stores, real socket-receiver wiring — but with a controllable
// "BE" so the test can simulate streaming, paused-on-ask, terminal,
// snapshot-on-reconnect, etc. at exact times. MockSocket plugs into
// `socketReceiver.sockets.get('API')` so all outgoing emits from
// `sendEvent(...)` land here, and incoming socket events are driven
// via `serverEmit(name, data)` which routes through
// `socketReceiver.injectEvent` (the same path the relay uses).
//
// Captures every outgoing emit with a timestamp so tests can assert
// what the FE tried to send to the BE.

import { socketReceiver } from '~/lib/socket-receiver';
import type { ServerToClientEvents } from '~/types/socket-events.generated';

export interface CapturedEmit {
    name: string;
    data: unknown;
    /** ms since the test started (set by the harness). */
    t: number;
}

type ReplyResolver = (req: unknown) => unknown;

export class MockSocket {
    sentEvents: CapturedEmit[] = [];
    connected = true;
    id = 'mock-sid';
    listeners = new Map<string, Array<(...args: unknown[]) => void>>();
    private _replyHandlers = new Map<string, ReplyResolver>();

    /** Captures FE → BE sends. Mirrors socket.io-client signature. If
     *  the test registered a `replyTo(name, ...)` handler for this event
     *  AND the payload carries a `request_id`, schedule a `response`
     *  frame on the next microtask. */
    emit = (name: string, data?: unknown, _ack?: unknown): boolean => {
        this.sentEvents.push({ name, data, t: this._now() });
        const handler = this._replyHandlers.get(name);
        if (handler) {
            const reqId = data && typeof data === 'object'
                ? (data as { request_id?: string }).request_id
                : undefined;
            if (reqId) {
                queueMicrotask(() => {
                    this.serverEmit('response', { request_id: reqId, data: handler(data) });
                });
            }
        }
        return true;
    };

    /** Register an auto-responder for outgoing event `name`. When the
     *  FE emits this event with a `request_id`, the mock replies via
     *  the `response` channel with `data` (or `data(req)` for dynamic
     *  payloads). Replaces any previously-registered handler. Pass a
     *  resolver function when the response depends on the request. */
    replyTo<T = unknown>(name: string, data: T | ((req: unknown) => T)): this {
        const resolver: ReplyResolver = typeof data === 'function'
            ? data as ReplyResolver
            : () => data;
        this._replyHandlers.set(name, resolver);
        return this;
    }

    onAny = (_handler: (...args: unknown[]) => void): this => this;
    onAnyOutgoing = (_handler: (...args: unknown[]) => void): this => this;

    on(event: string, handler: (...args: unknown[]) => void): this {
        const list = this.listeners.get(event) || [];
        list.push(handler);
        this.listeners.set(event, list);
        return this;
    }

    off(event: string, handler?: (...args: unknown[]) => void): this {
        if (!handler) {
            this.listeners.delete(event);
        } else {
            const list = this.listeners.get(event) || [];
            this.listeners.set(event, list.filter(h => h !== handler));
        }
        return this;
    }

    /** Drive a BE-side event INTO the FE. Routes through socketReceiver
     *  so all `onSocketEvent`/store listeners get the same payload they
     *  would in production. */
    serverEmit(name: string, data: unknown): void {
        // socket-receiver injectEvent dispatches to its handler map.
        socketReceiver.injectWireEvent(
            name as keyof ServerToClientEvents,
            data,
        );
    }

    /** Convenience: assert FE emitted a specific event by name; throws
     *  with a helpful diff if not. Returns the matching emit so the
     *  caller can inspect payload. */
    expectSent(name: string, predicate?: (data: unknown) => boolean): CapturedEmit {
        const match = this.sentEvents.find(
            e => e.name === name && (!predicate || predicate(e.data)),
        );
        if (!match) {
            const summary = this.sentEvents
                .map(e => `${e.name}@${e.t}ms`)
                .join(', ');
            throw new Error(
                `Expected FE to emit '${name}' but only saw: [${summary}]`,
            );
        }
        return match;
    }

    /** True when the FE has emitted the named event at least once. */
    hasSent(name: string): boolean {
        return this.sentEvents.some(e => e.name === name);
    }

    clearSent(): void {
        this.sentEvents = [];
    }

    clearReplyHandlers(): void {
        this._replyHandlers.clear();
    }

    private _testStartedAt = Date.now();
    private _now(): number {
        return Date.now() - this._testStartedAt;
    }
    resetClock(): void {
        this._testStartedAt = Date.now();
    }
}

/** Install a MockSocket as the API/main socket on the global
 *  `socketReceiver` singleton. Returns the mock + a teardown
 *  function the test should call in `afterEach`. */
export function installMockSocket(): { socket: MockSocket; teardown: () => void } {
    const mock = new MockSocket();
    // Reach into the receiver to patch its internal map. The receiver
    // exports the singleton as a class instance; sockets is a Map keyed
    // on env. We cast through `any` since this is test-only surgery.
    const sr = socketReceiver as unknown as {
        sockets: Map<string, unknown>;
        ensureSocketConnected: (env: string) => boolean;
    };
    const origSocketsValue = sr.sockets.get('API');
    const origEnsure = sr.ensureSocketConnected.bind(sr);
    sr.sockets.set('API', mock);
    sr.ensureSocketConnected = () => true;

    const teardown = () => {
        if (origSocketsValue !== undefined) {
            sr.sockets.set('API', origSocketsValue);
        } else {
            sr.sockets.delete('API');
        }
        sr.ensureSocketConnected = origEnsure;
        mock.sentEvents = [];
        mock.listeners?.clear?.();
    };

    return { socket: mock, teardown };
}
