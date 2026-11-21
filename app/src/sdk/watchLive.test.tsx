// @vitest-environment happy-dom
// The live layer over a fake watch: each change reaches the views that read what it names and no others, a reset (or a
// socket that opened without carrying on) has everything shown read again, and with no stream (refused, or not live
// yet) what's shown is read again every minute, the stream asked for again later. The only socket it opens is the
// SDK's own, at the address the token names.
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NoClick, NoClickError, type WatchMessage, type WatchOptions, type WatchStatus } from 'noclick';
import { WorkLiveContext, type WorkLive } from '@/sdk/live';
import { frameOf, liveFromWatch, RETRY_OFF_MS, sdkLive, type LiveMessage, type LiveSource, type LiveStatus } from '@/sdk/watchLive';
import { useV1 } from '@/sdk/useV1';
import { AGENTS_KEY, statesKey, useAgentFrames } from '@/screens/work/agents/reads';
import { WorkClientContext } from '@/screens/work/client';
import { useMachineFrames } from '@/screens/work/machine/frames';
import { useReadsAgainOnReset } from '@/screens/work/rereads';

afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

/** A watch whose messages, statuses and failure the test decides. */
function fakeWatch() {
    let push: ((message: WatchMessage) => void) | null = null;
    let fail: ((error: unknown) => void) | null = null;
    let onStatus: ((status: WatchStatus) => void) | undefined;
    const opened: WatchOptions[] = [];
    async function* watch(options: WatchOptions = {}): AsyncGenerator<WatchMessage> {
        opened.push(options);
        onStatus = options.onStatus;
        const queue: WatchMessage[] = [];
        let wake: (() => void) | null = null;
        let failure: unknown = null;
        push = (message) => {
            queue.push(message);
            wake?.();
        };
        fail = (error) => {
            failure = error;
            wake?.();
        };
        options.onStatus?.('connecting');
        try {
            while (!options.signal?.aborted) {
                if (failure) throw failure;
                const next = queue.shift();
                if (next) {
                    if (next.type === 'ready') options.onStatus?.('live');
                    yield next;
                } else await new Promise<void>((resolve) => {
                    wake = resolve;
                    options.signal?.addEventListener('abort', () => resolve(), { once: true });
                });
            }
        } finally {
            options.onStatus?.('stopped');
        }
    }
    return {
        watch: watch as unknown as typeof import('noclick').watch,
        opened,
        send: (message: WatchMessage) => act(() => push?.(message)),
        status: (status: WatchStatus) => act(() => onStatus?.(status)),
        refuse: () => act(() => fail?.(new NoClickError('Watching isn’t available on this deployment.', { status: 409 }))),
    };
}

const client = new NoClick({ apiKey: 'sk_test_made_up', baseUrl: 'https://api.noclick.test', maxRetries: 0 });
const change = (object: string, objectId: string | null, more: Partial<Extract<WatchMessage, { type: 'change' }>> = {}): WatchMessage => ({
    type: 'change', id: `c_${Math.random()}`, at: null, object, objectId, status: null, parent: null, change: null, version: null,
    workspaceId: null, messageId: null, threadId: null, raw: {}, ...more,
});

/** Work's own readers of what the stream names: agents, where they stand, and one machine. */
function Views({ reads }: { reads: Record<'agents' | 'states' | 'machine', () => Promise<number>> }) {
    useReadsAgainOnReset();
    useAgentFrames();
    // The keys the real reads use, their reads counted.
    useV1(AGENTS_KEY, reads.agents, { client });
    useV1(statesKey(null), reads.states, { client });
    useV1('resources:machines/m-1', reads.machine, { client });
    useMachineFrames('m-1', 'resources:machines/m-1');
    return null;
}

