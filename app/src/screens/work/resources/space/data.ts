// What a space can use, as its Resources tab reads it: the space's summary (its agents and how many run, the machines
// up, and each kind's items with the agents here that use them), the resources shared with it (each at the level its
// people get), and the account's skills, memories, machines, connections and secrets to draw each one fully: its
// agents' model keys are among its connections, and the secrets they hold are its secrets, each saying which came over
// with a move from a computer. Sharing a resource with a space gives it to every person there at the level set;
// removing it takes it from them while agents that hold it as their own keep it; deleting is account-wide, to the trash.
// Home (`HOME_SPACE`) is read the same way from the account's own reads, since no space summarises it: its agents are
// every agent of the account, as home's Agents tab lists them (each saying which spaces it's in), and it has every
// machine, skill, memory, connection and secret of the account, each with the agents that use it, shared with no one.
import { useMemo, type ComponentType } from 'react';
import { BookOpen, Brain, AppWindow, Database, FileText, FolderGit2, Hash, KeyRound, Mail, Phone, Plug, Server, UsersRound, Workflow } from 'lucide-react';
import { buildGraphPreview, type GraphPreview } from '@/lib/graphPreview';
import { invalidateV1, prefetchV1 } from '@/sdk/useV1';
import { Connection, Workspace, WorkspaceResource, type Agent, type NoClick, type WorkspaceResourceKind } from 'noclick';
import { listCompute, listMemories, listOwnComputers, listSkills, type Compute, type Knowledge } from '@/screens/resources/knowledge';
import { listSecrets, SECRETS_KEY, type SecretItem } from '@/screens/resources/secrets';
import { movedFrom, type MovedFrom } from '@/lib/movedFrom';
import { entryOf, readAgentStates, ringOf, type AgentState, type RingStatus } from '../../agents/states';
import { AGENTS_KEY, factsOf, keptByNoClick, readAgents, statesKey, useAgents, useAgentStates, useSpaceNoClicks, useWorkV1 } from '../../agents/reads';
import { HOME_SPACE } from '../../place';
import { MEMORIES_KEY, SKILLS_KEY, useKnowledge, type KnowledgeState } from '../knowledge/store';
import { fixWordCasing } from '@/lib/credentialLabels';
import { refFor } from '@/lib/agentTools';
import { COMPUTE_KEY, OWN_KEY, placeName, placeUp, type Place } from '../machines';

export type SpaceKind = 'agents' | 'machines' | 'skills' | 'memories' | 'automations' | 'connections' | 'secrets' | 'channels' | 'code' | 'websites' | 'databases' | 'files' | 'numbers' | 'email';
export const SPACE_KINDS: readonly SpaceKind[] = ['agents', 'machines', 'skills', 'memories', 'automations', 'connections', 'secrets', 'channels', 'code', 'websites', 'databases', 'files', 'numbers', 'email'];
/** Home's: what its agents work with. What a space shares with its people (channels, code, sites…) it has none of. */
export const HOME_KINDS: readonly SpaceKind[] = ['agents', 'machines', 'skills', 'memories', 'connections', 'secrets'];
/** The kinds the space's summary doesn't list: its machines come apart, its secrets are what its agents hold. */
type OwnRead = 'agents' | 'machines' | 'secrets';
const isSummaryKind = (k: SpaceKind): k is Exclude<SpaceKind, OwnRead> => k !== 'agents' && k !== 'machines' && k !== 'secrets';

/** What a space shares with its people: each kind as a link names it. */
export type LinkKind = 'connection' | 'app' | 'database' | 'files' | 'repo' | 'skill' | 'memory' | 'machine' | 'automation';
export const LINK_KIND: Partial<Record<SpaceKind, LinkKind>> = {
    machines: 'machine',
    automations: 'automation',
    connections: 'connection',
    websites: 'app',
    databases: 'database',
    files: 'files',
    code: 'repo',
    skills: 'skill',
    memories: 'memory',
};

/** A kind's mark: a line icon, as the sidebar draws its pages (Automations its own). The coloured automation mark is
 *  one automation's, where a pill or a card points at it, never the kind's. */
export type KindIcon = ComponentType<{ className?: string; strokeWidth?: number }>;

