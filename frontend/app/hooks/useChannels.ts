// The account's channels as the Channels page holds them, over a transport
// (the hosted platform's, or a test's): its workspaces and channels, each
// opened channel's history paged back from the newest, and every write.
// Changes arrive live through the transport and are read again where they
// landed (new messages after the newest, one message's reactions, the lists);
// a slow re-read is the backstop. Your own post shows at once and settles into
// the message the server keeps; your reaction flips at once and settles too.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChannelChange, ChannelsTransport } from '~/components/shell/channels/platform';
import type { AgentChoice, Channel, ChannelAttachment, ChannelMessage, ChannelMode, ChannelReaction, ChannelWorkspace } from '~/components/shell/channels/types';

/** How often the lists and the open channel are read again when no change arrived. */
export const CHANNELS_BACKSTOP_MS = 60_000;
/** Changes that land together are read once. */
const SETTLE_MS = 250;

export interface ChannelHistory {
    /** Oldest first. */
    messages: ChannelMessage[];
    /** Where older messages start, or null once the beginning is loaded. */
    older: string | null;
    loading: boolean;
    loadingOlder: boolean;
    error: string | null;
}

export interface Channels {
    loading: boolean;
    /** Why the account's channels couldn't be read, in a sentence. */
    error: string | null;
    workspaces: ChannelWorkspace[];
    channels: Channel[];
    agents: AgentChoice[];
    history(channelId: string): ChannelHistory | undefined;
    loadOlder(channelId: string): Promise<void>;
    refresh(): void;
    post(channelId: string, text: string, attachments: ChannelAttachment[]): Promise<void>;
    /** NoClick answering you alone, in the channel, until dismissed. */
    note(channelId: string, text: string): void;
    dismiss(channelId: string, messageId: string): void;
    /** Add your reaction, or take it back if it's there. */
    toggleReaction(channelId: string, messageId: string, emoji: string): Promise<void>;
    createWorkspace(name: string, logo?: File): Promise<ChannelWorkspace>;
    createChannel(input: { workspaceId: string | null; name: string; topic: string; mode: ChannelMode; agents: AgentChoice[] }): Promise<Channel>;
    updateChannel(channelId: string, changes: { topic?: string; mode?: ChannelMode }): Promise<void>;
    addAgent(channelId: string, agent: AgentChoice): Promise<void>;
    removeMember(channelId: string, memberId: string): Promise<void>;
    close(channelId: string): Promise<void>;
}

const EMPTY_HISTORY: ChannelHistory = { messages: [], older: null, loading: true, loadingOlder: false, error: null };

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const time = (m: ChannelMessage) => Date.parse(m.at) || 0;

/** `incoming` folded into `current`: one copy of each message, in the order they were posted. */
export function mergeMessages(current: ChannelMessage[], incoming: ChannelMessage[]): ChannelMessage[] {
    const byId = new Map(current.map((m) => [m.id, m]));
    for (const m of incoming) byId.set(m.id, m);
    return [...byId.values()].sort((a, b) => time(a) - time(b));
}

/** The newest message the server has (what `after` reads from). */
function newestKept(messages: ChannelMessage[]): string | null {
    for (let i = messages.length - 1; i >= 0; i--) if (!messages[i].pending && !messages[i].ephemeral) return messages[i].id;
    return null;
}

/** Your reaction flipped, before the server answers. */
export function flipReaction(reactions: ChannelReaction[], emoji: string): ChannelReaction[] {
    const found = reactions.find((r) => r.emoji === emoji);
    if (!found) return [...reactions, { emoji, count: 1, mine: true, names: ['You'] }];
    if (!found.mine) return reactions.map((r) => (r === found ? { ...r, count: r.count + 1, mine: true, names: [...r.names, 'You'] } : r));
    if (found.count <= 1) return reactions.filter((r) => r !== found);
    return reactions.map((r) => (r === found ? { ...r, count: r.count - 1, mine: false, names: r.names.filter((n) => n !== 'You') } : r));
}

let localIds = 0;

