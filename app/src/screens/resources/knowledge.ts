// Skills, memories and the machines agents run on, as Resources and Work read and change them: each skill (a SKILL.md
// folder, versioned) and memory (named entries) is the account's, attached to any number of its agents, and the
// account's agents are where those links live (`skills: [{id, pin}]`, `memories: [{id, writes}]`). The compute list
// is every NoClick machine held, every agent sandbox up now and every developer sandbox live. Read through the
// platform client (the console's in Resources, Work's in a space), over the API's own JSON.
import { ALL_USERS, Machine, Memory, Skill as SdkSkill, TrashItem, compute, type Agent, type AppTesting, type NoClick, type SkillFiles } from 'noclick';
import { toMemoryEntry } from '@/sdk/source';

type Wire = Record<string, unknown>;
const text = (v: unknown) => (typeof v === 'string' ? v : '');
const maybe = (v: unknown) => (typeof v === 'string' && v ? v : null);
const count = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const list = (v: unknown) => (Array.isArray(v) ? (v as Wire[]) : []);
const obj = (v: unknown) => (v && typeof v === 'object' ? (v as Wire) : null);

/** The most of each list Resources reads; the console pages past it. */
const LIMIT = 100;

/** Who made a version or wrote an entry: a person in the app, a key, or an agent as it worked. */
export interface Writer {
    type: 'console' | 'api' | 'agent';
    agentId: string | null;
    agentName: string | null;
    /** The conversation an agent learned it in. */
    conversation?: string | null;
}

function writer(raw: unknown): Writer | null {
    const w = obj(raw);
    if (!w) return null;
    return { type: (text(w.type) || 'console') as Writer['type'], agentId: maybe(w.agent_id), agentName: maybe(w.agent_name), conversation: maybe(w.conversation) };
}

// ── skills ─────────────────────────────────────────────────────────────────

export interface SkillLink {
    /** The agent. */
    id: string;
    name: string;
    /** Held at this version; null follows the latest. */
    pin: number | null;
}

export interface Skill {
    kind: 'skill';
    id: string;
    name: string;
    description: string;
    /** In every turn: added to the instructions rather than read when needed. */
    always: boolean;
    /** Its latest version. */
    version: number;
    fileCount: number;
    size: number;
    attachedTo: SkillLink[];
    userId: string | null;
    createdAt: string | null;
    updatedAt: string | null;
}

export function toSkill(raw: Wire): Skill {
    return {
        kind: 'skill',
        id: text(raw.id),
        name: text(raw.name),
        description: text(raw.description),
        always: raw.always === true,
        version: count(raw.version) ?? 1,
        fileCount: count(raw.file_count) ?? 1,
        size: count(raw.size) ?? 0,
        attachedTo: list(raw.attached_to).map((a) => ({ id: text(a.id), name: text(a.name), pin: count(a.pin) })),
        userId: maybe(raw.user_id),
        createdAt: maybe(raw.created_at),
        updatedAt: maybe(raw.updated_at),
    };
}

export interface SkillVersion {
    version: number;
    name: string;
    description: string;
    always: boolean;
    files: { path: string; size: number; sha256: string }[];
    size: number;
    createdBy: Writer | null;
    createdAt: string | null;
}

function toSkillVersion(raw: Wire): SkillVersion {
    return {
        version: count(raw.version) ?? 1,
        name: text(raw.name),
        description: text(raw.description),
        always: raw.always === true,
        files: list(raw.files).map((f) => ({ path: text(f.path), size: count(f.size) ?? 0, sha256: text(f.sha256) })),
        size: count(raw.size) ?? 0,
        createdBy: writer(raw.created_by),
        createdAt: maybe(raw.created_at),
    };
}

/** A file of a skill as written: its path and its text (base64 for bytes). */
export interface SkillFile {
    path: string;
    content: string;
    encoding?: 'utf-8' | 'base64';
}

export async function listSkills(client: NoClick): Promise<Skill[]> {
    return (await SdkSkill.list({ client, limit: LIMIT })).map((s) => toSkill(s.raw));
}

export async function skillVersions(client: NoClick, id: string): Promise<SkillVersion[]> {
    return (await SdkSkill.fromId(id, { client }).versions()).map((v) => toSkillVersion(v.raw));
}

