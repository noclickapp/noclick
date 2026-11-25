// The account's change stream (the SDK's `watch`, asked for through the app's own client) as the live frames screens
// follow (@/sdk/live): one stream per client, opened when something follows it and closed a little after nothing does.
// Each change becomes the frame its views already read again on, and a reset (or a socket that opened without carrying
// on from the last change, the first one included) a `reset`: what's shown is read again. While the stream isn't live
// (opening, reconnecting, or not offered here: an API whose stream is off refuses the token), a host can have what's
// shown read again every minute instead, and the stream is asked for again every few minutes, so it turns on by itself.
import { watch as sdkWatch, type NoClick, type WatchChange, type WatchStatus, type WatchTyping } from 'noclick';
import type { PlatformAgentEvent, PlatformChannelEvent, PlatformCodingAgentEvent, PlatformResourceEvent } from '@/sdk/frames';
import { BACKSTOP_MS, createWorkLive, resetEvery, type WorkFrames, type WorkLive } from '@/sdk/live';

/** What the stream says: an object changed, someone is typing, or read everything again. */
export type LiveMessage = WatchChange | WatchTyping | { type: 'reset' };
/** Where the stream stands: the SDK's, or `off` (not offered here, or no longer allowed: asked again later). */
export type LiveStatus = WatchStatus | 'off';

export interface LiveSource {
    subscribe(listener: (message: LiveMessage) => void): () => void;
    status(): LiveStatus;
    onStatus(listener: (status: LiveStatus) => void): () => void;
}

/** How long the stream stays open after the last follower leaves, so moving between pages keeps it. */
export const LINGER_MS = 30_000;
/** How long an `off` stream waits before it's asked for again. */
export const RETRY_OFF_MS = 5 * 60_000;

const SOURCES = new WeakMap<NoClick, LiveSource>();

/** The account's change stream through `client`: one per client (a test hands its own `watch`). */
export function sdkLive(client: NoClick, options: { watch?: typeof sdkWatch } = {}): LiveSource {
    const known = options.watch ? undefined : SOURCES.get(client);
    if (known) return known;
    const watch = options.watch ?? sdkWatch;
    const listeners = new Set<(message: LiveMessage) => void>();
    const statusListeners = new Set<(status: LiveStatus) => void>();
    let status: LiveStatus = 'stopped';
    let running: AbortController | null = null;
    let linger: ReturnType<typeof setTimeout> | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const setStatus = (next: LiveStatus) => {
        if (next === status) return;
        status = next;
        statusListeners.forEach((listener) => listener(next));
    };
    const emit = (message: LiveMessage) => listeners.forEach((listener) => listener(message));

    const start = () => {
        if (running || retry) return;
        const mine = new AbortController();
        running = mine;
        void (async () => {
            try {
                for await (const message of watch({ client, signal: mine.signal, onStatus: (s) => running === mine && setStatus(s) })) {
                    if (message.type === 'ready') {
                        if (!message.resumed) emit({ type: 'reset' });
                    } else emit(message);
                }
            } catch (error) {
                if (running !== mine) return;
                running = null;
                setStatus('off');
                console.info('[live] The change stream isn’t available here; reading again on a timer.', error);
                retry = setTimeout(() => {
                    retry = null;
                    if (listeners.size) start();
                }, RETRY_OFF_MS);
            }
        })();
    };
    const stop = () => {
        running?.abort();
        running = null;
        if (retry) clearTimeout(retry);
        retry = null;
        setStatus('stopped');
    };

    const source: LiveSource = {
        subscribe(listener) {
            listeners.add(listener);
            if (linger) clearTimeout(linger);
            linger = null;
            start();
            let subscribed = true;
            return () => {
                if (!subscribed) return;
                subscribed = false;
                listeners.delete(listener);
                if (!listeners.size) linger = setTimeout(stop, LINGER_MS);
            };
        },
        status: () => status,
        onStatus(listener) {
            statusListeners.add(listener);
            return () => void statusListeners.delete(listener);
        },
    };
    if (!options.watch) SOURCES.set(client, source);
    return source;
}

type Frame = { [K in keyof WorkFrames]: [K, WorkFrames[K]] }[keyof WorkFrames];

