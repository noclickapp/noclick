// A channel as the Chat page's card shows it in the reply that made it or put an agent in it: the channel (its members
// seated as Work seats them, your unread count), the newest page of its timeline, and the agents the card carries (each
// one's job, and the automation editing it opens), read with the page's client through Work's own transport. Followed over the
// account's platform:channel frames: a message is read in as its frame lands, never polled. A post goes out as you,
// the account, as Work's box posts it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { jobOf } from '@/screens/chat/cards/agentWords';
import { errorText } from '@/screens/console/pages/resources/shared';
import { channelOf, platformTransport, sdkTyping } from '@/screens/channels/sdkTransport';
import { useClient } from '@/sdk/client';
import { Agent, Channel as PlatformChannel, NotFound, Workspace } from 'noclick';
import { keptByNoClick } from '@/screens/work/agents/reads';
import type { Channel, ChannelMember, ChannelMessage } from '@/screens/channels/types';
import { flipReaction, mergeMessages, newestKept, seated } from '@/screens/channels/useChannels';
import { useWorkFrames } from '@/sdk/live';
import type { JsonObject } from '@/lib/toolCalls';

/** A platform agent in the channel beyond its seat there: its job in a line, and the automation it runs on. */
export interface ReplyAgent {
    role?: string;
    workflowId: string | null;
}

export interface ChannelReply {
    channel: Channel | null;
    /** The space it's in, by name; null for one of your own channels (or until it's read). */
    space: string | null;
    /** The newest page of its timeline, oldest first (null until read), and whether earlier messages remain. */
    messages: ChannelMessage[] | null;
    older: boolean;
    /** The agents the card carries: `joined`, the one a call put in it; else every agent in it but NoClick's own. */
    carried: ChannelMember[];
    /** Each platform agent it carries, by agent id, once read. */
    agents: ReadonlyMap<string, ReplyAgent>;
    gone: boolean;
    /** What the last read said went wrong. */
    error: string | null;
    /** Posts `text` as you; throws the sentence to show. */
    post(text: string): Promise<void>;
    react(message: ChannelMessage, emoji: string): void;
}

export function useChannelReply(channelId: string, joined?: string): ChannelReply {
    const client = useClient();
    const transport = useMemo(() => platformTransport(client, { sendTyping: sdkTyping(client) }), [client]);
    const [channel, setChannel] = useState<Channel | null>(null);
    const [space, setSpace] = useState<string | null>(null);
    const [page, setPage] = useState<{ messages: ChannelMessage[]; older: boolean } | null>(null);
    const [agents, setAgents] = useState<ReadonlyMap<string, ReplyAgent>>(new Map());
    const [gone, setGone] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const held = useRef<ChannelMessage[] | null>(null);
    held.current = page?.messages ?? null;

    const upsert = useCallback((incoming: ChannelMessage[]) => setPage((p) => ({ messages: mergeMessages(p?.messages ?? [], incoming), older: p?.older ?? false })), []);
    const failed = useCallback((e: unknown) => setError(errorText(e)), []);

    const readChannel = useCallback(async () => {
        try {
            setChannel(seated(channelOf(await PlatformChannel.get(channelId, { client, user: null }))));
        } catch (e) {
            if (e instanceof NotFound) setGone(true);
            else failed(e);
        }
    }, [client, channelId, failed]);
    const readHistory = useCallback(async () => {
        try {
            const read = await transport.history(channelId);
            setPage({ messages: read.messages, older: !!read.older });
        } catch (e) {
            failed(e);
        }
    }, [transport, channelId, failed]);
    /** What came after the newest message held, as Work reads a channel's new messages. */
    const readNew = useCallback(async () => {
        const after = held.current && newestKept(held.current);
        if (!after) return readHistory();
        try {
            upsert(await transport.after(channelId, after));
        } catch (e) {
            failed(e);
        }
    }, [transport, channelId, readHistory, upsert, failed]);

    useEffect(() => {
        void readChannel();
        void readHistory();
    }, [readChannel, readHistory]);

    useWorkFrames(
        'platform:channel',
        (frame) => {
            if (frame.channel_id !== channelId) return;
            // Every move can change who's in it or what you've read.
            void readChannel();
            if (frame.kind === 'message') void readNew();
            else if (frame.kind === 'reaction' && frame.message_id && held.current?.some((m) => m.id === frame.message_id))
                transport.message(channelId, frame.message_id).then((m) => upsert([m]), failed);
        }
    );

    const carried = useMemo(
        () => (channel?.members ?? []).filter((m) => m.kind === 'agent' && (joined ? m.id === joined : !keptByNoClick(m))),
        [channel, joined]
    );
    // Each platform agent it carries, read once: its job and its automation.
    const agentIds = carried.flatMap((m) => (m.agentId ? [m.agentId] : [])).join(' ');
    useEffect(() => {
        const wanted = agentIds ? agentIds.split(' ') : [];
        let live = true;
        for (const agentId of wanted) {
            Agent.get(agentId, { client, user: null }).then(
                (agent) => live && setAgents((was) => new Map(was).set(agentId, { role: jobOf(agent.raw as JsonObject), workflowId: agent.workflowId })),
                (e: unknown) => live && failed(e)
            );
        }
        return () => {
            live = false;
        };
    }, [agentIds, client, failed]);

    const workspaceId = channel?.workspaceId ?? null;
    useEffect(() => {
        if (!workspaceId) return;
        let live = true;
        Workspace.get(workspaceId, { client, user: null }).then(
            (w) => live && setSpace(w.name),
            (e: unknown) => live && failed(e)
        );
        return () => {
            live = false;
        };
    }, [workspaceId, client, failed]);

    const post = useCallback(async (text: string) => upsert([await transport.post(channelId, text, [])]), [transport, channelId, upsert]);
    const react = useCallback(
        (message: ChannelMessage, emoji: string) => {
            const on = !message.reactions.some((r) => r.emoji === emoji && r.mine);
            upsert([{ ...message, reactions: flipReaction(message.reactions, emoji) }]);
            transport.react(channelId, message.id, emoji, on).then((now) => upsert([now]), failed);
        },
        [transport, channelId, upsert, failed]
    );

    return { channel, space, messages: page?.messages ?? null, older: page?.older ?? false, carried, agents, gone, error, post, react };
}
