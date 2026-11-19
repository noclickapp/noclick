// The account's skills and memories, the agents that use each, and the changes made to them (attach, detach, hold at a
// version, read or write), read through Work's client. Resources and a space's tab read the same lists (keys
// `resources:skills`, `resources:memories`), so a change in one shows in the other, and a frame for either reads them
// again (useKnowledgeFrames).
import { useMemo } from 'react';
import { toast } from 'sonner';
import { invalidateV1 } from '@/sdk/useV1';
import type { NoClick } from 'noclick';
import { agentRef, listMemories, listSkills, MAX_MEMORIES, setAgentLinks, type AgentRef, type Knowledge, type MemoryItem, type Skill } from '@/screens/resources/knowledge';
import { AGENTS_KEY, nameOf, useAgents, useSpaceNoClicks, useWorkV1 } from '../../agents/reads';
import { useWorkFrames } from '@/sdk/live';

export const SKILLS_KEY = 'resources:skills';
export const MEMORIES_KEY = 'resources:memories';

/** An agent's use of an item: a skill held at a version (`pin`) or a memory it may write; null for its own memory. */
export interface Use {
    agent: AgentRef;
    link: { pin?: number | null; writes?: boolean } | null;
}

export interface KnowledgeState {
    loading: boolean;
    error: unknown;
    skills: Skill[];
    /** The account's named memories. */
    memories: MemoryItem[];
    /** Each agent's own memory, its agent's. */
    owns: MemoryItem[];
    agents: AgentRef[];
    find(id: string): Knowledge | undefined;
    agent(id: string): AgentRef | undefined;
    /** The agents that use it: an agent's own memory's agent first, then every agent that attaches it. */
    usersOf(item: Knowledge): Use[];
}

/** The agent whose own memory this is, else null. */
export const ownerOf = (item: Knowledge) => (item.kind === 'memory' ? item.agentId : null);

/** Its name as the viewer says it: an agent's own memory is "Its own memory" on its own profile. */
export function titleOf(item: Knowledge, owner?: AgentRef, viewer?: string): string {
    if (item.kind === 'memory' && item.agentId) return item.agentId === viewer ? 'Its own memory' : `${owner?.name ?? 'An agent'}’s memory`;
    return item.name ?? '';
}

export function useKnowledge(): KnowledgeState {
    const skills = useWorkV1(SKILLS_KEY, listSkills);
    const memories = useWorkV1(MEMORIES_KEY, listMemories);
    const agentsRead = useAgents();
    const noclicks = useSpaceNoClicks();
    return useMemo(() => {
        // Named as Work shows them: the account's coordinator is NoClick.
        const agents = (agentsRead.data ?? []).map((a) => ({ ...agentRef(a), name: nameOf(a, noclicks) }));
        const byAgent = new Map(agents.map((a) => [a.id, a]));
        const owns: MemoryItem[] = agents.flatMap((a) =>
            a.memoryId
                ? [
                      {
                          kind: 'memory' as const,
                          id: a.memoryId,
                          name: null,
                          description: `What ${a.name} learns as it works`,
                          agentId: a.id,
                          attachedTo: agents.flatMap((b) => b.memories.filter((m) => m.id === a.memoryId).map((m) => ({ id: b.id, name: b.name, writes: m.writes }))),
                          entryCount: null,
                          userId: a.userId,
                          createdAt: null,
                          updatedAt: null,
                      },
                  ]
                : []
        );
        const all = new Map<string, Knowledge>([...(skills.data ?? []), ...(memories.data ?? []), ...owns].map((i) => [i.id, i]));
        const known = (id: string, name: string): AgentRef =>
            byAgent.get(id) ?? { id, name, harness: 'sdk', model: null, userId: null, memoryId: null, skills: [], memories: [] };
        return {
            loading: (skills.loading || memories.loading || agentsRead.loading) && !(skills.data && memories.data),
            error: skills.error ?? memories.error,
            skills: skills.data ?? [],
            memories: memories.data ?? [],
            owns,
            agents,
            find: (id) => all.get(id),
            agent: (id) => byAgent.get(id),
            usersOf(item) {
                if (item.kind === 'skill') return item.attachedTo.map((a) => ({ agent: known(a.id, a.name), link: { pin: a.pin } }));
                const rest = item.attachedTo.map((a) => ({ agent: known(a.id, a.name), link: { writes: a.writes } }));
                return item.agentId ? [{ agent: known(item.agentId, ''), link: null }, ...rest] : rest;
            },
        };
    }, [skills.data, memories.data, agentsRead.data, skills.loading, memories.loading, agentsRead.loading, skills.error, memories.error, noclicks]);
}

/** Each agent's name as Work shows it, by id, for names the API gives as the agent's own (a skill's attached_to, a
 *  machine's running). */