const CHANNEL_CHANGES = new Set<PlatformChannelEvent['kind']>(['message', 'thread', 'reaction', 'pin', 'bookmark', 'channel']);
const AGENT_CHANGES = new Set<PlatformAgentEvent['change']>(['turn', 'step', 'tool_servers', 'wakeups', 'definition', 'session']);
const CODING_CHANGES = new Set<PlatformCodingAgentEvent['change']>(['turn', 'place', 'pause', 'definition']);
const RESOURCE_KINDS = new Set<PlatformResourceEvent['kind']>([
    'domain', 'deployment', 'repo', 'mcp_server', 'live_session', 'phone_call', 'workflow', 'workflow_run', 'durable_object_class', 'skill',
    'memory', 'machine', 'sandbox', 'agent_move', 'connection', 'plan_usage', 'workspace_resource', 'space_question',
    'trigger', 'approval', 'browser', 'spend_cap', 'notifications', 'workstream', 'popups', 'phones', 'operation', 'share',
    'hosted_mcp',
]);

const one = <T extends string>(set: ReadonlySet<T>, value: string | null): value is T => value !== null && set.has(value as T);

/** The frame a message of the stream becomes, as the platform's own relay would have sent it; null for one no screen
 *  follows. A change names no conversation (an agent's `conversation` is null: any of them), and typing no name (the
 *  channel's members say whose it is). */
export function frameOf(message: LiveMessage): Frame | null {
    if (message.type === 'reset') return ['reset', { why: 'stream' }];
    if (message.type === 'typing') {
        return ['platform:channel_typing', { channel_id: message.channelId, workspace_id: message.workspaceId, user_id: message.userId, name: '', typing: message.typing }];
    }
    const { object, objectId: id, change } = message;
    switch (object) {
        case 'channel':
            return ['platform:channel', { kind: one(CHANNEL_CHANGES, change) ? change : 'channel', channel_id: id, workspace_id: message.workspaceId, message_id: message.messageId, thread_id: message.threadId }];
        case 'workspace':
            return ['platform:channel', { kind: 'workspace', workspace_id: id }];
        case 'channel_sections':
            return ['platform:channel', { kind: 'sections', workspace_id: id }];
        case 'agent':
            return id && one(AGENT_CHANGES, change) ? ['platform:agent', { agent_id: id, change, conversation: null }] : null;
        case 'coding_agent':
            return one(CODING_CHANGES, change) ? ['platform:coding_agent', { agent_id: id, change }] : null;
        case 'usage':
            return ['platform:usage', { at: message.at?.toISOString() ?? null }];
        default: {
            const kind = object === 'agent_trigger' ? 'trigger' : object;
            return id && one(RESOURCE_KINDS, kind) ? ['platform:resource', { kind, id, status: message.status, parent_id: message.parent?.id ?? null, version: message.version }] : null;
        }
    }
}

/** Hands `frame` to `live` under its kind (a pair a union of kinds can't spread into `deliver`). */
function deliverFrame(live: WorkLive, [kind, frame]: Frame): void {
    (live.deliver as (kind: keyof WorkFrames, frame: WorkFrames[keyof WorkFrames]) => void)(kind, frame);
}

/** A screen's live frames from `source`: followed while anything listens; `backstopMs`, what's shown read again on that
 *  timer while the stream isn't live (null: never). */
export function liveFromWatch(source: LiveSource, { backstopMs = BACKSTOP_MS }: { backstopMs?: number | null } = {}): WorkLive {
    const live = createWorkLive();
    let listening = 0;
    let stop: (() => void) | null = null;

    const follow = () => {
        const unsubscribe = source.subscribe((message) => {
            const frame = frameOf(message);
            if (frame) deliverFrame(live, frame);
        });
        let backstop: (() => void) | null = null;
        const onStatus = (status: LiveStatus) => {
            if (status === 'live' || backstopMs === null) {
                backstop?.();
                backstop = null;
            } else backstop ??= resetEvery(live, backstopMs);
        };
        onStatus(source.status());
        const offStatus = source.onStatus(onStatus);
        return () => {
            unsubscribe();
            offStatus();
            backstop?.();
        };
    };

    return {
        on(kind, listener) {
            const off = live.on(kind, listener);
            if (listening++ === 0) stop = follow();
            let on = true;
            return () => {
                if (!on) return;
                on = false;
                off();
                if (--listening === 0) {
                    stop?.();
                    stop = null;
                }
            };
        },
        deliver: live.deliver,
    };
}