/** Each kind as the tab names it; `make` is its way to make one here (none for secrets, which an agent's own page holds). */
export const KINDS: { id: SpaceKind; label: string; icon: KindIcon; group: 'work' | 'know' | 'reach'; noun: [string, string]; make?: string }[] = [
    { id: 'agents', label: 'Agents', icon: UsersRound, group: 'work', noun: ['agent', 'agents'], make: 'New agent' },
    { id: 'machines', label: 'Machines', icon: Server, group: 'work', noun: ['machine', 'machines'], make: 'New machine' },
    { id: 'skills', label: 'Skills', icon: BookOpen, group: 'know', noun: ['skill', 'skills'], make: 'New skill' },
    { id: 'memories', label: 'Memories', icon: Brain, group: 'know', noun: ['memory', 'memories'], make: 'New memory' },
    { id: 'automations', label: 'Automations', icon: Workflow, group: 'reach', noun: ['automation', 'automations'], make: 'New automation' },
    { id: 'connections', label: 'Connections', icon: Plug, group: 'reach', noun: ['connection', 'connections'], make: 'Connect an account' },
    { id: 'secrets', label: 'Secrets', icon: KeyRound, group: 'reach', noun: ['secret', 'secrets'] },
    { id: 'channels', label: 'Channels', icon: Hash, group: 'reach', noun: ['channel', 'channels'], make: 'New channel' },
    { id: 'code', label: 'Code', icon: FolderGit2, group: 'reach', noun: ['repository', 'repositories'], make: 'New repository' },
    { id: 'websites', label: 'Websites', icon: AppWindow, group: 'reach', noun: ['website', 'websites'], make: 'New website' },
    { id: 'databases', label: 'Databases', icon: Database, group: 'reach', noun: ['database', 'databases'], make: 'New database' },
    { id: 'files', label: 'Files', icon: FileText, group: 'reach', noun: ['file folder', 'file folders'], make: 'Upload files' },
    { id: 'numbers', label: 'Numbers', icon: Phone, group: 'reach', noun: ['number', 'numbers'], make: 'Buy a number' },
    { id: 'email', label: 'Email', icon: Mail, group: 'reach', noun: ['address', 'addresses'], make: 'New address' },
];
export const GROUPS = { work: 'Working here', know: 'What they know', reach: 'What they reach' } as const;
export const kindOf = (id: SpaceKind) => KINDS.find((k) => k.id === id)!;
export const isSpaceKind = (v: string | null): v is SpaceKind => !!v && (SPACE_KINDS as readonly string[]).includes(v);

// ── the wire ───────────────────────────────────────────────────────────────

type Wire = Record<string, unknown>;
const text = (v: unknown) => (typeof v === 'string' ? v : '');
const maybe = (v: unknown) => (typeof v === 'string' && v ? v : null);
const count = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const rows = (v: unknown) => (Array.isArray(v) ? (v as Wire[]) : []);
const obj = (v: unknown) => (v && typeof v === 'object' ? (v as Wire) : {});

/** A resource shared with the space: everyone in it gets it at `membersLevel`, guests at `guestsLevel`. */
export interface SpaceLink {
    id: string;
    kind: LinkKind;
    ref: string;
    name: string;
    membersLevel: string;
    guestsLevel: string;
    /** The levels its kind takes, in order. */
    levels: string[];
    addedBy: { type: string; id: string | null; name: string | null } | null;
    addedAt: string | null;
    /** The API's own view, which the SDK changes and removes it through. */
    raw: Wire;
}

export function toLink(raw: Wire): SpaceLink {
    const by = raw.added_by ? obj(raw.added_by) : null;
    return {
        id: text(raw.id),
        kind: text(raw.kind) as LinkKind,
        ref: text(raw.ref),
        name: text(raw.name),
        membersLevel: text(raw.members_level) || 'none',
        guestsLevel: text(raw.guests_level) || 'none',
        levels: rows(raw.levels).map(String),
        addedBy: by ? { type: text(by.type), id: maybe(by.id), name: maybe(by.name) } : null,
        addedAt: maybe(raw.added_at),
        raw,
    };
}

