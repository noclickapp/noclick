// Where each of an account's agents stands, as GET /v1/agents/states reads it (every harness: what it's running, what
// waits on a person, waking, failed), and the list's order, chips and search over it. The pure half of the Agents
// list; reads.ts reads it and keeps it current.
import { Agent, type AgentNow, type AgentState as AgentStateName, type AgentStateRow, type HarnessName, type NoClick } from 'noclick';
import { knownStepName, stepName } from '@/lib/stepLabels';

export type { AgentStateName };
/** One agent's state: the first of needs-you, working, with you, waking, failed that holds, else idle; where it is,
 *  the tool call it's running, and what waits on a person (`waiting.total`, the rail's badge). */
export type AgentState = AgentStateRow;

/** Every agent's state, or a space's agents'. */
export async function readAgentStates(client: NoClick, spaceId: string | null): Promise<AgentState[]> {
    return (await Agent.states({ client, workspace: spaceId ?? undefined })).data;
}

// ── the list's rows ─────────────────────────────────────────────────────────

/** The state drawn as a ring round the avatar. */
export type RingStatus = 'working' | 'needs' | 'waking' | 'failed' | 'idle';

/** What the list knows of an agent besides its state: its job, for the second line and the search. */
export interface AgentFacts {
    id: string;
    name: string;
    role: string | null;
    harness: HarnessName;
}

export interface Entry {
    id: string;
    name: string;
    harness: HarnessName;
    role: string;
    status: RingStatus;
    needs: number;
    /** What it's doing, with a running agent's time or an idle one's last time. */
    line: string;
    /** Milliseconds since it last did something; 0 while it works or wakes. */
    ago: number;
    startedAt: number;
}

const RING: Record<AgentStateName, RingStatus> = { needs_you: 'needs', working: 'working', with_you: 'idle', waking: 'waking', failed: 'failed', idle: 'idle' };
/** The ring a state draws round the avatar. */
export const ringOf = (state: AgentStateName): RingStatus => RING[state] ?? 'idle';