export function useChannels(transport: ChannelsTransport, openId: string | null): Channels {
    const [lists, setLists] = useState<{ loading: boolean; error: string | null; workspaces: ChannelWorkspace[]; channels: Channel[] }>({
        loading: true,
        error: null,
        workspaces: [],
        channels: [],
    });
    const [agents, setAgents] = useState<AgentChoice[]>([]);
    const [histories, setHistories] = useState<Record<string, ChannelHistory>>({});
    const historiesRef = useRef(histories);
    historiesRef.current = histories;
    const openRef = useRef(openId);
    openRef.current = openId;

    const setHistory = useCallback((channelId: string, update: (h: ChannelHistory) => ChannelHistory) => {
        setHistories((prev) => ({ ...prev, [channelId]: update(prev[channelId] ?? EMPTY_HISTORY) }));
    }, []);

    const readLists = useCallback(async () => {
        try {
            const [workspaces, channels] = await Promise.all([transport.workspaces(), transport.channels()]);
            setLists({ loading: false, error: null, workspaces, channels });
        } catch (e) {
            setLists((prev) => ({ ...prev, loading: false, error: errorText(e) }));
        }
    }, [transport]);

    const readAgents = useCallback(async () => {
        try {
            setAgents(await transport.agents());
        } catch (e) {
            console.warn('[channels] agents failed:', e);
        }
    }, [transport]);

    /** What arrived after the newest message this page holds. */
    const readNew = useCallback(
        async (channelId: string) => {
            const held = historiesRef.current[channelId];
            if (!held || held.loading) return;
            const after = newestKept(held.messages);
            try {
                const fresh = after ? await transport.after(channelId, after) : (await transport.history(channelId)).messages;
                if (fresh.length) setHistory(channelId, (h) => ({ ...h, messages: mergeMessages(h.messages, fresh) }));
            } catch (e) {
                console.warn('[channels] new messages failed:', e);
            }
        },
        [transport, setHistory]
    );

    const openHistory = useCallback(
        async (channelId: string) => {
            setHistory(channelId, (h) => ({ ...h, loading: true, error: null }));
            try {
                const page = await transport.history(channelId);
                setHistory(channelId, (h) => ({ ...h, loading: false, older: page.older, messages: mergeMessages(h.messages, page.messages) }));
            } catch (e) {
                setHistory(channelId, (h) => ({ ...h, loading: false, error: errorText(e) }));
            }
        },
        [transport, setHistory]
    );

    useEffect(() => {
        void readLists();
        void readAgents();
    }, [readLists, readAgents]);

    // A channel's history loads the first time it opens; later it's kept current by changes.
    useEffect(() => {
        if (openId && !historiesRef.current[openId]) void openHistory(openId);
    }, [openId, openHistory]);

    // Live: read again where a change landed, a burst at a time.
    useEffect(() => {
        const pending = { lists: false, workspaces: false, fresh: new Set<string>(), messages: new Map<string, Set<string>>() };
        let timer: ReturnType<typeof setTimeout> | undefined;
        const flush = () => {
            timer = undefined;
            if (pending.lists) void readLists();
            pending.lists = false;
            for (const channelId of pending.fresh) void readNew(channelId);
            pending.fresh.clear();
            for (const [channelId, ids] of pending.messages) {
                for (const messageId of ids) {
                    transport.message(channelId, messageId).then(
                        (message) => setHistory(channelId, (h) => ({ ...h, messages: mergeMessages(h.messages, [message]) })),
                        (e) => console.warn('[channels] message failed:', e)
                    );
                }
            }
            pending.messages.clear();
        };
        const onChange = (change: ChannelChange) => {
            const id = change.channelId;
            const loaded = id !== undefined && historiesRef.current[id] !== undefined;
            if (change.kind === 'reaction') {
                if (!loaded || !change.messageId) return;
                const ids = pending.messages.get(id) ?? new Set<string>();
                pending.messages.set(id, ids.add(change.messageId));
            } else {
                // New messages move unread counts and who's busy; a channel's own change moves the lists.
                pending.lists = true;
                if (loaded && change.kind !== 'workspace') pending.fresh.add(id);
            }
            timer ??= setTimeout(flush, SETTLE_MS);
        };
        const stop = transport.subscribe(onChange);
        return () => {
            stop();
            if (timer) clearTimeout(timer);
        };
    }, [transport, readLists, readNew, setHistory]);

    // The backstop: a slow re-read while the page is in front of you.
    useEffect(() => {
        const tick = () => {
            if (document.hidden) return;
            void readLists();
            if (openRef.current) void readNew(openRef.current);
        };
        const timer = window.setInterval(tick, CHANNELS_BACKSTOP_MS);
        const onVisible = () => {
            if (!document.hidden) tick();
        };
        document.addEventListener('visibilitychange', onVisible);
        return () => {
            window.clearInterval(timer);
            document.removeEventListener('visibilitychange', onVisible);
        };
    }, [readLists, readNew]);

    // What you're reading is read: the open channel's unread count goes to zero, on the server too.
    const openUnread = lists.channels.find((c) => c.id === openId)?.unread ?? 0;
    useEffect(() => {
        if (!openId || !openUnread || typeof document === 'undefined' || document.hidden) return;
        setLists((prev) => ({ ...prev, channels: prev.channels.map((c) => (c.id === openId ? { ...c, unread: 0 } : c)) }));
        transport.markRead(openId).catch((e) => console.warn('[channels] mark read failed:', e));
    }, [openId, openUnread, transport]);

    const replaceChannel = useCallback((channel: Channel) => {
        setLists((prev) => ({ ...prev, channels: prev.channels.some((c) => c.id === channel.id) ? prev.channels.map((c) => (c.id === channel.id ? channel : c)) : [...prev.channels, channel] }));
    }, []);

    return useMemo<Channels>(
        () => ({
            loading: lists.loading,
            error: lists.error,
            workspaces: lists.workspaces,
            channels: lists.channels,
            agents,
            history: (channelId) => histories[channelId],
            loadOlder: async (channelId) => {
                const held = historiesRef.current[channelId];
                if (!held?.older || held.loadingOlder) return;
                setHistory(channelId, (h) => ({ ...h, loadingOlder: true }));
                try {
                    const page = await transport.history(channelId, held.older);
                    setHistory(channelId, (h) => ({ ...h, loadingOlder: false, older: page.older, messages: mergeMessages(h.messages, page.messages) }));
                } catch (e) {
                    setHistory(channelId, (h) => ({ ...h, loadingOlder: false }));
                    throw e;
                }
            },
            refresh: () => {
                void readLists();
                if (openRef.current) void readNew(openRef.current);
            },
            post: async (channelId, text, attachments) => {
                const localId = `local-${++localIds}`;
                const draft: ChannelMessage = {
                    id: localId,
                    author: { type: 'account', id: null, name: 'You' },
                    text,
                    at: new Date().toISOString(),
                    attachments,
                    reactions: [],
                    mentions: [],
                    pending: true,
                };
                setHistory(channelId, (h) => ({ ...h, messages: [...h.messages, draft] }));
                try {
                    const posted = await transport.post(
                        channelId,
                        text,
                        attachments.map((a) => a.id)
                    );
                    setHistory(channelId, (h) => ({ ...h, messages: mergeMessages(h.messages.filter((m) => m.id !== localId), [posted]) }));
                } catch (e) {
                    setHistory(channelId, (h) => ({ ...h, messages: h.messages.filter((m) => m.id !== localId) }));
                    throw e;
                }
            },
            note: (channelId, text) => {
                const note: ChannelMessage = {
                    id: `note-${++localIds}`,
                    author: { type: 'system', id: null, name: 'NoClick' },
                    text,
                    at: new Date().toISOString(),
                    attachments: [],
                    reactions: [],
                    mentions: [],
                    ephemeral: true,
                };
                setHistory(channelId, (h) => ({ ...h, messages: [...h.messages, note] }));
            },
            dismiss: (channelId, messageId) => setHistory(channelId, (h) => ({ ...h, messages: h.messages.filter((m) => m.id !== messageId) })),
            toggleReaction: async (channelId, messageId, emoji) => {
                const before = historiesRef.current[channelId]?.messages.find((m) => m.id === messageId);
                if (!before) return;
                const on = !before.reactions.some((r) => r.emoji === emoji && r.mine);
                setHistory(channelId, (h) => ({ ...h, messages: h.messages.map((m) => (m.id === messageId ? { ...m, reactions: flipReaction(m.reactions, emoji) } : m)) }));
                try {
                    const settled = await transport.react(channelId, messageId, emoji, on);
                    setHistory(channelId, (h) => ({ ...h, messages: mergeMessages(h.messages, [settled]) }));
                } catch (e) {
                    setHistory(channelId, (h) => ({ ...h, messages: h.messages.map((m) => (m.id === messageId ? { ...m, reactions: before.reactions } : m)) }));
                    throw e;
                }
            },
            createWorkspace: async (name, logo) => {
                const made = await transport.createWorkspace(name, logo);
                setLists((prev) => ({ ...prev, workspaces: [...prev.workspaces.filter((w) => w.id !== made.id), made] }));
                return made;
            },
            createChannel: async (input) => {
                const made = await transport.createChannel(input);
                replaceChannel(made);
                return made;
            },
            updateChannel: async (channelId, changes) => replaceChannel(await transport.updateChannel(channelId, changes)),
            addAgent: async (channelId, agent) => {
                const channel = lists.channels.find((c) => c.id === channelId);
                if (!channel) throw new Error('That channel is gone.');
                replaceChannel(await transport.addAgent(channel, agent));
            },
            removeMember: async (channelId, memberId) => replaceChannel(await transport.removeMember(channelId, memberId)),
            close: async (channelId) => {
                await transport.close(channelId);
                setLists((prev) => ({ ...prev, channels: prev.channels.filter((c) => c.id !== channelId) }));
            },
        }),
        [lists, agents, histories, transport, setHistory, readLists, readNew, replaceChannel]
    );
}