export interface SummaryItem {
    id: string;
    ref: string;
    name: string;
    linked: boolean;
    membersLevel: string | null;
    guestsLevel: string | null;
    /** The agents here that use it. */
    usedBy: string[];
    /** What its people hold through it (the account: its highest). */
    level: string | null;
    /** An automation's last run and next one, where its people read its runs, with its description, when it last
     *  changed and a picture of its graph, as the Automations page's cards draw one. */
    lastRun?: LastRun | null;
    nextRun?: string | null;
    description?: string | null;
    updatedAt?: string | null;
    preview?: GraphPreview | null;
}
/** An automation's last run, whoever started it: `at` when it ended, else when it started. */
export interface LastRun {
    id: string;
    /** `running`, `succeeded` or `failed`. */
    status: string;
    at: string | null;
    error: string | null;
}
export interface SummaryAgent {
    id: string;
    name: string;
    /** A NoClick (the account's own or the space's), as the platform flags it. */
    noclick: boolean;
    state: string;
    harness: string | null;
    model: string | null;
}
export interface SummaryMachine {
    id: string;
    kind: 'sandbox' | 'machine';
    /** The machine a container runs on (null for a sandbox). */
    machineId: string | null;
    agentId: string | null;
    state: string;
    /** A computer of yours, where the summary says (a machine shared with the space). */
    own?: boolean;
}
/** A machine shared with the space: the agents here placed on it are its `usedBy`. */
export interface SharedMachine extends SummaryItem {
    own: boolean;
    status: string;
}
export interface SpaceSummary {
    agents: { count: number; working: number; waiting: number; idle: number; items: SummaryAgent[] };
    machines: { count: number; up: number; items: SummaryMachine[]; shared: SharedMachine[] };
    items: Record<Exclude<SpaceKind, OwnRead>, SummaryItem[]>;
}

const toLastRun = (r: Wire): LastRun => ({ id: text(r.id), status: text(r.status), at: maybe(r.at), error: maybe(r.error) });

const toItem = (i: Wire): SummaryItem => ({
    id: text(i.id),
    ref: text(i.ref) || text(i.id),
    name: text(i.name),
    linked: i.linked === true,
    membersLevel: maybe(i.members_level),
    guestsLevel: maybe(i.guests_level),
    usedBy: rows(i.used_by).map(String),
    level: maybe(i.level),
    ...('last_run' in i
        ? {
              lastRun: i.last_run ? toLastRun(obj(i.last_run)) : null,
              nextRun: maybe(i.next_run),
              description: maybe(i.description),
              updatedAt: maybe(i.updated_at),
              preview: buildGraphPreview(i.preview) ?? null,
          }
        : {}),
});

export function toSummary(raw: Wire): SpaceSummary {
    const kinds = obj(raw.kinds);
    const agents = obj(kinds.agents);
    const machines = obj(kinds.machines);
    const items = Object.fromEntries(SPACE_KINDS.filter(isSummaryKind).map((k) => [k, rows(obj(kinds[k]).items).map(toItem)])) as SpaceSummary['items'];
    return {
        agents: {
            count: count(agents.count),
            working: count(agents.working),
            waiting: count(agents.waiting),
            idle: count(agents.idle),
            items: rows(agents.items).map((a) => ({ id: text(a.id), name: text(a.name), noclick: a.noclick === true, state: text(a.state), harness: maybe(a.harness), model: maybe(a.model) })),
        },
        machines: {
            count: count(machines.count),
            up: count(machines.up),
            items: rows(machines.items).map((m) => ({
                id: text(m.id),
                kind: m.kind === 'machine' ? 'machine' : 'sandbox',
                machineId: maybe(m.machine_id),
                agentId: maybe(m.agent_id),
                state: text(m.state),
            })),
            shared: rows(machines.shared).map((m) => ({ ...toItem(m), own: m.kind === 'own', status: text(m.status) })),
        },
        items,
    };
}

export const summaryKey = (spaceId: string) => `work:space/${spaceId}/summary`;
export const linksKey = (spaceId: string) => `work:space/${spaceId}/resources`;
export const CONNECTIONS_KEY = 'resources:connections';
/** What an agent NoClick made itself runs on in place of a connection: NoClick's own key. */
const NOCLICK_KEY = 'noclick';
export const SPACES_KEY = 'work:spaces/members';

