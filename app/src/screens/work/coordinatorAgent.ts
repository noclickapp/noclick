// The account's own assistant (NoClick, an agent named coordinator) and its one session, the conversation
// everyone talking to it shares: looked up once per client (the lookup makes it the first time), its session and that
// session's history read by its name beside that lookup, so a page draws the thread without waiting for it.
import { Agent, NotFound, type Message, type NoClick } from 'noclick';
import { keepRead, peekV1, readV1 } from '@/sdk/useV1';
import { readSessions } from './conversation/sessions';

export const COORDINATOR_AGENT = 'coordinator';
// The agent by its name ref: its conversations read without loading it first.
const byName = (client: NoClick): Agent => Agent.fromId(`agent:${COORDINATOR_AGENT}`, { client, user: null });

// The agent, looked up once per client: coming back reads the history straight away, not after another lookup.
const agents = new WeakMap<NoClick, Agent>();
// Its session as last read through a client (kept in the browser where the host keeps reads), so the page draws it at
// once while it's read again.
const SESSION_KEY = 'coordinator:session';
keepRead(SESSION_KEY);

export function coordinatorAgent(client: NoClick): Agent {
    let agent = agents.get(client);
    if (!agent) agents.set(client, (agent = Agent.fromName(COORDINATOR_AGENT, { client, user: null })));
    return agent;
}

/** Its session as last read through `client` (or kept from an earlier visit), if any. */
export const knownSession = (client: NoClick): string | null => peekV1<string>(client, SESSION_KEY) ?? null;

/** The session it's in: the one its listing by name marks active, read beside the lookup; where that page doesn't
 *  hold it (a new account's agent, made by the lookup, has none yet) its sessions read through the agent. */
export function readCoordinatorSession(client: NoClick): Promise<string> {
    return readV1(client, SESSION_KEY, async () => {
        let active: string | null = null;
        try {
            const page = await byName(client).conversationsPage({ user: null });
            active = page.data.find((c) => c.active)?.conversation ?? null;
        } catch (error) {
            if (!(error instanceof NotFound)) throw error;
        }
        return active ?? (await readSessions(coordinatorAgent(client))).active;
    });
}

/** Its session's history read by the agent's name (`agent:coordinator`), beside the lookup that finds (or first makes)
 *  the agent, so the thread doesn't wait for the lookup. Null where the agent isn't made yet (a new account: 404) or
 *  the read failed: the history is then read by the agent's id once the lookup answers. */
export async function historyByName(client: NoClick, session: string): Promise<Message[] | null> {
    try {
        return await byName(client).history(session, { user: null });
    } catch (error) {
        if (!(error instanceof NotFound)) console.warn('[coordinator] the conversation didn’t read by name:', error);
        return null;
    }
}
