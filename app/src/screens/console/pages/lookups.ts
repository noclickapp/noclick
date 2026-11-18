// What rows look up (an agent's name, a user's status), read once per page from
// the agent and user lists and cached with useV1. An id the lists don't hold
// renders as the id itself, never as a guess; a user's id is yours and labels itself.
import { Agent, ALL_USERS, User } from 'noclick';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { useV1 } from '@/sdk/useV1';

/** Enough for the tables and pickers. */
const LOOKUP_LIMIT = 200;

export interface UserSummary {
    id: string;
    status: string;
}

/** Your users, newest first: a picker lists them, a row checks one's status. */
export function useUsers(): UserSummary[] {
    const { client } = useConsole();
    const users = useV1('users?lookup', async () => (await User.list({ client, limit: LOOKUP_LIMIT })).map((u) => ({ id: u.id, status: u.status })));
    return users.data ?? [];
}

export interface AgentName {
    id: string;
    name: string;
    userId: string | null;
}

export function useAgentNames(): Map<string, AgentName> {
    const { client } = useConsole();
    const agents = useV1('agents?lookup', async () =>
        (await Agent.list({ client, userFilter: ALL_USERS, limit: LOOKUP_LIMIT })).map((a) => ({ id: a.id, name: a.name, userId: a.userId }))
    );
    return new Map((agents.data ?? []).map((a) => [a.id, a]));
}