const workspace = (client: NoClick, spaceId: string) => Workspace.fromId(spaceId, { client, user: null });

export async function readSummary(client: NoClick, spaceId: string): Promise<SpaceSummary> {
    return toSummary((await workspace(client, spaceId).summary()).raw);
}
export async function readLinks(client: NoClick, spaceId: string): Promise<SpaceLink[]> {
    return (await workspace(client, spaceId).resources()).map((r) => toLink(r.raw));
}

/** The resources shared with a space, each with what its people and its guests get (`levels` the ones its kind takes);
 *  null reads nothing. */
export function useSpaceLinks(spaceId: string | null) {
    return useWorkV1(spaceId ? linksKey(spaceId) : null, (client) => readLinks(client, spaceId!));
}

/** Every change to what the space holds reads its summary and links again. */
export function readSpaceAgain(spaceId: string): void {
    invalidateV1(summaryKey(spaceId));
    invalidateV1(linksKey(spaceId));
}

export async function share(client: NoClick, spaceId: string, kind: LinkKind, ref: string): Promise<SpaceLink> {
    return toLink((await workspace(client, spaceId).share(kind as WorkspaceResourceKind, ref)).raw);
}
export async function unshare(client: NoClick, link: SpaceLink): Promise<void> {
    await new WorkspaceResource(link.raw, client, null).remove();
}
export async function setLevels(client: NoClick, link: SpaceLink, levels: { membersLevel?: string; guestsLevel?: string }): Promise<void> {
    await new WorkspaceResource(link.raw, client, null).update(levels);
}

// ── words for levels ───────────────────────────────────────────────────────

const LEVEL_WORDS: Record<string, string> = { none: 'None', agents: 'Through agents only', use: 'Can use', view: 'View', read: 'Read', add: 'Read and add', write: 'Read and write' };
/** A machine's: its people see it, then may also put the space's agents on it. Its shell stays yours either way. */
const MACHINE_WORDS: Record<string, string> = { run: 'See it', use: 'Put agents on it' };
/** An automation's: its people see its runs, then also run it, then also change it. */
const AUTOMATION_WORDS: Record<string, string> = { runs: 'See runs', run: 'Run', edit: 'Run and edit' };
/** The levels of an automation at which its people run it (`run`, `edit`). */
export const RUNS_IT: readonly string[] = ['run', 'edit'];

/** A level as people read it: a database reached through agents is queried through them. */
export function levelWords(kind: LinkKind, level: string): string {
    if (kind === 'machine' && MACHINE_WORDS[level]) return MACHINE_WORDS[level];
    if (kind === 'automation' && AUTOMATION_WORDS[level]) return AUTOMATION_WORDS[level];
    if (kind === 'database' && level === 'agents') return 'Query through agents';
    return LEVEL_WORDS[level] ?? level;
}

// ── one item, whatever its kind ────────────────────────────────────────────

/** One item the space has, whatever its kind: what every list, page, picker and confirm reads. */
export interface Thing {
    key: string;
    kind: SpaceKind;
    /** The resource's own id (its ref when shared). */
    ref: string;
    name: string;
    /** Shared with the space: its people get it at the link's level. */
    link: SpaceLink | null;
    /** The agents here that use it. */
    usedBy: string[];
    agent?: SummaryAgent;
    machine?: SummaryMachine;
    place?: Place;
    knowledge?: Knowledge;
    secret?: SecretItem;
    /** Where a move carried it from (a connection or a secret), when it came over with one. */
    movedFrom?: MovedFrom | null;
    /** An automation: what its people here hold of it, and its runs and its picture where they read them. */
    automation?: Pick<SummaryItem, 'level' | 'lastRun' | 'nextRun' | 'description' | 'updatedAt' | 'preview'>;
}

export const thingKey = (kind: SpaceKind, ref: string) => `${kind}:${ref}`;

/** A connection's name as an app's: "github" → "GitHub", "work_gmail" → "Work Gmail". */
export const appName = (slug: string) => fixWordCasing(slug.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()));

export interface AgentHere {
    id: string;
    name: string;
    harness: string | null;
    model: string | null;
    status: RingStatus;
    /** What it's doing now, else its job. */
    line: string;
    /** Things waiting on a person. */
    needs: number;
    /** The other spaces it's in, by name. */
    elsewhere: string[];
}