/** "38s", "11m", "2h", "3d": how long a turn has run. */
export function elapsed(ms: number): string {
    const s = Math.max(0, Math.round(ms / 1000));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

// A word a step may show as it is: no id, no JSON, no path.
const PLAIN = /^[A-Za-z][\w.+-]{0,39}$/;
const ID_LIKE = /[0-9a-f]{8}-[0-9a-f]{4}|[{}[\]"]/i;
const CODE: Partial<Record<AgentNow['kind'], string>> = { command: 'Running', edit: 'Editing', read: 'Reading', search: 'Searching' };

/** A tool as the step line names it, by its wire name if it has one Work knows: a coding harness's raw name
 *  (`mcp__noclick__api_call`), or NoClick's own words for it ("noclick api call", whose `__` and `_` became spaces). */
function toolStep(tool: string, detail: string | undefined): string {
    const args = detail && /^[a-z0-9_]+$/.test(detail) ? { operation: detail } : undefined;
    const words = tool.trim().split(/\s+/);
    const names = [tool, words.join('_'), ...words.slice(1).map((_, i) => `${words.slice(0, i + 1).join('_')}__${words.slice(i + 1).join('_')}`)];
    for (const name of names) {
        const known = knownStepName(name, args, 'running');
        if (known) return known.label;
    }
    return stepName(tool.replace(/([a-z])([A-Z])/g, '$1 $2'), undefined, 'running').label;
}

/** What an agent is doing now in plain words, as Work says a step: NoClick's or an app's call by what it does
 *  ("Asking agent", "Sending a message in WhatsApp"), a command by its program ("Running pytest"), a file by its name;
 *  never an id or JSON. Null when it isn't running a step. */
export function nowWords(now: AgentNow | null | undefined): string | null {
    if (!now) return null;
    // A coding harness's step, as the platform said it ("Running the plan usage tests"), while it runs; once it ended
    // and the turn goes on, it's just working.
    if (now.label) return now.running ? now.label : null;
    const verb = CODE[now.kind];
    if (verb) {
        const [, rest = ''] = /^(?:bash:|edit|read|search)\s*(.*)$/.exec(now.line) ?? [];
        if (now.kind === 'command') {
            // The program the command runs last ("cd app && npm test" runs npm test), and what it's asked to do.
            const [program, sub] = (rest.split(/&&|;|\|/).pop() ?? '').trim().split(/\s+/);
            const name = program?.split('/').pop() ?? '';
            if (!PLAIN.test(name)) return 'Running a command';
            return `${verb} ${sub && /^[a-z][\w-]*$/.test(sub) ? `${name} ${sub}` : name}`;
        }
        if (now.kind === 'search') return rest && !ID_LIKE.test(rest) && rest.length <= 40 ? `${verb} “${rest}”` : verb;
        const file = rest.split('/').pop() ?? '';
        return `${verb} ${PLAIN.test(file) && !ID_LIKE.test(file) ? file : 'a file'}`;
    }
    const [tool, detail] = now.line.split(/:\s*/, 2);
    const words = toolStep(now.kind === 'tool' && now.tool ? now.tool : tool, detail);
    return ID_LIKE.test(words) ? 'Working' : words;
}

/** "4m ago", "yesterday", "3 days ago", "last week", "a month ago". */
export function agoText(ms: number): string {
    const m = Math.max(0, Math.floor(ms / 60_000));
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    if (d < 7) return d === 1 ? 'yesterday' : `${d} days ago`;
    const w = Math.floor(d / 7);
    if (d < 30) return w === 1 ? 'last week' : `${w} weeks ago`;
    const mo = Math.max(1, Math.floor(d / 30));
    return mo === 1 ? 'a month ago' : `${mo} months ago`;
}

/** Its row: the ring, what waits on you, and its line (the running tool call, else its job). */
export function entryOf(state: AgentState, facts: AgentFacts | undefined, now: number): Entry {
    const role = facts?.role ?? '';
    const started = state.turnStartedAt?.getTime() ?? state.now?.since?.getTime() ?? now;
    const last = state.lastActiveAt?.getTime() ?? null;
    let line: string;
    if (state.state === 'needs_you') line = state.waiting.total > 1 ? `${state.waiting.total} things wait on you` : 'Waiting on you';
    else if (state.state === 'working') line = `${nowWords(state.now) || 'Working'} · ${elapsed(now - started)}`;
    else if (state.state === 'waking') line = state.waking?.why || 'Waking';
    else if (state.state === 'failed') line = `Failed: ${state.failed?.message ?? 'its last turn didn’t finish'}`;
    else if (state.state === 'with_you') line = 'With you';
    else line = [role || 'Idle', last ? agoText(now - last) : null].filter(Boolean).join(' · ');
    const going = state.state === 'working' || state.state === 'waking';
    return {
        id: state.agentId,
        name: facts?.name ?? state.name,
        harness: facts?.harness ?? state.harness,
        role,
        status: ringOf(state.state),
        needs: state.waiting.total,
        line,
        ago: going ? 0 : last === null ? Number.MAX_SAFE_INTEGER : now - last,
        startedAt: started,
    };
}

const RANK: Record<RingStatus, number> = { needs: 0, failed: 1, working: 2, waking: 3, idle: 4 };

/** Needs you, then failed, then working (longest first, so one that starts joins the end) and waking, then by when it
 *  last did something. */
export const byAttention = (x: Entry, y: Entry) =>
    RANK[x.status] - RANK[y.status] || x.ago - y.ago || (x.status === 'working' ? x.startedAt - y.startedAt : 0) || x.name.localeCompare(y.name);

// ── search ──────────────────────────────────────────────────────────────────

export const termsOf = (query: string) => query.trim().toLowerCase().split(/\s+/).filter(Boolean);
export type Field = 'name' | 'line' | 'job' | 'harness';

/** Where a search found an agent: its name, what it's doing, its job or its harness; null when it didn't. */
export function foundIn(e: Entry, terms: string[], harnessLabel: string): { score: number; field: Field } | null {
    const fields = { name: e.name.toLowerCase(), line: e.line.toLowerCase(), job: e.role.toLowerCase(), harness: harnessLabel.toLowerCase() };
    if (!terms.every((t) => Object.values(fields).some((f) => f.includes(t)))) return null;
    if (fields.name.startsWith(terms[0])) return { score: 0, field: 'name' };
    if (terms.some((t) => fields.name.split(/\s+/).some((w) => w.startsWith(t)))) return { score: 1, field: 'name' };
    if (terms.some((t) => fields.name.includes(t))) return { score: 2, field: 'name' };
    if (terms.some((t) => fields.line.includes(t))) return { score: 3, field: 'line' };
    if (terms.some((t) => fields.job.includes(t))) return { score: 4, field: 'job' };
    return { score: 5, field: 'harness' };
}

/** Each place a term falls in the text, merged: the ranges a row bolds. */
export function matchRanges(text: string, terms: string[]): [number, number][] {
    const lower = text.toLowerCase();
    const ranges: [number, number][] = [];
    for (const t of terms) for (let i = lower.indexOf(t); i >= 0; i = lower.indexOf(t, i + 1)) ranges.push([i, i + t.length]);
    ranges.sort((a, b) => a[0] - b[0]);
    const merged: [number, number][] = [];
    for (const r of ranges) {
        const last = merged.at(-1);
        if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
        else merged.push([...r]);
    }
    return merged;
}

// ── the chips ───────────────────────────────────────────────────────────────

export type Chip = 'all' | 'running' | 'needs' | 'failed';
export const CHIPS: { id: Chip; label: string; holds: (e: Entry) => boolean; empty: string; noun: string }[] = [
    { id: 'all', label: 'All', holds: () => true, empty: '', noun: 'agent' },
    { id: 'running', label: 'Running', holds: (e) => e.status === 'working' || e.status === 'waking', empty: 'No agents running right now', noun: 'running agent' },
    { id: 'needs', label: 'Needs you', holds: (e) => e.needs > 0, empty: 'Nothing needs you', noun: 'agent waiting on you' },
    { id: 'failed', label: 'Failed', holds: (e) => e.status === 'failed', empty: 'Nothing has failed', noun: 'failed agent' },
];
/** Chips show once the list outgrows a glance; up to this many agents it's one sorted list. */
export const CHIPS_ABOVE = 6;

/** What each chip counts: Needs you the asks and held calls (as the rail's badge), the others agents. */
export function chipCounts(entries: readonly Entry[]): Record<Chip, number> {
    return {
        all: entries.length,
        running: entries.filter(CHIPS[1].holds).length,
        needs: entries.reduce((n, e) => n + e.needs, 0),
        failed: entries.filter(CHIPS[3].holds).length,
    };
}
