// A machine as its own page reads it (`GET /v1/machines/{id}`): what it costs this month, who's working on it, how
// long it's been up, its last check-in's processors, memory and disk, and the size it's becoming. The judgements the
// page shows are made here, once: what each state means for its agents, the verdict on its health with the fix, and
// its prices a month and a day (machines are monthly, never hourly).
import type {
    AppTesting,
    JsonObject,
    MachineHostName,
    MachineSizeName,
} from 'noclick';
import { REGION_NAMES } from '@/lib/regionNames';

type Wire = Record<string, unknown>;
const text = (v: unknown) => (typeof v === 'string' ? v : '');
const maybe = (v: unknown) => (typeof v === 'string' && v ? v : null);
const num = (v: unknown) =>
    typeof v === 'number' && Number.isFinite(v) ? v : null;
const obj = (v: unknown) =>
    v && typeof v === 'object' && !Array.isArray(v) ? (v as Wire) : null;
const list = (v: unknown) => (Array.isArray(v) ? (v as Wire[]) : []);

export const SIZE_LABELS: Record<MachineSizeName, string> = {
    small: 'Small',
    medium: 'Medium',
    large: 'Large',
    xlarge: 'XLarge',
};
/** A month, as machines are priced: a thirtieth of it is charged each day. */
export const DAYS_PER_MONTH = 30;

const APP_TESTING: readonly AppTesting[] = ['by_itself', 'ask_first', 'never'];

export interface MachineHealth {
    cpus: number | null;
    load1m: number;
    cpuPercent: number;
    memoryUsedGb: number;
    memoryTotalGb: number;
    diskUsedGb: number;
    diskTotalGb: number;
}

export interface MachinePortView {
    port: number;
    url: string;
    public: boolean;
}

export interface MachineView {
    id: string;
    name: string;
    kind: 'noclick' | 'own';
    status: string;
    statusReason: string | null;
    size: MachineSizeName | null;
    region: string | null;
    host: MachineHostName | null;
    cpu: number | null;
    memoryGb: number | null;
    diskGb: number | null;
    os: string | null;
    hostname: string | null;
    monthlyUsd: number | null;
    maxMonthlyUsd: number | null;
    conversationsAtOnce: number | null;
    agentShare: number | null;
    agentShareFixed: boolean;
    lastSeenAt: string | null;
    /** When it last booted, while it runs. */
    startedAt: string | null;
    spentUsdThisMonth: number;
    workingCount: number;
    agentStates: { agentId: string; working: boolean }[];
    health: MachineHealth | null;
    /** The size it's becoming while `updating`, and whether that moves it to a fresh machine. */
    pending: { size: MachineSizeName; move: boolean } | null;
    ports: MachinePortView[];
    userId: string | null;
    /** Your own machine's say on apps and test databases; null where the API doesn't carry it. */
    appTesting: AppTesting | null;
}

function toHealth(raw: unknown): MachineHealth | null {
    const h = obj(raw);
    if (!h) return null;
    const total = num(h.memory_total_gb);
    const disk = num(h.disk_total_gb);
    if (total === null || disk === null) return null;
    return {
        cpus: num(h.cpus),
        load1m: num(h.load_1m) ?? 0,
        cpuPercent: num(h.cpu_percent) ?? 0,
        memoryUsedGb: num(h.memory_used_gb) ?? 0,
        memoryTotalGb: total,
        diskUsedGb: num(h.disk_used_gb) ?? 0,
        diskTotalGb: disk,
    };
}