/** One file's text at a version (the latest without one). */
export async function readSkillFile(client: NoClick, id: string, path: string, version?: number): Promise<SkillFile> {
    const file = await SdkSkill.fromId(id, { client }).read(path, { version });
    return { path: file.path, content: file.content, encoding: file.encoding };
}

/** Files as the SDK takes them: text as it is, base64 back to its bytes. */
function sdkFiles(files: SkillFile[]): SkillFiles {
    return Object.fromEntries(files.map((f) => [f.path, f.encoding === 'base64' ? Uint8Array.from(atob(f.content), (c) => c.charCodeAt(0)) : f.content]));
}

/** A new skill from its files; its name and description are SKILL.md's frontmatter. */
export async function createSkill(client: NoClick, files: SkillFile[]): Promise<Skill> {
    return toSkill((await SdkSkill.create(sdkFiles(files), { client })).raw);
}

/** A new version: `files` written over the latest, refused if the latest moved past `baseVersion`. */
export async function saveSkill(client: NoClick, id: string, files: SkillFile[], baseVersion: number): Promise<Skill> {
    return toSkill((await SdkSkill.fromId(id, { client }).saveVersion(sdkFiles(files), { baseVersion })).raw);
}

/** A new version copying `version`'s files. */
export async function restoreSkill(client: NoClick, id: string, version: number): Promise<Skill> {
    return toSkill((await SdkSkill.fromId(id, { client }).restore(version)).raw);
}

/** The frontmatter for a skill's SKILL.md, then its instructions. */
export function skillMarkdown(name: string, description: string, body: string, always = false): string {
    return `---\nname: ${name}\ndescription: ${description.replace(/\s*\n\s*/g, ' ')}\n${always ? 'always: true\n' : ''}---\n\n${body.trim() || '…'}\n`;
}

