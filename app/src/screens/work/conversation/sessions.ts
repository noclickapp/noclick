// An agent is one session, as one terminal window running Claude is: everyone talking to it shares the conversation
// its listing marks `active`, and the earlier ones can be resumed. Work reads an agent's sessions once and again on its
// `session` frames (a clear or a resume, from anywhere), and opens the agent on its active one. A message in it names
// the chat it came from (`chat`): a channel's is `channel:<its id>`.
import { invalidateV1, readV1 } from '@/sdk/useV1';
import type { Agent, Conversation, JsonObject, NoClick } from 'noclick';
import { listedAgent, useWorkV1 } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';

/** Where an agent's sessions are kept, read once for whoever shows or picks them. */
export const sessionsKey = (agentId: string) => `work:agent:${agentId}:sessions`;

export interface Sessions {
    /** The one everyone talking to it shares now. */
    active: string;
    /** Every session, most recently active first, the active one among them once it has a message. */
    all: Conversation[];
}

/** An agent's sessions: an agent nobody has talked to has none yet, and reading any chat of it makes the one its
 *  first message would (the platform's `reading`), which the read names. */
export async function readSessions(client: NoClick, agent: Agent): Promise<Sessions> {
    const all = await agent.conversations();
    const found = all.find((c) => c.active);
    if (found) return { active: found.conversation, all };
    const path = `/v1/agents/${encodeURIComponent(agent.id)}/conversations/chat-${crypto.randomUUID()}`;
    const read = await client.request<JsonObject>('GET', path, { query: { limit: 1 }, user: agent._talkScope(undefined) });
    return { active: String(read.session), all };
}

/** The agent's sessions as Work reads them, null while unread. */
export function useSessions(agentId: string | null): { sessions: Sessions | null; error: unknown; refresh: () => Promise<void> } {
    const read = useWorkV1(agentId ? sessionsKey(agentId) : null, (client) => readSessions(client, listedAgent(client, agentId!)));
    return { sessions: read.data ?? null, error: read.error, refresh: read.refresh };
}

/** The session the agent is in now, null while unread. */
export const useActiveSession = (agentId: string | null): string | null => useSessions(agentId).sessions?.active ?? null;

/** Reads the session an agent opens on, ahead of a click. */
export const readActiveSession = async (client: NoClick, agentId: string): Promise<string> => (await readV1(client, sessionsKey(agentId), () => readSessions(client, listedAgent(client, agentId)))).active;

/** Keeps every agent's sessions current: a clear or a resume anywhere (another page, a chat's /clear, the API) reads
 *  them again, and the views showing the agent move to its new session. */
export function useFollowSessions(): void {
    useWorkFrames('platform:agent', (frame) => {
        if (frame.change === 'session') invalidateV1(sessionsKey(frame.agent_id));
    });
}

const CHANNEL_CHAT = /^channel:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i;

/** The channel a chat is (`channel:<its id>`), else null. */
export function channelOfChat(chat: string): string | null {
    return CHANNEL_CHAT.exec(chat)?.[1] ?? null;
}
