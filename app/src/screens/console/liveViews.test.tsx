// @vitest-environment happy-dom
// The console's live views move when the account's change stream says so, over the SDK's own socket, each change
// exactly as the watch socket delivers it (the API's change with the room's cursor), and keep no timer of their own
// while the stream follows the client.
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { watch as sdkWatch, type WatchOptions } from 'noclick';
import { liveFromWatch, sdkLive, type LiveSource } from '@/sdk/watchLive';
import { ConsoleProviders } from './ConsoleProviders';
import { fixtureConsole } from './fixtures/context';
import { fixtureAccount, ok, type FixtureRoute } from './fixtures/core';
import { useReadOnFrames } from './hooks/liveReads';
import { useOperation } from './pages/OperationDrawer';

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

/** The relay's watch room as a socket: it answers the token with `ready` and hands on what the test sends. */
class RoomSocket {
    static open: RoomSocket[] = [];
    readyState = 0;
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: ((event: { code: number; reason: string }) => void) | null = null;
    onerror: (() => void) | null = null;

    constructor(readonly url: string) {
        RoomSocket.open.push(this);
        queueMicrotask(() => {
            this.readyState = 1;
            this.onopen?.();
        });
    }

    send(data: string) {
        if (data === 'ping') return this.onmessage?.({ data: 'pong' });
        if ((JSON.parse(data) as { type?: string }).type === 'auth') this.say({ type: 'ready', resumed: false });
    }

    say(message: object) {
        this.onmessage?.({ data: JSON.stringify(message) });
    }

    close() {
        this.readyState = 3;
    }
}

/** An object's change as the watch socket delivers it: every field the API sets, `object_id` even when null, and the
 *  room's cursor (`id`). */
function change(id: string, object: string, objectId: string | null, status?: string) {
    return { id, type: 'change', at: '2026-11-27T10:00:00.000Z', object, object_id: objectId, ...(status ? { status } : {}) };
}

/** The intervals the console set since `spy` began: testing-library's `waitFor` keeps one of its own while it waits. */
function consoleIntervals(spy: { mock: { calls: unknown[][] } }): unknown[][] {
    return spy.mock.calls.filter(([callback]) => (callback as { name?: string }).name !== 'checkRealTimersCallback');
}

function streamFor(client: Parameters<typeof sdkLive>[0]): LiveSource {
    RoomSocket.open = [];
    const watch = (options: WatchOptions = {}) =>
        sdkWatch({
            ...options,
            token: async () => ({ url: 'wss://relay.test/v1/watch/socket/room_1?ticket=t1', token: 'tok_1' }),
            WebSocket: RoomSocket as unknown as typeof WebSocket,
        });
    return sdkLive(client, { watch: watch as typeof sdkWatch });
}

/** The console over the fixtures with a live source on the change stream; `routes` answer first. `settled` waits for
 *  the stream to be live and the reset its first `ready` brings (the account read again) to be over. */
function liveConsole(routes: FixtureRoute[]) {
    let accountReads = 0;
    const account: FixtureRoute = {
        method: 'GET',
        path: '/v1/account',
        reply: () => {
            accountReads += 1;
            return ok(fixtureAccount('populated'));
        },
    };
    const base = fixtureConsole({ routes: [account, ...routes] });
    const source = streamFor(base.client);
    const value = { ...base, live: liveFromWatch(source, { backstopMs: null }) };
    const settled = () => waitFor(() => expect([source.status(), accountReads]).toEqual(['live', 2]));
    return { value, settled };
}

describe("the console's live views", () => {
    it("read an operation again when its change comes, and keep no timer while the stream follows", async () => {
        const reads: string[] = [];
        const { value, settled } = liveConsole([
            {
                method: 'GET',
                path: '/v1/operations/:id',
                reply: (r) => {
                    reads.push(r.params.id);
                    return ok({ object: 'operation', id: r.params.id, kind: 'agent.message', status: 'running', created_at: '2026-11-27T09:59:00Z' });
                },
            },
        ]);
        function Drawer({ id }: { id: string }) {
            useOperation(id);
            return null;
        }
        const view = render(<ConsoleProviders value={value}>{null}</ConsoleProviders>);
        await settled();
        const timers = vi.spyOn(window, 'setInterval');

        view.rerender(
            <ConsoleProviders value={value}>
                <Drawer id="op_1" />
            </ConsoleProviders>
        );
        await waitFor(() => expect(reads).toEqual(['op_1']));
        act(() => RoomSocket.open[0].say(change('c_1', 'operation', 'op_1', 'running')));
        await waitFor(() => expect(reads).toEqual(['op_1', 'op_1']));
        // Another operation's change reads nothing this view shows.
        act(() => RoomSocket.open[0].say(change('c_2', 'operation', 'op_2', 'running')));
        act(() => RoomSocket.open[0].say(change('c_3', 'operation', 'op_1', 'succeeded')));
        await waitFor(() => expect(reads).toEqual(['op_1', 'op_1', 'op_1']));
        expect(consoleIntervals(timers)).toEqual([]);
    });

    it("read the tool-call log's newer calls when a burst of them is recorded", async () => {
        const { value, settled } = liveConsole([]);
        const read = vi.fn(async () => undefined);
        function Tail() {
            useReadOnFrames('platform:tool_calls', () => true, read);
            return null;
        }
        render(
            <ConsoleProviders value={value}>
                <Tail />
            </ConsoleProviders>
        );
        await settled();
        // The socket opened without carrying on: what's shown is read again once.
        await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
        const timers = vi.spyOn(window, 'setInterval');
        act(() => RoomSocket.open[0].say(change('c_1', 'tool_calls', null)));
        // Reads a burst asks for are a READ_GAP_MS apart: this one waits out the gap since the reset's.
        await waitFor(() => expect(read).toHaveBeenCalledTimes(2), { timeout: 3000 });
        expect(consoleIntervals(timers)).toEqual([]);
    });
});