export interface SpaceShare {
    /** Home: every agent and everything of the account's, shared with no one. */
    home: boolean;
    /** The kinds it lists. */
    kinds: readonly SpaceKind[];
    loading: boolean;
    error: unknown;
    summary: SpaceSummary | null;
    links: SpaceLink[];
    /** The space's items of a kind, the ones needing you first for agents. */
    of(kind: SpaceKind): Thing[];
    find(key: string): Thing | undefined;
    agents: AgentHere[];
    agent(id: string): AgentHere | undefined;
    /** Machines up now: its agents' sandboxes, machines kept on and computers of yours. */
    up: { sandboxes: number; keptOn: number; own: number };
    /** The spaces each agent of the account is in, by agent id (names). */
    spacesOf(agentId: string): string[];
    spaceName: string;
    /** The account's spaces, to share one with, each with the agents in it. */
    spaces: { id: string; name: string; logoUrl?: string; agentIds: string[] }[];
}

const RANK: Record<RingStatus, number> = { needs: 0, failed: 1, working: 2, waking: 3, idle: 4 };

/** A computer of yours: by its place where the account reads it, else as the space's summary says. */
export const ownMachine = (t: Thing) => (t.place ? t.place.kind === 'own' : !!t.machine?.own);

/** Where the space's agents run now, one row per place (an agent's sandbox, or a machine running several agents), the
 *  machines shared with it (with the agents here placed on each), then every computer of yours (online or not,
 *  whatever runs there). */
function machineRows(s: SpaceSummary | null, places: ReadonlyMap<string, Place>, own: Place[], names: ReadonlyMap<string, string>): Thing[] {
    const rows = new Map<string, Thing>();
    for (const m of s?.machines.items ?? []) {
        const ref = m.machineId ?? m.id;
        const row = rows.get(ref);
        if (row) {
            if (m.agentId && !row.usedBy.includes(m.agentId)) row.usedBy.push(m.agentId);
            continue;
        }
        const place = places.get(ref);
        rows.set(ref, { key: thingKey('machines', ref), kind: 'machines', ref, name: placeName(place, names) ?? ref, link: null, usedBy: m.agentId ? [m.agentId] : [], machine: m, place });
    }
    for (const m of s?.machines.shared ?? []) {
        const row = rows.get(m.ref);
        if (row) {
            row.usedBy = [...new Set([...row.usedBy, ...m.usedBy])];
            continue;
        }
        const place = places.get(m.ref);
        const machine: SummaryMachine = { id: m.ref, kind: 'machine', machineId: m.ref, agentId: null, state: m.status, own: m.own };
        rows.set(m.ref, { key: thingKey('machines', m.ref), kind: 'machines', ref: m.ref, name: placeName(place, names) ?? m.name, link: null, usedBy: [...m.usedBy], machine, place });
    }
    for (const p of own) if (!rows.has(p.id)) rows.set(p.id, { key: thingKey('machines', p.id), kind: 'machines', ref: p.id, name: p.name, link: null, usedBy: [], place: p });
    return [...rows.values()];
}

/** The summary without the NoClick agents among its agents or their counts: the account's works across the account,
 *  and the space's answers in its NoClick channel. */
function withoutNoClick(summary: SpaceSummary): SpaceSummary {
    const kept = summary.agents.items.filter(keptByNoClick);
    if (!kept.length) return summary;
    const less = (state: 'working' | 'waiting' | 'idle') => summary.agents[state] - kept.filter((a) => a.state === state).length;
    return {
        ...summary,
        agents: { count: summary.agents.count - kept.length, working: less('working'), waiting: less('waiting'), idle: less('idle'), items: summary.agents.items.filter((a) => !kept.includes(a)) },
    };
}

/** Home's summary, from the account's own reads: every agent of yours (never NoClick's own, nor its helpers) and how
 *  each stands, where they run (and every machine kept on, whoever runs there), and every skill, memory and connection
 *  with the agents that use it. */