export function toMachineView(raw: JsonObject | Wire): MachineView {
    const pending = obj(raw.pending);
    const testing = maybe(raw.app_testing);
    return {
        id: text(raw.id),
        name: text(raw.name) || text(raw.hostname),
        kind: raw.kind === 'own' ? 'own' : 'noclick',
        status: text(raw.status),
        statusReason: maybe(raw.status_reason),
        size: (maybe(raw.size) as MachineSizeName | null) ?? null,
        region: maybe(raw.region),
        host: (maybe(raw.host) as MachineHostName | null) ?? null,
        cpu: num(raw.cpu),
        memoryGb: num(raw.memory_gb),
        diskGb: num(raw.disk_gb),
        os: maybe(raw.os),
        hostname: maybe(raw.hostname),
        monthlyUsd: num(raw.monthly_usd),
        maxMonthlyUsd: num(raw.max_monthly_usd),
        conversationsAtOnce: num(raw.conversations_at_once),
        agentShare: num(raw.agent_share),
        agentShareFixed: raw.agent_share_fixed === true,
        lastSeenAt: maybe(raw.last_seen_at),
        startedAt: maybe(raw.started_at),
        spentUsdThisMonth: num(raw.spent_usd_this_month) ?? 0,
        workingCount: num(raw.working_count) ?? 0,
        agentStates: list(raw.agent_states).map((s) => ({
            agentId: text(s.agent_id),
            working: s.working === true,
        })),
        health: toHealth(raw.health),
        pending:
            pending && maybe(pending.size)
                ? {
                      size: text(pending.size) as MachineSizeName,
                      move: pending.move === true,
                  }
                : null,
        ports: list(raw.ports).map((p) => ({
            port: num(p.port) ?? 0,
            url: text(p.url),
            public: p.public === true,
        })),
        userId: maybe(raw.user_id),
        appTesting: APP_TESTING.includes(testing as AppTesting)
            ? (testing as AppTesting)
            : null,
    };
}

const usd = (n: number) => `$${n.toFixed(2)}`;

/** A day of a monthly price: what each day it's kept is charged. */
export const dayPrice = (monthly: number) =>
    Math.round((monthly / DAYS_PER_MONTH) * 100) / 100;
export const perMonth = (monthly: number) => `${usd(monthly)} a month`;
export const perDay = (monthly: number) => `${usd(dayPrice(monthly))} a day`;

/** The price, said once before anything is charged. */
export const priceLine = (monthly: number) =>
    `That’s ${usd(dayPrice(monthly))} a day, from the day it starts until you delete it. Stopping it doesn’t stop the charge.`;

/** A region as a place: "US East", never `us-east`. */
export const placeName = (region: string | null) =>
    region ? (REGION_NAMES[region] ?? region) : null;

/** Your own computer, as people call it: their Mac (NoClick's VM on it), their PC (Ubuntu in WSL), or their computer. */
export function ownDevice(os: string | null): {
    what: 'Mac' | 'PC' | 'computer';
    system: string | null;
} {
    const mac = os ? /\(VM on (macOS[^)]*)\)/.exec(os) : null;
    if (mac)
        return {
            what: 'Mac',
            system: mac[1].replace(/^macOS (\d+)(\.\d+)*$/, 'macOS $1'),
        };
    if (os?.includes('(WSL on Windows)'))
        return { what: 'PC', system: 'Windows' };
    return { what: 'computer', system: os };
}

/** "NoClick machine · Small · US East", or "Your Mac · macOS 15". */
export function kindLine(m: MachineView): string {
    if (m.kind === 'own') {
        const d = ownDevice(m.os);
        return [`Your ${d.what}`, d.system].filter(Boolean).join(' · ');
    }
    return [
        'NoClick machine',
        m.size ? SIZE_LABELS[m.size] : null,
        placeName(m.region),
    ]
        .filter(Boolean)
        .join(' · ');
}

/** How many agents work on it at once: its size's, or what fits in your own (null until it says). */
export const slotsOf = (m: MachineView) => m.conversationsAtOnce;

export const isUp = (m: MachineView) => m.status === 'running';
/** Agents keep working while it runs, and through a resize until their turns end. */
export const canWork = (m: MachineView) =>
    m.status === 'running' || m.status === 'updating';

/** Its agents' ids, working first. */
export const workingIds = (m: MachineView) =>
    canWork(m)
        ? m.agentStates.filter((a) => a.working).map((a) => a.agentId)
        : [];

export type Tone = 'ok' | 'busy' | 'off' | 'bad';
export interface StateInfo {
    tone: Tone;
    label: string;
    /** What it means for its agents, in a sentence. */
    meaning: string;
    /** Its one action, where it has one. */
    action?: 'start' | 'restart';
}