export function useAgentNames(): ReadonlyMap<string, string> {
    const { data } = useAgents();
    const noclicks = useSpaceNoClicks();
    return useMemo(() => new Map((data ?? []).map((a) => [a.id, nameOf(a, noclicks)])), [data, noclicks]);
}

/** Reads the lists again when the backend says a skill, a memory or an agent's definition moved. */
export function useKnowledgeFrames(): void {
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'skill') invalidateV1(SKILLS_KEY);
        if (frame.kind === 'memory') invalidateV1(MEMORIES_KEY);
    });
    useWorkFrames('platform:coding_agent', (frame) => {
        if (frame.change === 'definition') {
            invalidateV1(SKILLS_KEY);
            invalidateV1(MEMORIES_KEY);
        }
    });
}

/** Everything a link changes reads again: the lists (their `attached_to`), the agents (their links). */
export function readLinksAgain(): void {
    invalidateV1(SKILLS_KEY);
    invalidateV1(MEMORIES_KEY);
    invalidateV1(AGENTS_KEY);
}

type Link = { id: string; pin?: number | null; writes?: boolean };

/** The agent's links of `item`'s kind with `change` made: a link put in (or replaced), or taken out (`null`). */
function linksWith(agent: AgentRef, item: Knowledge, change: Link | null) {
    if (item.kind === 'skill') {
        const rest = agent.skills.filter((s) => s.id !== item.id);
        return { skills: change ? [...rest, { id: item.id, pin: change.pin ?? null }] : rest };
    }
    const rest = agent.memories.filter((m) => m.id !== item.id);
    return { memories: change ? [...rest, { id: item.id, writes: !!change.writes }] : rest };
}

/** Why it can't have one more memory, or null. */
export function memoryRefusal(agent: AgentRef, item: Knowledge): string | null {
    if (item.kind !== 'memory' || agent.memories.some((m) => m.id === item.id)) return null;
    return agent.memories.length >= MAX_MEMORIES ? `${agent.name} reads ${MAX_MEMORIES} memories besides its own already` : null;
}

/** Why the agent can't write the memory, or null: an agent's own memory is written only by it. */
export function writeRefusal(agent: AgentRef, item: MemoryItem, owner?: AgentRef): string | null {
    return item.agentId && item.agentId !== agent.id ? `Only ${owner?.name ?? 'its agent'} writes its own memory` : null;
}

function failed(what: string, error: unknown) {
    toast.error(what, { description: error instanceof Error ? error.message : String(error) });
}

export async function attach(client: NoClick, agent: AgentRef, item: Knowledge, link: { pin?: number | null; writes?: boolean } = {}): Promise<boolean> {
    const refusal = memoryRefusal(agent, item);
    if (refusal) {
        toast(refusal, { description: 'Detach one first, or put related notes in one memory.' });
        return false;
    }
    try {
        await setAgentLinks(client, agent, linksWith(agent, item, { id: item.id, ...link }));
        readLinksAgain();
        return true;
    } catch (error) {
        failed(`Couldn’t attach it to ${agent.name}`, error);
        return false;
    }
}

/** Changes a link in place: a skill's version held, a memory's writes. */
export async function relink(client: NoClick, agent: AgentRef, item: Knowledge, link: { pin?: number | null; writes?: boolean }): Promise<void> {
    const kept = item.kind === 'skill' ? agent.skills.find((s) => s.id === item.id) : agent.memories.find((m) => m.id === item.id);
    if (!kept) return;
    const next = item.kind === 'skill' ? agent.skills.map((s) => (s.id === item.id ? { ...s, ...link, pin: link.pin ?? null } : s)) : null;
    try {
        await setAgentLinks(client, agent, next ? { skills: next } : { memories: agent.memories.map((m) => (m.id === item.id ? { ...m, writes: !!link.writes } : m)) });
        readLinksAgain();
    } catch (error) {
        failed(`Couldn’t change it for ${agent.name}`, error);
    }
}

/** Detaches it, saying the item stays and offering it back. */
export async function detachWithUndo(client: NoClick, agent: AgentRef, item: Knowledge, name: string): Promise<void> {
    const before = item.kind === 'skill' ? agent.skills.find((s) => s.id === item.id) : agent.memories.find((m) => m.id === item.id);
    try {
        await setAgentLinks(client, agent, linksWith(agent, item, null));
        readLinksAgain();
    } catch (error) {
        failed(`Couldn’t detach it from ${agent.name}`, error);
        return;
    }
    toast(`${name} detached from ${agent.name}`, {
        description: 'It stays in Resources, and every other agent keeps it.',
        action: before
            ? {
                  label: 'Undo',
                  // Put back as it was, on the agent as it is now.
                  onClick: () => void attach(client, { ...agent, ...linksWith(agent, item, null) }, item, before),
              }
            : undefined,
    });
}
