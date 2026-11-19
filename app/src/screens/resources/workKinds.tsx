// Work's kinds as Resources lists them: the account's agents (as Work lists them in your home, each with a page of its
// own), skills, memories (an agent's own among them), where agents run and secrets, read from the platform API with the
// console's client. Their rows, pages, removals and making one are Work's own parts (screens/work/resources), the ones a
// space's Resources tab draws, so a skill or a machine reads and acts the same in both. Those parts read Work's client
// and live frames: the console's, handed on here (where the host has no live frames, a source that never moves).
import { useEffect, useMemo, type ReactNode } from 'react';
import { Agent, ALL_USERS, Machine, User } from 'noclick';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { errorText } from '@/screens/console/pages/resources/shared';
import { createWorkLive, WorkLiveContext } from '@/sdk/live';
import { getMachineAccess } from '@/sdk/owner';
import { invalidateV1, useV1, type V1State } from '@/sdk/useV1';
import { WorkClientContext } from '@/screens/work/client';
import { AGENTS_KEY, nameOf } from '@/screens/work/agents/reads';
import { MACHINE_VIEWS_KEY } from '@/screens/work/machine/reads';
import { AgentLead, AgentLeadsProvider, AgentRowMenu, useAccountAgentItems } from '@/screens/work/resources/agentsInResources';
import { AgentResourcePage } from '@/screens/work/resources/agentPage';
import { AddMachine, CreateMemory, CreateSkill, MachinesNotice, MachineWays, WORK_KINDS, WorkResourceActions, WorkResourceBody } from '@/screens/work/resources/inResources';
import { MEMORIES_KEY, SKILLS_KEY } from '@/screens/work/resources/knowledge/store';
import { MachineResourcePage } from '@/screens/work/resources/machinePage';
import { AGENTS_ENABLED_KEY, AGENTS_NOT_ENABLED, COMPUTE_KEY, OWN_KEY } from '@/screens/work/resources/machines';
import { deletePreviewer, withOwner } from './items';
import type { KindId } from './kinds';
import type { ResourceItem } from './model';
import { agentRef, agentsOnMachines, listCompute, listMemories, listOwnComputers, listSkills, toMemory, type Knowledge } from './knowledge';
import { knowledgeRemoval, memoryItem, placeItem, placeRemoval, skillItem } from './knowledgeItems';
import type { Removal } from './platform';
import { listSecrets, secretItem, secretRemoval, SECRETS_KEY } from './secrets';
import type { MoreKinds } from './slots';

/** The kinds Work's parts draw, every item of each. */
const WORK_OWNED = new Set<KindId>(['agents', 'skills', 'memories', 'machines', 'secrets']);

/** An item's body: a skill's, memory's or machine's is Work's; an agent's whole page is Work's own (`Page`), and a
 *  secret's facts say all there is. */
function WorkBody({ item, now }: { item: ResourceItem; now: string }) {
    return WORK_KINDS.has(item.kind) ? <WorkResourceBody item={item} now={now} /> : null;
}

