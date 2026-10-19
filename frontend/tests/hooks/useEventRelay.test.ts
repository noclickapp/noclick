// @vitest-environment jsdom
// A user-events relay viewer proves it is the user with its first frame: a short-lived token minted over the app's
// socket, never put in the relay URL. Every connect sends one, a live token is reused, and one near expiry or refused
// by the relay is replaced with a fresh mint on the next connect. A mint that fails is retried with backoff, and a
// connection that still has no token after a few tries starts over, so a tab never sits unauthenticated.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';

const { sendEventAsync, injectWireEvent } = vi.hoisted(() => ({
    sendEventAsync: vi.fn(),
    injectWireEvent: vi.fn(),
}));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync }));
vi.mock('~/lib/socket-receiver', () => ({
    socketReceiver: { injectWireEvent },
}));
vi.mock('~/lib/hostedDefaults', () => ({
    relayBaseUrl: () => 'wss://relay.test',
}));

type Listener = (event: unknown) => void;

// Hoisted with the mock that returns it (vi.mock runs before module-level code).
const { FakeRelaySocket } = vi.hoisted(() => {
    class FakeRelaySocket {
        static OPEN = 1;
        static CLOSED = 3;
        static instances: FakeRelaySocket[] = [];

        readyState = 0;
        sent: unknown[] = [];
        private listeners = new Map<string, Listener[]>();

        constructor(public url: string) {
            FakeRelaySocket.instances.push(this);
        }

        addEventListener(type: string, listener: Listener) {
            this.listeners.set(type, [
                ...(this.listeners.get(type) ?? []),
                listener,
            ]);
        }

        send(data: unknown) {
            this.sent.push(data);
        }

        close() {
            this.readyState = FakeRelaySocket.CLOSED;
        }

        reconnects: unknown[][] = [];

        reconnect(...args: unknown[]) {
            this.reconnects.push(args);
        }

        emit(type: string, event: unknown = {}) {
            for (const listener of this.listeners.get(type) ?? [])
                listener(event);
        }

        /** One underlying connection opening (partysocket re-emits `open` on every reconnect). */
        connect() {
            this.readyState = FakeRelaySocket.OPEN;
            this.emit('open');
        }

        drop() {
            this.readyState = 0;
            this.emit('close', { code: 1006, reason: '' });
        }

        receive(message: object) {
            this.emit('message', { data: JSON.stringify(message) });
        }

        authFrames(): string[] {
            return this.sent
                .filter(
                    (frame): frame is string =>
                        typeof frame === 'string' && frame.startsWith('{')
                )
                .map((frame) => JSON.parse(frame))
                .filter((frame) => frame.type === 'auth')
                .map((frame) => frame.token);
        }
    }
    return { FakeRelaySocket };
});
vi.mock('partysocket/ws', () => ({ default: FakeRelaySocket }));

import { useEventRelay } from '~/hooks/useEventRelay';
import { forgetUserRelayToken } from '~/lib/relayToken';

const NOW_S = Date.parse('2026-10-14T12:00:00Z') / 1000;
let minted = 0;
let sessionUser = 'user-1';
// What the next mints do before they succeed: time out, or come back refused (a rate limit).
let mintFailures: Array<'timeout' | 'refused'> = [];

const flush = () =>
    act(async () => void (await vi.advanceTimersByTimeAsync(0)));

function connectedRelay(userId = 'user-1') {
    renderHook(() => useEventRelay({ userId }));
    return FakeRelaySocket.instances.at(-1)!;
}

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW_S * 1000);
    FakeRelaySocket.instances = [];
    forgetUserRelayToken();
    minted = 0;
    sessionUser = 'user-1';
    mintFailures = [];
    sendEventAsync.mockImplementation(
        async (request: { event_name?: string }) => {
            if (request.event_name !== 'relay:user_token')
                return { error: 'unexpected' };
            const failure = mintFailures.shift();
            if (failure === 'timeout') throw new Error('Request timeout');
            if (failure === 'refused')
                return { error: 'rate_limit', message: 'Rate limit exceeded' };
            minted += 1;
            return {
                success: true,
                token: `token-${minted}`,
                expires_at: Math.floor(Date.now() / 1000) + 300,
                user_id: sessionUser,
            };
        }
    );
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
    sendEventAsync.mockReset();
    injectWireEvent.mockReset();
});