function homeSummary({ agents, states, compute, knowledge, connections }: { agents: Agent[]; states: AgentState[]; compute: Compute[]; knowledge: KnowledgeState; connections: Connection[] }): SpaceSummary {
    const ids = new Set(agents.map((a) => a.id));
    const ring = new Map(states.map((st) => [st.agentId, ringOf(st.state)]));
    const stateOf = (id: string) => {
        const r = ring.get(id) ?? 'idle';
        return r === 'needs' ? 'waiting' : r === 'working' || r === 'waking' ? 'working' : 'idle';
    };
    const agentItems: SummaryAgent[] = agents.map((a) => ({ id: a.id, name: a.name, noclick: a.noclick, state: stateOf(a.id), harness: a.harness ?? null, model: a.model ?? null }));
    const machines: SummaryMachine[] = compute.flatMap((c): SummaryMachine[] => {
        // A developer's sandbox runs code, not an agent.
        if (c.kind === 'sandbox') return [];
        const kept = c.kind === 'machine';
        // Each agent once: its one session runs there, whoever talks to it.
        const agentIds = [...new Set(c.running.filter((r) => ids.has(r.agentId)).map((r) => r.agentId))];
        if (!agentIds.length) return kept ? [{ id: c.id, kind: 'machine', machineId: c.id, agentId: null, state: c.status }] : [];
        return agentIds.map((agentId) => ({ id: c.id, kind: kept ? 'machine' : 'sandbox', machineId: kept ? c.id : null, agentId, state: c.status }));
    });
    const item = (ref: string, name: string, usedBy: string[]): SummaryItem => ({ id: ref, ref, name, linked: false, membersLevel: null, guestsLevel: null, usedBy: [...new Set(usedBy)].filter((a) => ids.has(a)), level: null });
    const known = (k: Knowledge) => item(k.id, k.name ?? '', knowledge.usersOf(k).map((u) => u.agent.id));
    const none = Object.fromEntries(SPACE_KINDS.filter(isSummaryKind).map((k) => [k, [] as SummaryItem[]])) as SpaceSummary['items'];
    const count = (state: string) => agentItems.filter((a) => a.state === state).length;
    return {
        agents: { count: agentItems.length, working: count('working'), waiting: count('waiting'), idle: count('idle'), items: agentItems },
        machines: { count: machines.length, up: machines.filter((m) => m.kind === 'sandbox' || m.state === 'running').length, items: machines, shared: [] },
        items: {
            ...none,
            skills: knowledge.skills.map(known),
            memories: knowledge.memories.map(known),
            // A space names a connection by the ref an agent's tools name it by: a named one by its name, an account
            // connected in the app by `credential:<id>` (its name names no connection, or another one).
            connections: connections.map((c) => item(refFor(c), c.name, c.usedBy.filter((h) => h.kind === 'agent').map((h) => h.id))),
        },
    };
}

export const readSpaces = (client: NoClick) => Workspace.list({ client, status: 'active' });

/** The names of the spaces each agent of the account works in, by agent id: an agent is the account's, and any number
 *  of its spaces can have it. */
export function spacesByAgent(spaces: readonly Workspace[]): Map<string, string[]> {
    const memberOf = new Map<string, string[]>();
    for (const w of spaces) for (const m of w.members) if (m.agentId) memberOf.set(m.agentId, [...(memberOf.get(m.agentId) ?? []), w.name]);
    return memberOf;
}
const readConnections = (client: NoClick) => Connection.list({ client });

/** Reads ahead what a space's Resources tab shows (the pointer resting on the tab), each read `useSpaceShare` makes,
 *  under its key, unless it was read in the last minute. */
export function prefetchSpaceShare(client: NoClick, spaceId: string): void {
    const home = spaceId === HOME_SPACE;
    const reads: [string, (client: NoClick) => Promise<unknown>][] = [
        [statesKey(home ? null : spaceId), (c) => readAgentStates(c, home ? null : spaceId)],
        [AGENTS_KEY, readAgents],
        [SKILLS_KEY, listSkills],
        [MEMORIES_KEY, listMemories],
        [COMPUTE_KEY, listCompute],
        [OWN_KEY, listOwnComputers],
        [SPACES_KEY, readSpaces],
        [CONNECTIONS_KEY, readConnections],
        [SECRETS_KEY, listSecrets],
    ];
    if (!home) reads.push([summaryKey(spaceId), (c) => readSummary(c, spaceId)], [linksKey(spaceId), (c) => readLinks(c, spaceId)]);
    for (const [key, read] of reads) prefetchV1(client, key, () => read(client), 60_000);
}