/** Work's kinds, read and handed on with the parts that draw them. */
export function WorkKinds({ children }: { children: (work: MoreKinds) => ReactNode }) {
    const { client, live } = useConsole();
    const still = useMemo(() => createWorkLive(), []);
    return (
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={live ?? still}>
                <Reads>{children}</Reads>
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
}

function Reads({ children }: { children: (work: MoreKinds) => ReactNode }) {
    const { client } = useConsole();
    // Skills, memories (an agent's own among them, from its agent) and where agents run: the keys a space's tab reads too.
    const skills = useV1(SKILLS_KEY, () => listSkills(client));
    const memories = useV1(MEMORIES_KEY, () => listMemories(client));
    const agents = useV1(AGENTS_KEY, () => Agent.list({ client }));
    const compute = useV1(COMPUTE_KEY, () => listCompute(client));
    const own = useV1(OWN_KEY, () => listOwnComputers(client));
    // What a machine's row adds: who's on it, its size and uptime, and whose approval a held one waits for.
    const machineViews = useV1(MACHINE_VIEWS_KEY, () => Machine.list({ client, userFilter: ALL_USERS }));
    const vetting = useV1('resources:machines/vetting', (signal) => getMachineAccess(client, signal));
    const agentsEnabled = useV1(AGENTS_ENABLED_KEY, () => agentsOnMachines(client));
    // Secrets by name, the key a space's tab reads them by too.
    const secrets = useV1(SECRETS_KEY, () => listSecrets(client));
    // The account's agents, as Work lists them in your home, with what each spent this month.
    const accountAgents = useAccountAgentItems();
    // Who a user's secret is for, by name: the read Resources' own lists name them by.
    const users = useV1('resources:users', () => User.listPage({ client, limit: 100 }));
    useEffect(() => {
        if (own.error !== undefined) console.warn('[resources] your computers failed:', own.error);
    }, [own.error]);

    const previewDeletion = useMemo(() => deletePreviewer(client), [client]);
    const agentRows = agents.data;
    const knowledge = useMemo(() => {
        // Named as Work shows them: the account's coordinator is NoClick.
        const refs = (agentRows ?? []).map((a) => ({ ...agentRef(a), name: nameOf(a) }));
        const byAgent = new Map(refs.map((a) => [a.id, a]));
        // Each agent's own memory, attached to whichever agents read it.
        const owns = refs.flatMap((a) =>
            a.memoryId
                ? [
                      toMemory({
                          id: a.memoryId,
                          agent_id: a.id,
                          description: `What ${a.name} learns as it works`,
                          attached_to: refs.flatMap((b) => b.memories.filter((m) => m.id === a.memoryId).map((m) => ({ id: b.id, name: b.name, writes: m.writes }))),
                      }),
                  ]
                : []
        );
        const all: Knowledge[] = [...(skills.data ?? []), ...(memories.data ?? []), ...owns];
        return { byAgent, owns, names: new Map(refs.map((a) => [a.id, a.name])), byId: new Map(all.map((k) => [k.id, k])) };
    }, [agentRows, skills.data, memories.data]);
    const places = useMemo(() => new Map([...(compute.data?.data ?? []), ...(own.data ?? [])].map((p) => [p.id, p])), [compute.data, own.data]);

    type Read = Pick<V1State<unknown>, 'data' | 'error' | 'loading'>;
    // A failed read has answered: the kind says why rather than waiting on it.
    const agentsRead: Read = { data: accountAgents.loading ? undefined : accountAgents.items, error: accountAgents.error, loading: accountAgents.loading && accountAgents.error === undefined };
    // Each kind's list and the reads it's drawn from, its own first: a kind draws once these answer, whatever the rest
    // still wait on. A kind whose rows name agents waits for them, so a machine never first says it has none on it.
    const reads: [KindId, Read[]][] = [
        ['agents', [agentsRead]],
        ['skills', [skills, agents]],
        ['memories', [memories, agents]],
        ['machines', [compute, own, machineViews, vetting, agents]],
        ['secrets', [secrets, agents]],
    ];
    const errors: Partial<Record<KindId, string>> = {};
    const loading: Partial<Record<KindId, boolean>> = {};
    for (const [kind, from] of reads) {
        loading[kind] = from.some((read) => read.loading);
        if (from[0].error !== undefined && from[0].data === undefined) errors[kind] = errorText(from[0].error);
    }
    const userRows = users.data?.data;
    const names = useMemo(() => new Map((userRows ?? []).flatMap((u): [string, string][] => (u.name ? [[u.id, u.name]] : []))), [userRows]);

    const work: MoreKinds = {
        items: {
            agents: accountAgents.items,
            skills: (skills.data ?? []).map((sk) => skillItem(sk, knowledge.names)),
            memories: [...(memories.data ?? []), ...knowledge.owns].map((m) => memoryItem(m, knowledge.byAgent)),
            machines: [...places.values()].map((p) => {
                const v = machineViews.data?.find((m) => m.id === p.id);
                const on = (agentRows ?? []).filter((a) => a.machineId === p.id).map((a) => nameOf(a));
                return placeItem(p, knowledge.names, { agents: on, size: v?.size ?? null, startedAt: (v?.raw.started_at as string | null | undefined) ?? null, status: v?.raw.status as string | undefined, os: v?.os ?? null, company: vetting.data?.company_name ?? null });
            }),
            secrets: (secrets.data ?? []).map((sec) => withOwner(secretItem(sec, knowledge.names), sec.userId, names)),
        },
        loading,
        errors,
        owns: (item) => WORK_OWNED.has(item.kind),
        Body: WorkBody,
        Actions: WorkResourceActions,
        Create: { skills: CreateSkill, memories: CreateMemory, machines: AddMachine },
        Empty: { machines: MachineWays },
        Notice: { machines: MachinesNotice },
        // Until agents run on machines here, a computer of yours can't be added.
        unavailable: agentsEnabled.data === false ? { machines: AGENTS_NOT_ENABLED } : {},
        Lead: { agents: AgentLead },
        Page: { agents: AgentResourcePage, machines: MachineResourcePage },
        RowMenu: { agents: AgentRowMenu },
        removal(item): Removal | null {
            const known = knowledge.byId.get(item.id);
            const place = places.get(item.id);
            if (item.kind === 'machines' && place) return placeRemoval(client, place);
            const secret = item.kind === 'secrets' ? secrets.data?.find((sec) => sec.id === item.id) : undefined;
            if (secret) {
                const removal = secretRemoval(client, secret, (path, user) => previewDeletion(path, user).catch((error: unknown) => Promise.reject(new Error(errorText(error)))));
                // Read again however far it got: the agents it came off, and the list.
                const readAgain = () => {
                    invalidateV1(SECRETS_KEY);
                    invalidateV1(AGENTS_KEY);
                };
                return { ...removal, run: () => removal.run().finally(readAgain) };
            }
            if (known && WORK_KINDS.has(item.kind)) {
                return knowledgeRemoval(client, known, (path) => previewDeletion(path, null).catch((error: unknown) => Promise.reject(new Error(errorText(error)))));
            }
            return null;
        },
    };
    return <AgentLeadsProvider value={accountAgents.leads}>{children(work)}</AgentLeadsProvider>;
}
