// Work's reads of an account's agents, through the platform client Work is given: the agents themselves, where each
// stands, their faces (the letters and colour each wears everywhere in Work), kept current by the backend's frames
// (a coding agent moving; any agent's turn, step, request, approval, ask or wake-up), never by polling.
import { createContext, createElement, useContext, useMemo, type ReactNode } from 'react';
import { Agent, type NoClick } from 'noclick';
import { invalidateV1, peekV1, useV1, type V1Options, type V1State } from '@/sdk/useV1';
import { COORDINATOR_AGENT } from '../coordinatorAgent';
import { AgentRolesContext } from '@/screens/channels/avatars';
import { NOCLICK_NAME, seatMembers } from '@/screens/channels/model';
import type { ChannelMember } from '@/screens/channels/types';
import { useWorkClient } from '../client';
import { useWorkFrames } from '@/sdk/live';
import { readAgentStates, type AgentState } from './states';

/** A /v1 read through Work's client, cached per client and key (`work:` keys), revalidated by `invalidateV1`. */
export function useWorkV1<T>(key: string | null, read: (client: NoClick, signal: AbortSignal) => Promise<T>, options: Omit<V1Options, 'client'> = {}): V1State<T> {
    const client = useWorkClient();
    return useV1(key, (signal) => read(client, signal), { ...options, client });
}

export const AGENTS_KEY = 'work:agents';
export const STATES_KEY = 'work:states';

/** Every agent the client can see (the account's own, or a person's spaces' through their session). */
export const readAgents = (client: NoClick) => Agent.list({ client });

export function useAgents(): V1State<Agent[]> {
    return useWorkV1(AGENTS_KEY, readAgents);
}

/** The agent as the list read it, already loaded, so what's asked of it goes straight out (a lazy one reads the agent
 *  first, again for every call made before that read lands); a lazy one while the list isn't in. */
export function listedAgent(client: NoClick, agentId: string): Agent {
    return peekV1<Agent[]>(client, AGENTS_KEY)?.find((a) => a.id === agentId) ?? Agent.fromId(agentId, { client, user: null });
}

/** Where each agent stands: all of them, or one space's. */
export const statesKey = (spaceId: string | null) => `${STATES_KEY}:${spaceId ?? 'all'}`;

export function useAgentStates(spaceId: string | null, options: { enabled?: boolean } = {}): V1State<AgentState[]> {
    return useWorkV1(statesKey(spaceId), (client) => readAgentStates(client, spaceId), options);
}

/** Reads where agents stand again when the backend says something moved: any agent's turn or step, a coding agent's
 *  place, a pause, or an agent's definition (renamed, say: the agents themselves are read again too, and so are they
 *  when a space they work in changes, for its people's pages). */
export function useAgentFrames(): void {
    useWorkFrames('platform:agent', (frame) => {
        invalidateV1(STATES_KEY);
        if (frame.change === 'definition') invalidateV1(AGENTS_KEY);
    });
    useWorkFrames('platform:channel', (frame) => {
        if (frame.kind === 'workspace') invalidateV1(AGENTS_KEY);
    });
    useWorkFrames('platform:coding_agent', (frame) => {
        invalidateV1(STATES_KEY);
        if (frame.change === 'definition') invalidateV1(AGENTS_KEY);
    });
}

/** Each agent's face as Work draws it everywhere, seated as a channel seats it (`seatMembers`): the letters that tell
 *  it from the account's other agents, and its own colour unless an agent before it wears that one, then the first one
 *  free. */
export function agentFaces(agents: readonly { id: string; name: string; role?: string | null; noclick?: boolean; paused?: boolean }[]): Map<string, ChannelMember> {
    const seated = seatMembers(
        agents.map((a) => ({ id: a.id, kind: 'agent' as const, name: a.name, agentId: a.id, role: a.role ?? undefined, ...(a.noclick ? { noclick: true } : {}), ...(a.paused ? { paused: true } : {}) }))
    );
    return new Map(seated.map((m) => [m.id, m]));
}

/** The faces of every agent the client sees, by id. */
export function useAgentFaces(): Map<string, ChannelMember> {
    const { data } = useAgents();
    const noclicks = useSpaceNoClicks();
    return useMemo(() => agentFaces((data ?? []).map((a) => factsOf(a, noclicks))), [data, noclicks]);
}

/** Each agent's job to whatever draws its mascot beneath, so one that knows only its name (a channel's members, a
 *  card) dresses it as the agents list does. */
export function AgentRoles({ children }: { children: ReactNode }) {
    const faces = useAgentFaces();
    const roles = useMemo(() => new Map([...faces.values()].flatMap((f): [string, string][] => (f.role ? [[f.id, f.role]] : []))), [faces]);
    return createElement(AgentRolesContext.Provider, { value: roles }, children);
}

/** A text's first sentence, without its full stop, cut to a line (no lookbehind: Safari before 16.4 has none). */
export function firstSentence(text: string): string {
    const end = /[.!?](\s|$)/.exec(text);
    const first = (end ? text.slice(0, end.index) : text).trim().replace(/[.!?]+$/, '');
    return first.length > 90 ? `${first.slice(0, 87).trimEnd()}…` : first;
}