/** What a state means for the machine's agents; `company` names whose approval a held machine waits for. */
export function stateInfo(m: MachineView, company?: string | null): StateInfo {
    const own = m.kind === 'own';
    switch (m.status) {
        case 'running':
            return own
                ? {
                      tone: 'ok',
                      label: 'Online',
                      meaning: 'Agents can work on it while it’s on.',
                  }
                : {
                      tone: 'ok',
                      label: 'Running',
                      meaning: 'Agents can work on it now.',
                  };
        case 'stopped':
            return m.statusReason === 'unpaid'
                ? {
                      tone: 'off',
                      label: 'Stopped',
                      meaning:
                          'Its account’s balance couldn’t pay for it. Add funds, then start it; what it owes is charged first.',
                      action: 'start',
                  }
                : {
                      tone: 'off',
                      label: 'Stopped',
                      meaning: `Agents can’t work on it until it starts again. It’s still charged ${m.monthlyUsd !== null ? perDay(m.monthlyUsd) : 'each day'}.`,
                      action: 'start',
                  };
        case 'provisioning':
            return own
                ? {
                      tone: 'off',
                      label: 'Waiting to connect',
                      meaning: 'Its install command hasn’t run on it yet.',
                  }
                : {
                      tone: 'busy',
                      label: 'Starting',
                      meaning:
                          'Ready in about 3 minutes. Agents wait until then.',
                  };
        case 'updating': {
            const to = m.pending ? SIZE_LABELS[m.pending.size] : 'its new size';
            return m.pending?.move
                ? {
                      tone: 'busy',
                      label: 'Resizing',
                      meaning: `Moving to a fresh ${to} machine, with its files copied over. Back in a few minutes.`,
                  }
                : {
                      tone: 'busy',
                      label: 'Resizing',
                      meaning: `Becomes ${to} once the turns on it now end. Agents carry on until then.`,
                  };
        }
        case 'restarting':
            return {
                tone: 'busy',
                label: 'Restarting',
                meaning:
                    'Back in about a minute. What agents were doing stopped; they pick up with their next message.',
            };
        case 'offline':
            return {
                tone: 'off',
                label: 'Offline',
                meaning:
                    'It hasn’t checked in lately, so agents wait until it’s on and online again.',
            };
        case 'failed':
            return {
                tone: 'bad',
                label: 'Failed',
                meaning: m.statusReason
                    ? `It didn’t come up: ${m.statusReason}`
                    : 'It didn’t come up. Restart it to try again.',
                action: own ? undefined : 'restart',
            };
        case 'awaiting_approval':
            return {
                tone: 'off',
                label: 'Waiting for approval',
                meaning: `It starts the moment NoClick approves ${company || 'your company'}. Nothing is charged until then.`,
            };
        default:
            return {
                tone: 'off',
                label: m.status
                    ? m.status.charAt(0).toUpperCase() + m.status.slice(1)
                    : 'Unknown',
                meaning: '',
            };
    }
}

