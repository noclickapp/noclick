// The account's channels as a channel page holds them, over a transport
// (the platform's through the SDK, or a test's): its workspaces and channels, each
// opened channel's history paged back from the newest, and every write.
// Changes arrive live through the transport and are read again where they
// landed (new messages after the newest, one message's reactions, the lists);
// a slow re-read is the backstop. Your own post shows at once and settles into
// the message the server keeps; your reaction flips at once and settles too.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { seatMembers } from './model';
import type { ChannelChange, ChannelsTransport } from './transport';
import type { AgentChoice, Channel, ChannelAttachment, ChannelMessage, ChannelMode, ChannelReaction, ChannelWorkspace } from './types';

/** How often the lists and the open channel are read again when no change arrived. */
export const CHANNELS_BACKSTOP_MS = 60_000;
/** Changes that land together are read once. */
export const SETTLE_MS = 250;

export interface ChannelHistory {
    /** Oldest first. */
    messages: ChannelMessage[];
    /** Where older messages start, or null once the beginning is loaded. */
    older: string | null;
    loading: boolean;
    loadingOlder: boolean;
    error: string | null;
    /** Kept in this browser from an earlier session (some of it left out): catching up replaces it whole. */
    restored?: boolean;
}

export interface Channels {
    loading: boolean;
    /** The open channel isn't in the lists, which haven't been read since it opened (it was made since, say): they're
     *  read again for it, and until they answer it isn't gone. */
    findingOpen: boolean;
    /** Why the account's channels couldn't be read, in a sentence. */
    error: string | null;
    workspaces: ChannelWorkspace[];
    channels: Channel[];
    agents: AgentChoice[];
    history(channelId: string): ChannelHistory | undefined;
    /** Read a channel's history ahead of its opening (a row the pointer rests on), as opening it would. */
    prefetch(channelId: string): void;
    loadOlder(channelId: string): Promise<void>;
    refresh(): void;
    post(channelId: string, text: string, attachments: ChannelAttachment[]): Promise<void>;
    /** NoClick answering you alone, in the channel, until dismissed. */
    note(channelId: string, text: string): void;
    dismiss(channelId: string, messageId: string): void;
    /** A message as the server now has it (a pin, a thread's counts), into the timeline it's in. */
    upsert(channelId: string, message: ChannelMessage): void;
    /** Add your reaction, or take it back if it's there. */
    toggleReaction(channelId: string, messageId: string, emoji: string): Promise<void>;
    createWorkspace(name: string, logo?: File): Promise<ChannelWorkspace>;
    createChannel(input: { workspaceId: string | null; name: string; topic: string; agents: AgentChoice[]; people?: string[] }): Promise<Channel>;
    updateChannel(channelId: string, changes: { name?: string; topic?: string; mode?: ChannelMode }): Promise<void>;
    addAgent(channelId: string, agent: AgentChoice): Promise<void>;
    removeMember(channelId: string, memberId: string): Promise<void>;
    close(channelId: string): Promise<void>;
    /** Open a closed channel again (under `name`, where an open one has its own). */
    reopen(channelId: string, name?: string): Promise<void>;
    /** Star or mute it, or undo either, for you alone: it shows at once. */
    setPreference(channelId: string, preference: 'starred' | 'muted', on: boolean): Promise<void>;
    /** Leave a channel you're in. */
    leave(channelId: string): Promise<void>;
    /** Join a channel you're not in (one you left, say). */
    join(channelId: string): Promise<void>;
    /** To the trash; resolves to its trash item, which `restoreChannel` puts back. */
    deleteChannel(channelId: string): Promise<{ trashId: string }>;
    restoreChannel(trashId: string): Promise<void>;
}

const EMPTY_HISTORY: ChannelHistory = { messages: [], older: null, loading: true, loadingOlder: false, error: null };

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const time = (m: ChannelMessage) => Date.parse(m.at) || 0;

/** A channel with its agents each in a colour and letters of their own there (`seatMembers`). */
export const seated = (channel: Channel): Channel => ({ ...channel, members: seatMembers(channel.members) });

/** `incoming` folded into `current`: one copy of each message, in the order they were posted. */
export function mergeMessages(current: ChannelMessage[], incoming: ChannelMessage[]): ChannelMessage[] {
    const byId = new Map(current.map((m) => [m.id, m]));
    for (const m of incoming) byId.set(m.id, m);
    return [...byId.values()].sort((a, b) => time(a) - time(b));
}

