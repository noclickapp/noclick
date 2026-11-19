// What the chat's card for an agent the coordinator made reads on /v1, with the dashboard's session: the agent with
// its own triggers and the channels it's in (with their schedules). Read again when the account's channels move (a
// platform:channel frame) and, while `follow` is on, every few seconds: the turn that made it goes on adding
// triggers and channels in the calls after. (A channel's card is useChannelReply.)
import { useCallback, useEffect, useState } from 'react';
import type { ChannelSeat } from '@/screens/chat/cards/agentWords';
import { useClient } from '@/sdk/client';
import { NotFound } from 'noclick';
import { useWorkFrames } from '@/sdk/live';
import { list, str, type JsonObject } from '@/lib/toolCalls';

/** How often a card read while its turn may still change it reads again. */
export const FOLLOW_READ_MS = 4000;

const rows = (page: unknown): JsonObject[] => list(page as JsonObject, 'data').filter((r): r is JsonObject => !!r && typeof r === 'object');

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
        const path = `/v1/agents/${encodeURIComponent(agentId)}`;
        const [agent, triggers, channels] = await Promise.all([
            client.request<JsonObject>('GET', path, { user: null }),
            client.request('GET', `${path}/triggers`, { user: null }),
            client.request('GET', '/v1/channels', { user: null, query: { status: 'open', user_id: 'none', limit: 100 } }),
        ]);
        const mine = rows(channels).filter((c) => list(c, 'members').some((m) => str(m as JsonObject, 'agent_id') === agentId));
        const seats = await Promise.all(
            mine.map(async (channel) => ({ channel, triggers: rows(await client.request('GET', `/v1/channels/${str(channel, 'id')}/triggers`, { user: null })) }))
        );
        return { agent, triggers: rows(triggers), seats };
    }, [client, agentId]);
    return useCardRead('the agent', read, follow);
}
