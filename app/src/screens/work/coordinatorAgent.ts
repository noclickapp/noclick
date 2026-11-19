// The account's own assistant (NoClick, an agent named coordinator) and its one session, the conversation
// everyone talking to it shares: looked up once per client (the lookup makes it the first time), its session and that
// session's history read by its name beside that lookup, so a page draws the thread without waiting for it.
import { Agent, NotFound, type JsonObject, type Message, type NoClick } from 'noclick';
import { toMessage } from '@/sdk/source';
import { readSessions } from './conversation/sessions';

export const COORDINATOR_AGENT = 'coordinator';
const BY_NAME = `/v1/agents/${encodeURIComponent(`agent:${COORDINATOR_AGENT}`)}/conversations`;

// The agent, looked up once per client: coming back reads the history straight away, not after another lookup.
const agents = new WeakMap<NoClick, Agent>();
// Its session as last read per client, so coming back draws it at once while it's read again.
const sessions = new WeakMap<NoClick, string>();

export function coordinatorAgent(client: NoClick): Agent {
    let agent = agents.get(client);
    if (!agent) agents.set(client, (agent = Agent.fromName(COORDINATOR_AGENT, { client, user: null })));
    return agent;
}

/** Its session as last read through `client`, if any. */
export const knownSession = (client: NoClick): string | null => sessions.get(client) ?? null;

/** The session it's in: the one its listing by name marks active, read beside the lookup; where that page doesn't
 *  hold it (a new account's agent, made by the lookup, has none yet) its sessions read through the agent. */
export async function readCoordinatorSession(client: NoClick): Promise<string> {
    let active: string | null = null;
    try {
        const page = await client.request<{ data?: JsonObject[] }>('GET', BY_NAME, { user: null });
        const found = (page.data ?? []).find((c) => c.active === true);
        active = typeof found?.conversation === 'string' ? found.conversation : null;
    } catch (error) {
        if (!(error instanceof NotFound)) throw error;
    }
    const session = active ?? (await readSessions(client, coordinatorAgent(client))).active;
    sessions.set(client, session);
    return session;
}

/** Its session's history read by the agent's name (`agent:coordinator`), beside the lookup that finds (or first makes)
 *  the agent, so the thread doesn't wait for the lookup. Null where the agent isn't made yet (a new account: 404) or
 *  the read failed: the history is then read by the agent's id once the lookup answers. */
export async function historyByName(client: NoClick, session: string): Promise<Message[] | null> {
    try {
        const conversation = await client.request<{ messages?: JsonObject[] }>('GET', `${BY_NAME}/${encodeURIComponent(session)}`, { user: null });
        return (conversation.messages ?? []).map(toMessage);
    } catch (error) {
        if (!(error instanceof NotFound)) console.warn('[coordinator] the conversation didn’t read by name:', error);
        return null;
    }
}