/** "4m", "3 hours", "12 days": how long since `from`. */
export function sinceText(from: string, now: number): string {
    const m = Math.max(0, Math.floor((now - Date.parse(from)) / 60_000));
    if (m < 2) return 'just now';
    if (m < 60) return `${m} minutes`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} ${h === 1 ? 'hour' : 'hours'}`;
    const d = Math.floor(h / 24);
    return `${d} ${d === 1 ? 'day' : 'days'}`;
}

/** "Up 12 days", "Up just now". */
export const upLine = (m: MachineView, now: number) =>
    m.startedAt
        ? sinceText(m.startedAt, now) === 'just now'
            ? 'Up just now'
            : `Up ${sinceText(m.startedAt, now)}`
        : 'Up';

/** What agents may use of its memory: all of a NoClick machine's, your own's share. */
export function memoryForAgents(m: MachineView, h: MachineHealth): number {
    return m.kind === 'own' && m.agentShare
        ? h.memoryTotalGb * m.agentShare
        : h.memoryTotalGb;
}

export interface Verdict {
    tone: Tone;
    text: string;
    /** The fix, where there is one: a size up, a look at the disk, or fewer agents at once on your own. */
    fix?: { action: 'resize' | 'files' | 'settings'; label: string };
}

/** NoClick's reading of the numbers, as one sentence and its fix. */
export function verdictOf(m: MachineView, now: number): Verdict {
    if (m.status === 'offline')
        return {
            tone: 'off',
            text: m.lastSeenAt
                ? `Last checked in ${sinceText(m.lastSeenAt, now)} ago. Nothing new until it’s back.`
                : 'Nothing new until it’s back.',
        };
    if (m.status === 'provisioning' && m.kind === 'own')
        return { tone: 'off', text: 'Nothing yet: it hasn’t connected.' };
    if (!canWork(m))
        return { tone: 'off', text: 'Nothing to read while it isn’t running.' };
    const h = m.health;
    if (!h) return { tone: 'off', text: 'It hasn’t said how busy it is yet.' };
    const mem = h.memoryUsedGb / Math.max(memoryForAgents(m, h), 0.001);
    const disk = h.diskUsedGb / Math.max(h.diskTotalGb, 0.001);
    if (mem > 0.88 || h.cpuPercent > 90) {
        const what =
            mem > 0.88
                ? 'memory is nearly full'
                : 'its processors are flat out';
        return {
            tone: 'bad',
            text: `Working hard: ${what}, so agents may slow down.`,
            fix:
                m.kind === 'own'
                    ? {
                          action: 'settings',
                          label: 'Fewer agents at once would help',
                      }
                    : { action: 'resize', label: 'A bigger size would help' },
        };
    }
    if (disk > 0.85)
        return {
            tone: 'bad',
            text: 'Its disk is nearly full.',
            fix:
                m.kind === 'own'
                    ? undefined
                    : { action: 'files', label: 'See what’s using it' },
        };
    return { tone: 'ok', text: 'Plenty of room. Agents aren’t waiting on it.' };
}

export interface Bar {
    label: string;
    word: string;
    numbers: string;
    ratio: number;
}

const gb = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

/** The three bars under Details: processors, memory and disk, each with a plain word and its numbers. */
export function barsOf(m: MachineView, h: MachineHealth): Bar[] {
    const word = (r: number, kind: 'cpu' | 'space') =>
        kind === 'cpu'
            ? r < 0.35
                ? 'Calm'
                : r < 0.75
                  ? 'Steady'
                  : 'Flat out'
            : r < 0.6
              ? 'Plenty free'
              : r < 0.85
                ? 'Getting full'
                : 'Nearly full';
    const memTotal = memoryForAgents(m, h);
    const cpu = Math.min(1, h.cpuPercent / 100);
    const mem = Math.min(1, h.memoryUsedGb / Math.max(memTotal, 0.001));
    const disk = Math.min(1, h.diskUsedGb / Math.max(h.diskTotalGb, 0.001));
    return [
        {
            label: 'Processors',
            word: word(cpu, 'cpu'),
            numbers: `${Math.round(h.cpuPercent)}% busy`,
            ratio: cpu,
        },
        {
            label: 'Memory',
            word: word(mem, 'space'),
            numbers: `${gb(Math.round(h.memoryUsedGb * 10) / 10)} of ${m.kind === 'own' ? `the ${gb(Math.round(memTotal * 10) / 10)} GB agents may use` : `${gb(memTotal)} GB`}`,
            ratio: mem,
        },
        {
            label: 'Disk',
            word: word(disk, 'space'),
            numbers: `${gb(Math.round(h.diskUsedGb))} of ${gb(Math.round(h.diskTotalGb))} GB used`,
            ratio: disk,
        },
    ];
}

/** What an agent's answer says beside it (`notes`): placed on a machine on its owner's plan, where the plan's sign-in
 * is kept. */
export const answerNotes = (answer: JsonObject): string[] =>
    Array.isArray(answer.notes) ? answer.notes.map(String) : [];

/** "Scout", "Scout and Ledger", "Scout, Ledger and Pixel". */
export function andList(names: string[]): string {
    return names.length <= 1
        ? names.join('')
        : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}