/** The space's own read, from its summary and links, drawn with the account's knowledge and machines; home's from the
 *  account's reads alone. */
export function useSpaceShare(spaceId: string): SpaceShare {
    const home = spaceId === HOME_SPACE;
    const summary = useWorkV1(home ? null : summaryKey(spaceId), (client) => readSummary(client, spaceId));
    const links = useSpaceLinks(home ? null : spaceId);
    const states = useAgentStates(home ? null : spaceId);
    const agentsRead = useAgents();
    const knowledge = useKnowledge();
    const compute = useWorkV1(COMPUTE_KEY, listCompute);
    const own = useWorkV1(OWN_KEY, listOwnComputers);
    const spaces = useWorkV1(SPACES_KEY, readSpaces);
    const connections = useConnections();
    const secrets = useWorkV1(SECRETS_KEY, listSecrets);
    const noclicks = useSpaceNoClicks();
    return useMemo(() => {
        const memberOf = spacesByAgent(spaces.data ?? []);
        // Home's is whole once it knows its agents: the rest fill in as they're read.
        const s = home
            ? agentsRead.data
                ? homeSummary({ agents: agentsRead.data.filter((a) => !keptByNoClick(a) && !a.helper), states: states.data ?? [], compute: compute.data?.data ?? [], knowledge, connections: connections.data ?? [] })
                : null
            : summary.data
              ? withoutNoClick(summary.data)
              : null;
        const linked = links.data ?? [];
        const now = Date.now();
        // Named and described as Work shows them: the account's coordinator is NoClick.
        const facts = new Map((agentsRead.data ?? []).map((a) => [a.id, factsOf(a, noclicks)]));
        const stateOf = new Map((states.data ?? []).map((st) => [st.agentId, st]));
        const spaceName = (spaces.data ?? []).find((w) => w.id === spaceId)?.name ?? '';
        const agents: AgentHere[] = (s?.agents.items ?? []).map((a) => {
            const st = stateOf.get(a.id);
            const entry = st ? entryOf(st, facts.get(a.id), now) : null;
            return {
                id: a.id,
                name: facts.get(a.id)?.name ?? a.name,
                harness: a.harness,
                model: a.model,
                status: st ? ringOf(st.state) : a.state === 'working' ? 'working' : a.state === 'waiting' ? 'needs' : 'idle',
                line: entry?.line ?? facts.get(a.id)?.role ?? '',
                needs: st?.waiting.total ?? 0,
                elsewhere: (memberOf.get(a.id) ?? []).filter((n) => n !== spaceName),
            };
        });
        agents.sort((a, b) => RANK[a.status] - RANK[b.status]);
        const places = new Map<string, Place>([...(compute.data?.data ?? []), ...(own.data ?? [])].map((p) => [p.id, p]));
        const linkOf = (kind: SpaceKind, ref: string) => linked.find((l) => l.kind === LINK_KIND[kind] && l.ref === ref) ?? null;
        const things: Thing[] = [
            ...agents.map((a) => ({ key: thingKey('agents', a.id), kind: 'agents' as const, ref: a.id, name: a.name, link: null, usedBy: [a.id], agent: s!.agents.items.find((x) => x.id === a.id) })),
            ...machineRows(s, places, own.data ?? [], new Map([...facts].map(([id, f]) => [id, f.name]))).map((t) => ({ ...t, link: linkOf('machines', t.ref) })),
            ...SPACE_KINDS.filter(isSummaryKind).flatMap((kind) =>
                (s?.items[kind] ?? []).map((i) => ({
                    key: thingKey(kind, i.ref),
                    kind,
                    ref: i.ref,
                    name: kind === 'memories' || kind === 'skills' ? (knowledge.find(i.ref)?.name ?? i.name) : kind === 'connections' ? appName(i.name) : i.name,
                    link: linkOf(kind, i.ref),
                    usedBy: [...i.usedBy],
                    knowledge: kind === 'memories' || kind === 'skills' ? knowledge.find(i.ref) : undefined,
                    automation: kind === 'automations' ? { level: i.level, lastRun: i.lastRun, nextRun: i.nextRun, description: i.description, updatedAt: i.updatedAt, preview: i.preview } : undefined,
                }))
            ),
        ];
        // Each agent here keeps a memory of its own, which the summary leaves to its agent.
        for (const m of knowledge.owns) {
            if (m.agentId && agents.some((a) => a.id === m.agentId) && !things.some((t) => t.kind === 'memories' && t.ref === m.id)) {
                things.push({ key: thingKey('memories', m.id), kind: 'memories', ref: m.id, name: '', link: null, usedBy: [m.agentId], knowledge: m });
            }
        }
        // An agent here that runs on a key of its own uses that connection too (a move's model key is one).
        const here = new Set(agents.map((a) => a.id));
        const conns = connections.data ?? [];
        const connOf = (ref: string) => conns.find((c) => c.id === ref || refFor(c) === ref);
        for (const a of agentsRead.data ?? []) {
            const name = a.modelConnection;
            if (!here.has(a.id) || !name || name === NOCLICK_KEY) continue;
            const row = things.find((t) => t.kind === 'connections' && (t.ref === name || (!!connOf(name) && connOf(t.ref) === connOf(name))));
            if (row) {
                if (!row.usedBy.includes(a.id)) row.usedBy.push(a.id);
            } else things.push({ key: thingKey('connections', name), kind: 'connections', ref: name, name: appName(name), link: null, usedBy: [a.id] });
        }
        for (const t of things) if (t.kind === 'connections') t.movedFrom = movedFrom(connOf(t.ref)?.raw.moved_from);
        // The secrets its agents hold, each by name: the account's, in the space through them (home has every one).
        for (const sec of secrets.data ?? []) {
            const users = sec.agents.filter((a) => here.has(a.id)).map((a) => a.id);
            if (users.length || home) things.push({ key: thingKey('secrets', sec.id), kind: 'secrets', ref: sec.id, name: sec.name, link: null, usedBy: users, secret: sec, movedFrom: sec.movedFrom });
        }
        const byKey = new Map(things.map((t) => [t.key, t]));
        const machinesUp = things.filter((t) => t.kind === 'machines' && (t.place ? placeUp(t.place) : t.machine?.state === 'running'));
        const statusRank = new Map(agents.map((a, i) => [a.id, i]));
        return {
            home,
            kinds: home ? HOME_KINDS : SPACE_KINDS,
            loading: !s && (home ? agentsRead.loading : summary.loading),
            error: home ? agentsRead.error : summary.error,
            summary: s,
            links: linked,
            of(kind) {
                const list = things.filter((t) => t.kind === kind);
                if (kind === 'agents') return list.sort((a, b) => (statusRank.get(a.ref) ?? 0) - (statusRank.get(b.ref) ?? 0));
                if (kind === 'skills' || kind === 'memories') return list.sort((a, b) => b.usedBy.length - a.usedBy.length);
                return list;
            },
            find: (key) => byKey.get(key),
            agents,
            agent: (id) => agents.find((a) => a.id === id),
            up: {
                sandboxes: machinesUp.filter((t) => t.machine?.kind === 'sandbox').length,
                keptOn: machinesUp.filter((t) => t.machine?.kind === 'machine' && !ownMachine(t)).length,
                own: machinesUp.filter(ownMachine).length,
            },
            spacesOf: (agentId) => memberOf.get(agentId) ?? [],
            spaceName,
            spaces: (spaces.data ?? []).map((w) => ({ id: w.id, name: w.name, logoUrl: w.logoUrl ?? undefined, agentIds: w.members.flatMap((m) => (m.agentId ? [m.agentId] : [])) })),
        };
    }, [home, summary.data, summary.loading, summary.error, links.data, states.data, agentsRead.data, agentsRead.loading, agentsRead.error, knowledge, compute.data, own.data, spaces.data, connections.data, secrets.data, spaceId, noclicks]);
}

/** The account's connections, read once for the tab's connection rows and pages (status, account, who holds it). */
export function useConnections() {
    return useWorkV1(CONNECTIONS_KEY, readConnections);
}