/** The account's own coordinator, which Work shows as NoClick (its name and mark, as a channel shows NoClick). */
export const isNoClick = (agent: { name: string; userId?: string | null }) => agent.name === COORDINATOR_AGENT && !agent.userId;

/** Whether `agent` is a NoClick, the account's own or a space's, as every platform read that lists agents flags it
 *  (`noclick`: an agent, its state, a channel's or a space's member). Work shows it as NoClick in its mark, never by
 *  the name it's found by (a space's is `noclick-<the space's id>`), and never lists, counts or offers it among a
 *  space's agents, though a channel shows it as a member. */
export const keptByNoClick = (agent: { noclick?: unknown }) => agent.noclick === true;

/** Whether `agent` is a space's own NoClick: a NoClick (`keptByNoClick`) other than the account's own. */
export const isSpaceNoClick = (agent: { name: string; userId?: string | null; noclick?: unknown }) => keptByNoClick(agent) && !isNoClick(agent);

/** What Work calls a NoClick and the line under that name, wherever it shows one (Agents, a conversation, a profile,
 *  a channel's members, the pickers). */
export interface NoClickNaming {
    name: string;
    line: string;
}

/** The one place Work names its two kinds of NoClick: the account's own (`space` null) is yours, the same assistant in
 *  every space and on your phone; a space's is that space's own, by the space's name (just NoClick until it's read). */
export function noclickNaming(space: { name?: string } | null): NoClickNaming {
    if (!space) return { name: 'Your NoClick', line: 'Your assistant everywhere, across all your spaces and your phone' };
    return { name: space.name ? `${NOCLICK_NAME} for ${space.name}` : NOCLICK_NAME, line: 'Changes this space when you ask; tells you what matters' };
}

/** What Work calls the account's own NoClick. */
export const YOUR_NOCLICK = noclickNaming(null).name;

/** A space's own NoClick, the one each of the account's spaces has: known by the agent the platform names for the
 *  space (`GET /v1/workspaces/{id}/noclick`, intro.ts), and shown as `noclickNaming` names it, never by its name. */
export interface SpaceNoClick extends NoClickNaming {
    agentId: string;
}

/** The NoClicks of the account's own spaces, by space, which name each for its space. `names`: every space Work
 *  lists (yours and the ones you joined), by workspace id, so any space's NoClick is named for its space. */
export interface SpaceNoClicks {
    of: ReadonlyMap<string, SpaceNoClick>;
    names: ReadonlyMap<string, string>;
    /** The personal spaces you joined: they have no NoClick of their own. */
    personal: ReadonlySet<string>;
}
const NONE: SpaceNoClicks = { of: new Map(), names: new Map(), personal: new Set() };
export const SpaceNoClicksContext = createContext<SpaceNoClicks>(NONE);
export const useSpaceNoClicks = () => useContext(SpaceNoClicksContext);

/** The ids of NoClick's helpers among the agents the client sees (`Agent.helper`: an app's coding agent, a child
 *  NoClick's own agent spawned), which the platform made for NoClick's own work: never yours, so Work never lists,
 *  counts or offers them. Their work shows where it happens: the chat's At work tab, an app's live editing. */
export function useHelperIds(): ReadonlySet<string> {
    const { data } = useAgents();
    return useMemo(() => new Set((data ?? []).filter((a) => a.helper).map((a) => a.id)), [data]);
}

/** NoClick's own agent's id, the account's provided agent (`isNoClick`), once the agents are read (undefined until
 *  then; null where it has none). It works across the whole account, its conversation the Chat page. */
export function useNoClickId(): string | null | undefined {
    const { data } = useAgents();
    return data ? (data.find(isNoClick)?.id ?? null) : undefined;
}

/** How Work names `agent` if it's a NoClick (`spaces`: the account's spaces' NoClicks, as read, which name one for
 *  its space; any other space's is just NoClick); null for any other agent. */
function namingOf(agent: Agent, spaces: SpaceNoClicks): NoClickNaming | null {
    if (!keptByNoClick(agent)) return null;
    if (isNoClick(agent)) return noclickNaming(null);
    return [...spaces.of.values()].find((n) => n.agentId === agent.id) ?? noclickNaming({});
}

/** Its name as Work shows it: a NoClick's as `noclickNaming` names it, any other agent's own. */
export function nameOf(agent: Agent, spaces: SpaceNoClicks = NONE): string {
    return namingOf(agent, spaces)?.name ?? agent.name;
}

/** Its job in a line, without a closing full stop: a NoClick's line, else its `role`, else its instructions' first
 *  sentence. */
export function roleOf(agent: Agent, spaces: SpaceNoClicks = NONE): string | null {
    const kept = namingOf(agent, spaces);
    if (kept) return kept.line;
    const role = (agent.raw as { role?: unknown }).role;
    if (typeof role === 'string' && role.trim()) return role.trim().replace(/\.+$/, '') || null;
    return firstSentence(agent.instructions ?? '') || null;
}

/** What a row and a face read of an agent: its name, job and harness as Work shows them, and whether it's paused. */
export const factsOf = (agent: Agent, spaces: SpaceNoClicks = NONE) => ({
    id: agent.id,
    name: nameOf(agent, spaces),
    role: roleOf(agent, spaces),
    harness: agent.harness ?? 'sdk',
    noclick: keptByNoClick(agent),
    paused: agent.paused,
});