/** The newest message the server has (what `after` reads from). */
export function newestKept(messages: ChannelMessage[]): string | null {
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

interface Lists {
    loading: boolean;
    error: string | null;
    workspaces: ChannelWorkspace[];
    channels: Channel[];
}

/** What a transport's page last held (its lists, agents and the histories it opened), so a page mounted again over the
 *  same transport shows it at once and reads it again in place. Changes that landed meanwhile went unheard: every list
 *  is read again on mount, and each kept history again the first time it's opened. */
export interface ChannelsHeld {
    lists: Lists;
    agents: AgentChoice[];
    histories: Record<string, ChannelHistory>;
}
const held = new WeakMap<ChannelsTransport, ChannelsHeld>();

/** What a page over `transport` holds now; null before it read anything. */
export function heldBy(transport: ChannelsTransport): ChannelsHeld | null {
    return held.get(transport) ?? null;
}

/** Puts what a page held before (an earlier visit, kept in this browser) under `transport`, unless it holds something
 *  already: a page mounted over it then shows it at once and reads it all again, as after a return. */
export function hold(transport: ChannelsTransport, kept: ChannelsHeld): void {
    if (!held.has(transport)) held.set(transport, kept);
}

export function useChannels(transport: ChannelsTransport, openId: string | null): Channels {
    const [lists, setLists] = useState<Lists>(() => held.get(transport)?.lists ?? { loading: true, error: null, workspaces: [], channels: [] });
    const [agents, setAgents] = useState<AgentChoice[]>(() => held.get(transport)?.agents ?? []);
    const [histories, setHistories] = useState<Record<string, ChannelHistory>>(() => held.get(transport)?.histories ?? {});
    const historiesRef = useRef(histories);
    historiesRef.current = histories;
    const openRef = useRef(openId);
    openRef.current = openId;
    // The histories read (or followed) since this page mounted: any other one held from before is read again on open.
    const current = useRef(new Set<string>());
    // The channel open when the latest read of the lists began; undefined until one answers after mount.
    const [readWith, setReadWith] = useState<string | null | undefined>(undefined);

    useEffect(() => {
        // What's held is what the server sent: never a post still going or a note only you see.
        const settled = Object.fromEntries(
            Object.entries(histories)
                .filter(([, h]) => !h.loading && !h.error)
                .map(([id, h]) => [id, { ...h, loadingOlder: false, messages: h.messages.filter((m) => !m.pending && !m.ephemeral) }])
        );
        held.set(transport, { lists, agents, histories: settled });
    }, [transport, lists, agents, histories]);

    const setHistory = useCallback((channelId: string, update: (h: ChannelHistory) => ChannelHistory) => {
        setHistories((prev) => ({ ...prev, [channelId]: update(prev[channelId] ?? EMPTY_HISTORY) }));
    }, []);

    const readLists = useCallback(async () => {
        const opened = openRef.current;
        try {
            const [workspaces, channels] = await Promise.all([transport.workspaces(), transport.channels()]);
            setLists({ loading: false, error: null, workspaces, channels: channels.map(seated) });
        } catch (e) {
            setLists((prev) => ({ ...prev, loading: false, error: errorText(e) }));
        }
        setReadWith(opened);
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

    /** A history held from an earlier mount, brought up to date in place: its newest page read again (what changed on
     *  it, what's gone from it), the older messages it held kept while they run on into that page. When more came
     *  meanwhile than a page holds (or it was kept from an earlier session), what it held is dropped: the page starts
     *  the history again, its older ones a click away, never with a hole in it. */
    const catchUp = useCallback(
        async (channelId: string) => {
            try {
                const page = await transport.history(channelId);
                const from = page.messages.length ? time(page.messages[0]) : Infinity;
                setHistory(channelId, (h) => {
                    const joins = !h.restored && page.messages.length > 0 && h.messages.some((m) => m.id === page.messages[0].id);
                    const older = page.older && joins ? h.messages.filter((m) => !m.pending && !m.ephemeral && time(m) < from) : [];
                    const local = h.messages.filter((m) => m.pending || m.ephemeral);
                    return { ...h, restored: false, older: older.length ? h.older : page.older, messages: mergeMessages(older, [...page.messages, ...local]) };
                });
            } catch (e) {
                console.warn('[channels] catching up failed:', e);
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

    // A channel opened that the lists don't hold (held from an earlier visit, or read before it was made) is looked for in
    // them once more before it counts as gone; the read on mount looks for the one open then.
    const findingOpen = !!openId && !lists.channels.some((c) => c.id === openId) && readWith !== openId;
    useEffect(() => {
        if (findingOpen && readWith !== undefined) void readLists();
    }, [findingOpen, readWith, readLists]);

    // A channel's history loads the first time it opens (or is read ahead); later it's kept current by changes. One
    // held from an earlier mount shows at once and catches up.
    const bringUp = useCallback(
        (channelId: string) => {
            if (current.current.has(channelId)) return;
            current.current.add(channelId);
            if (historiesRef.current[channelId]) void catchUp(channelId);
            else void openHistory(channelId);
        },
        [openHistory, catchUp]
    );
    useEffect(() => {
        if (openId) bringUp(openId);
    }, [openId, bringUp]);

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
        /** Read one message again, if the timeline shows it (a reply lives in its thread, not here). */
        const reread = (channelId: string | undefined, messageId: string | undefined) => {
            if (!channelId || !messageId || !historiesRef.current[channelId]?.messages.some((m) => m.id === messageId)) return;
            const ids = pending.messages.get(channelId) ?? new Set<string>();
            pending.messages.set(channelId, ids.add(messageId));
        };
        const onChange = (change: ChannelChange) => {
            const id = change.channelId;
            const loaded = id !== undefined && historiesRef.current[id] !== undefined;
            if (change.kind === 'reset') {
                // Anything may have moved: the lists, and what's new in every channel this holds.
                pending.lists = true;
                for (const held of Object.keys(historiesRef.current)) pending.fresh.add(held);
            } else if (change.kind === 'reaction' || change.kind === 'pin') {
                reread(id, change.messageId);
            } else if (change.kind === 'thread') {
                // A reply moves its parent's counts, and what's unread.
                reread(id, change.threadId);
                pending.lists = true;
            } else if (change.kind === 'bookmark' || change.kind === 'sections' || change.kind === 'typing') {
                // A channel's bookmarks are its tab's, your sections are your list's, and who's typing is the box's
                // (typing.ts): none of them moves what this holds.
                return;
            } else {
                // New messages move unread counts and who's busy; a channel's own change moves the lists. One that
                // names a message the timeline holds changed it (an ask on it settled): it's read again.
                pending.lists = true;
                if (loaded && change.kind !== 'workspace') pending.fresh.add(id);
                if (change.kind === 'message') reread(id, change.messageId);
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

    // What you're reading is read: the open channel's unread count (and what mentions you) goes to zero, on the server too.
    const openChannel = lists.channels.find((c) => c.id === openId);
    const openUnread = (openChannel?.unread ?? 0) + (openChannel?.mentions ?? 0);
    useEffect(() => {
        if (!openId || !openUnread || typeof document === 'undefined' || document.hidden) return;
        setLists((prev) => ({ ...prev, channels: prev.channels.map((c) => (c.id === openId ? { ...c, unread: 0, ...(c.mentions ? { mentions: 0 } : {}) } : c)) }));
        transport.markRead(openId).catch((e) => console.warn('[channels] mark read failed:', e));
    }, [openId, openUnread, transport]);

    const replaceChannel = useCallback((read: Channel) => {
        const channel = seated(read);
        setLists((prev) => ({ ...prev, channels: prev.channels.some((c) => c.id === channel.id) ? prev.channels.map((c) => (c.id === channel.id ? channel : c)) : [...prev.channels, channel] }));
    }, []);

    return useMemo<Channels>(
        () => ({
            loading: lists.loading,
            findingOpen,
            error: lists.error,
            workspaces: lists.workspaces,
            channels: lists.channels,
            agents,
            history: (channelId) => histories[channelId],
            prefetch: bringUp,
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
            upsert: (channelId, message) => setHistory(channelId, (h) => (h.messages.some((m) => m.id === message.id) ? { ...h, messages: mergeMessages(h.messages, [message]) } : h)),
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
            // A closed channel stays in its list, read-only.
            close: async (channelId) => {
                await transport.close(channelId);
                setLists((prev) => ({ ...prev, channels: prev.channels.map((c) => (c.id === channelId ? { ...c, status: 'closed' as const } : c)) }));
            },
            reopen: async (channelId, name) => replaceChannel(await transport.reopen(channelId, name)),
            setPreference: async (channelId, preference, on) => {
                const was = lists.channels.find((c) => c.id === channelId);
                const shown = (c: Channel) => ({ ...c, [preference]: on, ...(preference === 'muted' && on ? { unread: c.mentions ?? 0 } : {}) });
                setLists((prev) => ({ ...prev, channels: prev.channels.map((c) => (c.id === channelId ? shown(c) : c)) }));
                try {
                    replaceChannel(await transport.setPreference(channelId, preference, on));
                } catch (e) {
                    if (was) setLists((prev) => ({ ...prev, channels: prev.channels.map((c) => (c.id === channelId ? { ...c, [preference]: was[preference], unread: was.unread } : c)) }));
                    throw e;
                }
            },
            join: async (channelId) => replaceChannel(await transport.join(channelId)),
            // You're out of it, and it reads as one you're not in.
            leave: async (channelId) => {
                await transport.leave(channelId);
                setLists((prev) => ({ ...prev, channels: prev.channels.map((c) => (c.id === channelId ? { ...c, joined: false, starred: false, muted: false, unread: 0 } : c)) }));
            },
            deleteChannel: async (channelId) => {
                const gone = await transport.deleteChannel(channelId);
                setLists((prev) => ({ ...prev, channels: prev.channels.filter((c) => c.id !== channelId) }));
                return gone;
            },
            restoreChannel: async (trashId) => {
                await transport.restoreChannel(trashId);
                await readLists();
            },
        }),
        [lists, findingOpen, agents, histories, transport, setHistory, readLists, readNew, replaceChannel, bringUp]
    );
}
