// What the chat's card for an agent the coordinator made reads on /v1, with the dashboard's session: the agent with
// its own triggers and the channels it's in (with their schedules). Read again when the account's channels move (a
// platform:channel frame) and, while `follow` is on, every few seconds: the turn that made it goes on adding
// triggers and channels in the calls after. (A channel's card is useChannelReply.)
import { useCallback, useEffect, useState } from 'react';
import type { ChannelSeat } from '@/screens/chat/cards/agentWords';
import { useClient } from '@/sdk/client';
import { Agent, Channel, NO_USER, NotFound } from 'noclick';
import { useWorkFrames } from '@/sdk/live';
import { list, str, type JsonObject } from '@/lib/toolCalls';

/** How often a card read while its turn may still change it reads again. */
export const FOLLOW_READ_MS = 4000;


/** `read` once, again on a channel frame and while `follow` is on; `gone` once it answers 404. */
function useCardRead<T>(page: string, read: () => Promise<T>, follow: boolean) {
    const [view, setView] = useState<T | null>(null);
    const [gone, setGone] = useState(false);
    const load = useCallback(async () => {
        try {
            setView(await read());
        } catch (error) {
            if (error instanceof NotFound) setGone(true);
            else console.warn(`[coordinator] reading ${page} failed:`, error);
        }
    }, [read, page]);
    useWorkFrames('platform:channel', () => void load());
    useEffect(() => {
        if (gone) return;
        void load();
        const timer = follow ? window.setInterval(() => void load(), FOLLOW_READ_MS) : undefined;
        return () => window.clearInterval(timer);
    }, [load, follow, gone]);
    return { view, gone };
}

export interface AgentCardView {
    agent: JsonObject;
    triggers: JsonObject[];
    seats: ChannelSeat[];
}

export function useAgentCard(agentId: string, follow: boolean) {
    const client = useClient();
    const read = useCallback(async (): Promise<AgentCardView> => {
        const agent = Agent.fromId(agentId, { client, user: null });
        const [read, triggers, channels] = await Promise.all([
            agent.hydrate(),
            agent.triggers(),
            Channel.list({ client, status: 'open', agent: agentId, userFilter: NO_USER, limit: 100 }),
        ]);
        const seats = await Promise.all(
            channels.map(async (channel) => ({ channel: channel.raw as JsonObject, triggers: (await channel.triggers()).map((t) => t.raw as JsonObject) })),
        );
        return { agent: read.raw as JsonObject, triggers: triggers.map((t) => t.raw as JsonObject), seats };
    }, [client, agentId]);
    return useCardRead('the agent', read, follow);
}