describe('useEventRelay authentication', () => {
    it('sends a minted token as the first frame, never in the URL', async () => {
        const ws = connectedRelay('user-1');
        expect(ws.url).toBe('wss://relay.test/user-1');

        ws.connect();
        await flush();

        expect(sendEventAsync).toHaveBeenCalledTimes(1);
        expect(sendEventAsync.mock.calls[0][0]).toMatchObject({
            event_name: 'relay:user_token',
        });
        expect(ws.authFrames()).toEqual(['token-1']);
        expect(ws.url).not.toContain('token');
        // One mint can't outlast the relay's 30s auth deadline.
        expect(sendEventAsync.mock.calls[0][2]).toBe(8000);
    });

    it('retries a failed mint with backoff and authenticates once one succeeds', async () => {
        mintFailures = ['timeout', 'refused'];
        const ws = connectedRelay();
        ws.connect();
        await flush();
        expect(sendEventAsync).toHaveBeenCalledTimes(1);
        expect(ws.authFrames()).toEqual([]);

        await act(async () => void (await vi.advanceTimersByTimeAsync(999)));
        expect(sendEventAsync).toHaveBeenCalledTimes(1);
        await act(async () => void (await vi.advanceTimersByTimeAsync(1)));
        expect(sendEventAsync).toHaveBeenCalledTimes(2);
        expect(ws.authFrames()).toEqual([]);

        await act(async () => void (await vi.advanceTimersByTimeAsync(2000)));
        expect(sendEventAsync).toHaveBeenCalledTimes(3);
        expect(ws.authFrames()).toEqual(['token-1']);
        expect(ws.reconnects).toEqual([]);
    });

    it('starts over on a fresh connection when the mint keeps failing', async () => {
        mintFailures = ['refused', 'refused', 'refused', 'refused'];
        const ws = connectedRelay();
        ws.connect();
        await flush();
        await act(
            async () =>
                void (await vi.advanceTimersByTimeAsync(1000 + 2000 + 4000))
        );
        expect(sendEventAsync).toHaveBeenCalledTimes(4);
        expect(ws.reconnects).toEqual([[4002, 'relay token unavailable']]);

        // The fresh connection authenticates as usual.
        ws.drop();
        ws.connect();
        await flush();
        expect(ws.authFrames()).toEqual(['token-1']);
    });

    it('abandons a retry once its connection has dropped', async () => {
        mintFailures = ['refused'];
        const ws = connectedRelay();
        ws.connect();
        await flush();
        ws.drop();
        await act(async () => void (await vi.advanceTimersByTimeAsync(10_000)));
        expect(sendEventAsync).toHaveBeenCalledTimes(1);

        ws.connect();
        await flush();
        expect(sendEventAsync).toHaveBeenCalledTimes(2);
        expect(ws.authFrames()).toEqual(['token-1']);
    });

    it('re-sends a live token on reconnect, and mints a fresh one once it nears expiry', async () => {
        const ws = connectedRelay();
        ws.connect();
        await flush();

        ws.drop();
        ws.connect();
        await flush();
        expect(ws.authFrames()).toEqual(['token-1', 'token-1']);
        expect(minted).toBe(1);

        // Inside the refresh margin: the next connect must not present a token that could lapse in flight.
        vi.setSystemTime((NOW_S + 300 - 30) * 1000);
        ws.drop();
        ws.connect();
        await flush();
        expect(ws.authFrames()).toEqual(['token-1', 'token-1', 'token-2']);
        expect(minted).toBe(2);
    });

    it('drops a token the relay refused, so the reconnect mints a fresh one', async () => {
        const ws = connectedRelay();
        ws.connect();
        await flush();

        ws.receive({ type: 'auth:error', message: 'Token expired' });
        ws.drop();
        ws.connect();
        await flush();

        expect(ws.authFrames()).toEqual(['token-1', 'token-2']);
    });

    it('does not send a token that arrives after its connection dropped', async () => {
        let release: (value: unknown) => void = () => {};
        sendEventAsync.mockImplementationOnce(
            () => new Promise((resolve) => (release = resolve))
        );
        const ws = connectedRelay();
        ws.connect();
        ws.drop();

        release({
            success: true,
            token: 'late',
            expires_at: NOW_S + 300,
            user_id: 'user-1',
        });
        await flush();
        expect(ws.authFrames()).toEqual([]);
    });

    it("keeps the relay's auth replies out of the app's events", async () => {
        const ws = connectedRelay();
        ws.connect();
        await flush();

        ws.receive({ type: 'auth:required' });
        ws.receive({ type: 'auth:success' });
        ws.receive({ type: 'auth:error', message: 'nope' });
        ws.receive({ type: 'chat:message', text: 'hi' });

        expect(injectWireEvent).toHaveBeenCalledTimes(1);
        expect(injectWireEvent).toHaveBeenCalledWith('chat:message', {
            type: 'chat:message',
            text: 'hi',
        });
    });

    it("never presents one user's cached token in another user's room", async () => {
        const first = connectedRelay('user-1');
        first.connect();
        await flush();
        cleanup();

        sessionUser = 'user-2';
        const second = connectedRelay('user-2');
        second.connect();
        await flush();
        expect(second.authFrames()).toEqual(['token-2']);
    });

    it("sends nothing when the app's socket is signed in as a different user", async () => {
        sessionUser = 'someone-else'; // e.g. an admin mimicking a user
        const ws = connectedRelay('user-1');
        ws.connect();
        await flush();
        expect(minted).toBe(1);
        expect(ws.authFrames()).toEqual([]);
    });
});