/** SKILL.md's frontmatter fields (name, description, always), or null where it has none. */
export function frontmatter(markdown: string): { name: string; description: string; always: boolean } | null {
    const match = /^---\r?\n([\s\S]*?)\r?\n---/.exec(markdown);
    if (!match) return null;
    const field = (key: string) => new RegExp(`^${key}:\\s*(.*)$`, 'm').exec(match[1])?.[1].trim().replace(/^["']|["']$/g, '') ?? '';
    return { name: field('name'), description: field('description'), always: field('always') === 'true' };
}

// ── memories ───────────────────────────────────────────────────────────────

export interface MemoryLink {
    id: string;
    name: string;
    writes: boolean;
}

export interface MemoryItem {
    kind: 'memory';
    id: string;
    /** Null for an agent's own memory. */
    name: string | null;
    description: string;
    /** The agent whose own memory this is. */
    agentId: string | null;
    attachedTo: MemoryLink[];
    /** Unknown (null) for an agent's own memory until it's read. */
    entryCount: number | null;
    userId: string | null;
    createdAt: string | null;
    updatedAt: string | null;
}

export function toMemory(raw: Wire): MemoryItem {
    return {
        kind: 'memory',
        id: text(raw.id),
        name: maybe(raw.name),
        description: text(raw.description),
        agentId: maybe(raw.agent_id),
        attachedTo: list(raw.attached_to).map((a) => ({ id: text(a.id), name: text(a.name), writes: a.writes === true })),
        entryCount: count(raw.entry_count),
        userId: maybe(raw.user_id),
        createdAt: maybe(raw.created_at),
        updatedAt: maybe(raw.updated_at),
    };
}

export interface MemoryEntry {
    name: string;
    description: string;
    content: string | null;
    version: number;
    updatedAt: string | null;
    writtenBy: Writer | null;
}

/** The account's named memories (an agent's own is listed with its agent's, `agentMemories`). */
export async function listMemories(client: NoClick): Promise<MemoryItem[]> {
    return (await Memory.list({ client, limit: LIMIT })).map((m) => toMemory(m.raw));
}

/** One agent's memories: its own first, then the ones it attaches, in order. */
export async function agentMemories(client: NoClick, agentId: string): Promise<MemoryItem[]> {
    const page = await client.request<{ data: Wire[] }>('GET', '/v1/memories', { query: { agent_id: agentId, limit: LIMIT } });
    return list(page.data).map(toMemory);
}

export async function getMemory(client: NoClick, id: string): Promise<MemoryItem> {
    return toMemory(await client.request<Wire>('GET', `/v1/memories/${id}`));
}

export async function memoryEntries(client: NoClick, id: string): Promise<MemoryEntry[]> {
    const rows = await client.request<Wire[] | { data: Wire[] }>('GET', `/v1/memories/${id}/entries`);
    const raw = Array.isArray(rows) ? rows : list(rows.data);
    return raw.map((row) => {
        const entry = toMemoryEntry(row as Parameters<typeof toMemoryEntry>[0]);
        return { name: entry.name, description: entry.description, content: entry.content, version: entry.version, updatedAt: entry.updatedAt?.toISOString() ?? null, writtenBy: writer(row.written_by) };
    });
}

/** One entry in full, its content with it (a list leaves content out). */
export async function readEntry(client: NoClick, id: string, name: string): Promise<MemoryEntry> {
    const row = await client.request<Wire>('GET', `/v1/memories/${id}/entries/${encodeURIComponent(name)}`);
    const entry = toMemoryEntry(row as Parameters<typeof toMemoryEntry>[0]);
    return { name: entry.name, description: entry.description, content: entry.content, version: entry.version, updatedAt: entry.updatedAt?.toISOString() ?? null, writtenBy: writer(row.written_by) };
}

/** Writes an entry over the version read (0 or none: a new one). */
export async function saveEntry(client: NoClick, id: string, name: string, content: string, options: { description?: string; version?: number }): Promise<void> {
    await Memory.fromId(id, { client }).save(name, content, options);
}

export async function forgetEntry(client: NoClick, id: string, name: string, version?: number): Promise<void> {
    await Memory.fromId(id, { client }).forget(name, { version });
}

export async function createMemory(client: NoClick, name: string, description: string): Promise<MemoryItem> {
    const memory = await Memory.create(name, { client, description });
    return getMemory(client, memory.id);
}

// ── either ─────────────────────────────────────────────────────────────────

export type Knowledge = Skill | MemoryItem;
export type KnowledgeKind = Knowledge['kind'];

const route = (kind: KnowledgeKind, id: string) => `/v1/${kind === 'skill' ? 'skills' : 'memories'}/${id}`;

export async function renameKnowledge(client: NoClick, item: Knowledge, name: string): Promise<void> {
    await (item.kind === 'skill' ? SdkSkill.fromId(item.id, { client }) : Memory.fromId(item.id, { client })).update({ name });
}

/** To the trash, detached from every agent; the TrashItem's restore puts both back. */
export async function trashKnowledge(client: NoClick, item: Knowledge): Promise<TrashItem> {
    return item.kind === 'skill' ? SdkSkill.fromId(item.id, { client }).delete() : Memory.fromId(item.id, { client }).delete();
}

/** What deleting it does, as the platform previews it: the agents it's detached from. */
export async function previewTrash(client: NoClick, item: Knowledge): Promise<{ deletes: string; dependsOnIt: string[] }> {
    const { impact } = await client.request<{ impact: Wire }>('POST', '/v1/delete_previews', { json: { method: 'DELETE', path: route(item.kind, item.id) } });
    return { deletes: text(impact.deletes), dependsOnIt: list(impact.depends_on_it).map(String) };
}

// ── the account's agents, and their links ──────────────────────────────────

export type Harness = 'sdk' | 'claude_code' | 'codex' | 'opencode' | 'hermes' | 'openclaw';

export interface AgentRef {
    id: string;
    name: string;
    harness: Harness;
    model: string | null;
    userId: string | null;
    /** Its own memory. */
    memoryId: string | null;
    skills: { id: string; pin: number | null }[];
    memories: { id: string; writes: boolean }[];
}

/** An agent as its links are written: from the SDK's agent, its skills read from the API's own field. */
export function agentRef(agent: Agent): AgentRef {
    return {
        id: agent.id,
        name: agent.name,
        harness: (agent.harness ?? 'sdk') as Harness,
        model: agent.model,
        userId: agent.userId,
        memoryId: agent.memoryId,
        skills: agent.skills ?? [],
        memories: agent.memories ?? [],
    };
}

/** Sets an agent's skills or memories to `links`, in order (acting for its user, where it's a user's). */
export async function setAgentLinks(client: NoClick, agent: AgentRef, change: { skills?: AgentRef['skills']; memories?: AgentRef['memories'] }): Promise<void> {
    await client.request('PATCH', `/v1/agents/${agent.id}`, { json: change, user: agent.userId ?? undefined });
}

/** The most memories an agent reads besides its own. */
export const MAX_MEMORIES = 10;

// ── machines ───────────────────────────────────────────────────────────────

export interface ComputeRun {
    agentId: string;
    agentName: string;
    harness: Harness | null;
    state: string;
}

export interface Compute {
    /** A NoClick machine, an agent's warm sandbox up now, or a developer sandbox that's live. */
    kind: 'machine' | 'agent_sandbox' | 'sandbox';
    id: string;
    name: string;
    status: string;
    userId: string | null;
    region: string | null;
    cpu: number | null;
    memoryGb: number | null;
    startedAt: string | null;
    usdPerHour: number | null;
    usdPerMonth: number | null;
    spentUsdToday: number | null;
    running: ComputeRun[];
}

export function toCompute(raw: Wire): Compute {
    return {
        kind: (text(raw.kind) || 'machine') as Compute['kind'],
        id: text(raw.id),
        name: text(raw.name),
        status: text(raw.status),
        userId: maybe(raw.user_id),
        region: maybe(raw.region),
        cpu: count(raw.cpu),
        memoryGb: count(raw.memory_gb),
        startedAt: maybe(raw.started_at),
        usdPerHour: count(raw.usd_per_hour),
        usdPerMonth: count(raw.usd_per_month),
        spentUsdToday: count(raw.spent_usd_today),
        running: list(raw.running).map((r) => ({
            agentId: text(r.agent_id),
            agentName: text(r.agent_name),
            harness: (maybe(r.harness) as Harness | null) ?? null,
            state: text(r.state),
        })),
    };
}

/** Where the account's agents and code run now, its users' included. */
export async function listCompute(client: NoClick): Promise<{ data: Compute[] }> {
    return { data: (await compute({ client, userFilter: ALL_USERS })).map((c) => toCompute(c.raw)) };
}

/** Up now: a machine running, or any sandbox listed (only live ones are). */
export const isUp = (c: Compute) => c.kind !== 'machine' || c.status === 'running';

/** A computer of the person's that runs NoClick's machine daemon (`/v1/machines?kind=own`). */
export interface OwnComputer {
    kind: 'own';
    id: string;
    name: string;
    /** provisioning (waiting to be paired), running (online) or offline. */
    status: string;
    os: string | null;
    hostname: string | null;
    lastSeenAt: string | null;
    /** Its CPUs and memory, as the box reported them (on a Mac, NoClick's VM's); its agents get `agentShare`. */
    cpu: number | null;
    memoryGb: number | null;
    conversationsAtOnce: number | null;
    /** The part of it its agents use, the rest staying yours (on a Mac, the part NoClick's VM is made with). */
    agentShare: number | null;
    /** On a Mac once NoClick's VM is made: a VM keeps its size, so the share does too. */
    agentShareFixed: boolean;
    /** Whether its agents run apps and test databases there: by themselves, asking first, or never. */
    appTesting: AppTesting;
    /** While it isn't registered yet: its pairing, the box installing it (on a Mac, its VM once sized), and the box
     *  last turned away with its code. */
    pairing: {
        code: string | null;
        command: string | null;
        commands: PairingCommands | null;
        expiresAt: string | null;
        installingOn: string | null;
        vm: { cpus: number; memoryGb: number } | null;
        refused: PairingRefusal | null;
    } | null;
    /** False while agents don't run on machines on this deployment. */
    agentsEnabled: boolean | null;
    createdAt: string | null;
}

/** A box the installer turned away with the code, in the installer's own words (the terminal printed the same). */
export interface PairingRefusal {
    hostname: string | null;
    system: string | null;
    arch: string | null;
    message: string;
    /** What to do, where NoClick knows it; the installer's own refusals say it in `message`. */
    nextStep: string | null;
    at: string | null;
}

function toRefusal(raw: unknown): PairingRefusal | null {
    const r = obj(raw);
    return r ? { hostname: maybe(r.hostname), system: maybe(r.system), arch: maybe(r.arch), message: text(r.message), nextStep: maybe(r.next_step), at: maybe(r.at) } : null;
}

/** The command's forms as a code is made: Linux's (Windows runs it in WSL) and a Mac's, without sudo, and each again
 *  with `--yes` for running it unattended (over SSH, from cloud-init or a script), where the API gives them. */
export interface PairingCommands {
    linux: string;
    mac: string;
    unattended: { linux: string; mac: string } | null;
}

function toCommands(raw: unknown): PairingCommands | null {
    const c = obj(raw);
    if (!c || !maybe(c.linux) || !maybe(c.mac)) return null;
    const unattended = maybe(c.linux_unattended) && maybe(c.mac_unattended) ? { linux: text(c.linux_unattended), mac: text(c.mac_unattended) } : null;
    return { linux: text(c.linux), mac: text(c.mac), unattended };
}

function toVm(raw: unknown): { cpus: number; memoryGb: number } | null {
    const v = obj(raw);
    const cpus = count(v?.cpus);
    const memoryGb = count(v?.memory_gb);
    return cpus !== null && memoryGb !== null ? { cpus, memoryGb } : null;
}

export function toOwnComputer(raw: Wire): OwnComputer {
    const pairing = obj(raw.pairing);
    return {
        kind: 'own',
        id: text(raw.id),
        name: text(raw.name) || text(raw.hostname),
        status: text(raw.status),
        os: maybe(raw.os),
        hostname: maybe(raw.hostname),
        lastSeenAt: maybe(raw.last_seen_at),
        cpu: count(raw.cpu),
        memoryGb: count(raw.memory_gb),
        conversationsAtOnce: count(raw.conversations_at_once),
        agentShare: count(raw.agent_share),
        agentShareFixed: raw.agent_share_fixed === true,
        appTesting: (maybe(raw.app_testing) as AppTesting | null) ?? 'never',
        pairing: pairing
            ? {
                  code: maybe(pairing.code),
                  command: maybe(pairing.command),
                  commands: toCommands(pairing.commands),
                  expiresAt: maybe(pairing.expires_at),
                  installingOn: maybe(pairing.installing_on),
                  vm: toVm(pairing.vm),
                  refused: toRefusal(pairing.refused),
              }
            : null,
        agentsEnabled: typeof raw.agents_enabled === 'boolean' ? raw.agents_enabled : null,
        createdAt: maybe(raw.created_at),
    };
}

export async function listOwnComputers(client: NoClick): Promise<OwnComputer[]> {
    return (await Machine.list({ client, kind: 'own', limit: LIMIT })).map((m) => toOwnComputer(m.raw));
}

/** Whether agents run on machines on this deployment yet; until they do, adding a computer of yours is refused. */
export async function agentsOnMachines(client: NoClick): Promise<boolean> {
    return Machine.agentsEnabledHere({ client });
}

/** Adds a computer of yours, with whether its agents may run apps there: answers its one-time pairing command. */
export async function addOwnComputer(client: NoClick, options: { name?: string; appTesting?: AppTesting } = {}): Promise<OwnComputer> {
    return toOwnComputer((await Machine.addOwn({ client, ...options })).raw);
}

/** One computer of yours as it stands now (a read never carries its code or command). */
export async function getOwnComputer(client: NoClick, id: string): Promise<OwnComputer> {
    return toOwnComputer((await Machine.get(id, { client })).raw);
}

/** What part of a computer of yours its agents use, the rest staying yours; refused where it leaves too little. */
export async function setComputerShare(client: NoClick, id: string, share: number): Promise<OwnComputer> {
    return toOwnComputer((await Machine.fromId(id, { client }).update({ agentShare: share })).raw);
}

/** Whether a computer of yours lets its agents run apps and test databases: by themselves, asking first, or never. */
export async function setComputerAppTesting(client: NoClick, id: string, appTesting: AppTesting): Promise<OwnComputer> {
    return toOwnComputer((await Machine.fromId(id, { client }).update({ appTesting })).raw);
}

/** A fresh pairing command, for a computer not paired yet. */
export async function newPairing(client: NoClick, id: string): Promise<OwnComputer> {
    return toOwnComputer((await Machine.fromId(id, { client }).newPairingCode()).raw);
}

export async function removeMachine(client: NoClick, id: string): Promise<void> {
    await Machine.fromId(id, { client }).delete();
}