function mount(live: WorkLive) {
    const reads = { agents: vi.fn(async () => 1), states: vi.fn(async () => 2), machine: vi.fn(async () => 3) };
    render(
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={live}>
                <Views reads={reads} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
    const counts = () => ({ agents: reads.agents.mock.calls.length, states: reads.states.mock.calls.length, machine: reads.machine.mock.calls.length });
    return { counts };
}

describe('a change', () => {
    it('re-reads exactly what it names', async () => {
        const fake = fakeWatch();
        const { counts } = mount(liveFromWatch(sdkLive(client, { watch: fake.watch })));
        await waitFor(() => expect(counts()).toEqual({ agents: 1, states: 1, machine: 1 }));
        fake.send({ type: 'ready', resumed: true });

        fake.send(change('agent', 'agt_1', { change: 'turn' }));
        await waitFor(() => expect(counts()).toEqual({ agents: 1, states: 2, machine: 1 }));
        fake.send(change('agent', 'agt_1', { change: 'definition' }));
        await waitFor(() => expect(counts()).toEqual({ agents: 2, states: 3, machine: 1 }));
        fake.send(change('machine', 'm-1', { status: 'running' }));
        await waitFor(() => expect(counts()).toEqual({ agents: 2, states: 3, machine: 2 }));
        // Another machine, a channel, someone typing: none of these views reads them.
        fake.send(change('machine', 'm-2'));
        fake.send(change('channel', 'ch_1', { change: 'message' }));
        fake.send({ type: 'typing', channelId: 'ch_1', workspaceId: null, userId: 'usr_ana', typing: true, raw: {} });
        fake.send(change('machine', 'm-1'));
        await waitFor(() => expect(counts()).toEqual({ agents: 2, states: 3, machine: 3 }));
    });
});

describe('a reset', () => {
    it('reads everything shown again, and so does a socket that opened without carrying on', async () => {
        const fake = fakeWatch();
        const { counts } = mount(liveFromWatch(sdkLive(client, { watch: fake.watch })));
        await waitFor(() => expect(counts()).toEqual({ agents: 1, states: 1, machine: 1 }));

        fake.send({ type: 'ready', resumed: false });
        await waitFor(() => expect(counts()).toEqual({ agents: 2, states: 2, machine: 2 }));
        fake.send({ type: 'reset' });
        await waitFor(() => expect(counts()).toEqual({ agents: 3, states: 3, machine: 3 }));
        // One that carried on from the last change missed nothing.
        fake.send({ type: 'ready', resumed: true });
        fake.send(change('machine', 'm-1'));
        await waitFor(() => expect(counts()).toEqual({ agents: 3, states: 3, machine: 4 }));
    });
});

/** A source the test moves by hand. */
function handSource() {
    const listeners = new Set<(m: LiveMessage) => void>();
    const statusListeners = new Set<(s: LiveStatus) => void>();
    let status: LiveStatus = 'connecting';
    const source: LiveSource = {
        subscribe: (listener) => (listeners.add(listener), () => void listeners.delete(listener)),
        status: () => status,
        onStatus: (listener) => (statusListeners.add(listener), () => void statusListeners.delete(listener)),
    };
    return {
        source,
        listeners,
        set: (next: LiveStatus) => {
            status = next;
            statusListeners.forEach((l) => l(next));
        },
    };
}

describe('the backstop', () => {
    it('resets every minute while the stream isn’t live, and stops once it is', () => {
        vi.useFakeTimers();
        const hand = handSource();
        const live = liveFromWatch(hand.source);
        const heard: string[] = [];
        const off = live.on('reset', (r) => heard.push(r.why));

        vi.advanceTimersByTime(60_000);
        expect(heard).toEqual(['backstop']);
        hand.set('live');
        vi.advanceTimersByTime(180_000);
        expect(heard).toEqual(['backstop']);
        hand.set('reconnecting');
        vi.advanceTimersByTime(60_000);
        expect(heard).toEqual(['backstop', 'backstop']);
        off();
        expect(hand.listeners.size).toBe(0);
        vi.advanceTimersByTime(180_000);
        expect(heard).toEqual(['backstop', 'backstop']);
    });

    it('keeps reading again every minute when the stream isn’t offered, and asks for it again later', async () => {
        vi.useFakeTimers();
        const fake = fakeWatch();
        const source = sdkLive(client, { watch: fake.watch });
        const live = liveFromWatch(source);
        const heard: string[] = [];
        live.on('reset', (r) => heard.push(r.why));
        await vi.waitFor(() => expect(fake.opened).toHaveLength(1));
        fake.refuse();
        await vi.waitFor(() => expect(source.status()).toBe('off'));

        vi.advanceTimersByTime(60_000);
        expect(heard).toEqual(['backstop']);
        vi.advanceTimersByTime(RETRY_OFF_MS - 60_000);
        await vi.waitFor(() => expect(fake.opened).toHaveLength(2));
    });

    it('is never on where the host reads again its own way', () => {
        vi.useFakeTimers();
        const hand = handSource();
        const live = liveFromWatch(hand.source, { backstopMs: null });
        const heard: string[] = [];
        live.on('reset', (r) => heard.push(r.why));
        vi.advanceTimersByTime(300_000);
        expect(heard).toEqual([]);
    });
});

describe('frames', () => {
    it('are the ones the platform’s relay sends, less what the stream never says', () => {
        const at = (m: WatchMessage) => frameOf(m as LiveMessage);
        expect(at(change('channel', 'ch_1', { change: 'thread', workspaceId: 'ws_1', threadId: 'm_9' }))).toEqual(['platform:channel', { kind: 'thread', channel_id: 'ch_1', workspace_id: 'ws_1', message_id: null, thread_id: 'm_9' }]);
        expect(at(change('workspace', 'ws_1'))).toEqual(['platform:channel', { kind: 'workspace', workspace_id: 'ws_1' }]);
        expect(at(change('channel_sections', 'ws_1'))).toEqual(['platform:channel', { kind: 'sections', workspace_id: 'ws_1' }]);
        expect(at(change('agent', 'agt_1', { change: 'wakeups' }))).toEqual(['platform:agent', { agent_id: 'agt_1', change: 'wakeups', conversation: null }]);
        expect(at(change('coding_agent', null, { change: 'pause' }))).toEqual(['platform:coding_agent', { agent_id: null, change: 'pause' }]);
        expect(at(change('agent_trigger', 't-1', { status: 'active', parent: { object: 'agent', id: 'agt_1' } }))).toEqual(['platform:resource', { kind: 'trigger', id: 't-1', status: 'active', parent_id: 'agt_1', version: null }]);
        expect(at(change('workflow', 'wf_1', { version: 7 }))).toEqual(['platform:resource', { kind: 'workflow', id: 'wf_1', status: null, parent_id: null, version: 7 }]);
        // The account was charged: when, and nothing about the charges.
        expect(at(change('usage', null, { at: new Date('2026-10-16T15:20:00Z') }))).toEqual(['platform:usage', { at: '2026-10-16T15:20:00.000Z' }]);
        expect(at(change('usage', null))).toEqual(['platform:usage', { at: null }]);
        expect(at({ type: 'typing', channelId: 'ch_1', workspaceId: 'ws_1', userId: 'usr_ana', typing: true, raw: {} })).toEqual(['platform:channel_typing', { channel_id: 'ch_1', workspace_id: 'ws_1', user_id: 'usr_ana', name: '', typing: true }]);
        // What no screen follows.
        expect(at(change('something_new', 'x_1'))).toBeNull();
        expect(at(change('agent', 'agt_1', { change: 'something_new' }))).toBeNull();
    });
});

describe('the socket', () => {
    it('is the SDK’s own, opened at the address the token names, and the only one', async () => {
        const opened: string[] = [];
        class Socket {
            constructor(readonly url: string) {
                opened.push(url);
            }
            send() {}
            close() {}
            onopen: (() => void) | null = null;
            onmessage: (() => void) | null = null;
            onclose: (() => void) | null = null;
            onerror: (() => void) | null = null;
        }
        vi.stubGlobal('WebSocket', Socket);
        const tokens: string[] = [];
        const viaServer = new NoClick({
            apiKey: 'held-by-this-app-server',
            baseUrl: 'https://app.example.test/api',
            maxRetries: 0,
            fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
                tokens.push(`${init?.method ?? 'GET'} ${new URL(String(input)).pathname}`);
                return Response.json({ url: 'wss://api.noclick.test/v1/watch/socket/room_1', token: 'tok_1', objects: [] });
            }) as typeof fetch,
        });
        const live = liveFromWatch(sdkLive(viaServer));
        const off = live.on('platform:resource', () => undefined);
        await vi.waitFor(() => expect(opened).toEqual(['wss://api.noclick.test/v1/watch/socket/room_1']));
        expect(tokens).toEqual(['POST /api/v1/watch/tokens']);
        off();
    });
});
