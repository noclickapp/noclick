// What the usage page shows, derived from what `usage:page` sends (types.ts): the period's spend and who paid it,
// each day, where it went (by service and by thing, and inside each), the projection with its range, how long the
// money lasts where the deployment bills, and what's coming. Pure functions over the groups; the charges themselves
// come a page at a time.
import { formatUsage, usdToCredits } from '~/lib/money';
import { getDisplayName } from '~/lib/usage';
import usageNames from '~/lib/usage/usageNames.json';
import type { ChargeRow, ChargesQuery, UsageGroup, UsagePageData, UsageRow, UsageSnapshot } from './types';

export const DAY_MS = 86_400_000;

// ── money ────────────────────────────────────────────────────────────────────

/** A metered amount in dollars, precise enough that a real charge never rounds away (lib/money's rule). */
export function money(usd: number): string {
    if (usd < 0) return `−${formatUsage(usdToCredits(-usd))}`;
    return formatUsage(usdToCredits(usd));
}

/** A whole-dollar figure for axes and estimates: "$246", "$1.2K". */
export function roundMoney(usd: number): string {
    const sign = usd < 0 ? '−' : '';
    const v = Math.abs(usd);
    if (v >= 10_000) return `${sign}$${(v / 1000).toFixed(v >= 100_000 ? 0 : 1)}K`;
    if (v >= 100) return `${sign}$${Math.round(v).toLocaleString('en-US')}`;
    if (v >= 10) return `${sign}$${v.toFixed(0)}`;
    if (v === 0) return '$0';
    return `${sign}$${v < 1 ? v.toFixed(2) : v.toFixed(v % 1 === 0 ? 0 : 2)}`;
}

/** Split a figure into its dollars and cents for a hero: ["$127", ".40"]. */
export function heroParts(usd: number): [string, string] {
    const s = money(usd);
    const dot = s.lastIndexOf('.');
    return dot === -1 ? [s, ''] : [s.slice(0, dot), s.slice(dot)];
}

// ── dates (UTC: billing's windows and day buckets are UTC) ───────────────────

export const dayKey = (t: number | string) => new Date(t).toISOString().slice(0, 10);
const dayStart = (t: number) => Math.floor(t / DAY_MS) * DAY_MS;

// Intl formatters are costly to build, and a drill relabels every visible row.
const FORMATS = new Map<string, Intl.DateTimeFormat>();
function format(opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
    const key = JSON.stringify(opts);
    let f = FORMATS.get(key);
    if (!f) FORMATS.set(key, (f = new Intl.DateTimeFormat('en-US', { ...opts, timeZone: 'UTC' })));
    return f;
}

export function dayLabel(key: string, opts: { weekday?: boolean; year?: boolean } = {}): string {
    return format({
        month: 'short',
        day: 'numeric',
        weekday: opts.weekday ? 'short' : undefined,
        year: opts.year ? 'numeric' : undefined,
    }).format(Date.parse(`${key}T00:00:00Z`));
}

export function timeLabel(iso: string): string {
    return format({ hour: 'numeric', minute: '2-digit' }).format(Date.parse(iso));
}

/** "in 5 days", "tomorrow", "today". */
export function daysFrom(nowKey: string, key: string): string {
    const d = Math.round((Date.parse(`${key}T00:00:00Z`) - Date.parse(`${nowKey}T00:00:00Z`)) / DAY_MS);
    if (d === 0) return 'today';
    if (d === 1) return 'tomorrow';
    if (d < 0) return `${-d} days ago`;
    return `in ${d} days`;
}

/** "+1 415 555 0132" from "+14155550132"; anything else as it came. */
export function phoneLabel(number: string): string {
    const m = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(number);
    return m ? `+1 ${m[1]} ${m[2]} ${m[3]}` : number;
}

// ── services: where the money goes ───────────────────────────────────────────

export type ServiceId = 'ai' | 'sandboxes' | 'machines' | 'browsers' | 'calls' | 'numbers' | 'email' | 'apps' | 'databases' | 'storage' | 'domains' | 'tools';

/** What each service is called, beside every charge's name (lib/usage/usageNames.json: one table). The buckets are
 *  the platform API's `group_by=type`, with model calls, emails and stored files each joined into one. */
export const SERVICES: Record<ServiceId, { label: string; gloss: string }> = usageNames.services;

export function serviceOf(row: UsageRow): ServiceId {
    const t = row.usage_type;
    const s = row.usage_subtype;
    if (row.metadata.platform_api?.surface === 'ai' || t === 'ai_usage' || t === 'ai_builder' || t === 'ai_testing') return 'ai';
    if (t === 'cpu_usage' || t === 'gpu_usage') return 'sandboxes';
    if (t === 'recurring') return 'numbers';
    if (s.startsWith('email/')) return 'email';
    if (s.startsWith('voice/') || s.startsWith('phone/') || s.startsWith('whatsapp/')) return 'calls';
    if (s.startsWith('volume/') || s.startsWith('storage/')) return 'storage';
    if (s.startsWith('machine/')) return 'machines';
    if (s.startsWith('database/')) return 'databases';
    if (s.startsWith('browser/')) return 'browsers';
    if (s.startsWith('apps/')) return 'apps';
    if (s.startsWith('domain/')) return 'domains';
    return 'tools';
}

/** Charges that arrive on a date (a number's month, a domain's renewal) rather than with use: the projection adds
 *  them where they fall instead of folding them into the daily rate. */
export const isScheduled = (row: UsageRow) => row.usage_type === 'recurring' || row.usage_subtype.startsWith('domain/');

// ── things: which automation, agent, app, person or key ───────────────────────

export type Dimension = 'service' | 'automation' | 'agent' | 'app' | 'person' | 'key';

export const DIMENSION_LABEL: Record<Dimension, string> = {
    service: 'Service',
    automation: 'Automation',
    agent: 'Agent',
    app: 'Site',
    person: 'Person',
    key: 'API key',
};

/** No thing claims the charge (an account's own service). */
export const OUTSIDE = '__outside__';
/** The account's chat with NoClick. */
export const CHAT = '__chat__';
/** Charges recorded inside an automation before the agent and run were stamped on them. */
export const EARLIER = '__earlier__';
/** What the account itself holds (a number's month, a domain's renewal): nothing used it but the account. */
export const ACCOUNT = '__account__';

/** The platform agent a charge was made by: the one its attribution names, else the one that runs on the workflow
 *  node it was recorded in (a call its turn made under another key names only that). */
function platformAgentOf(snap: UsageSnapshot, m: UsageRow['metadata']): string | undefined {
    return m.platform_api?.agent_id ?? (m.workflow_id && m.node_id ? snap.directory.agents[`${m.workflow_id}:${m.node_id}`]?.agent : undefined);
}

/** Whether a charge was the account's chat with NoClick: the coordinator's own, or the agent that is it. */
function inChat(snap: UsageSnapshot, m: UsageRow['metadata']): boolean {
    const agent = platformAgentOf(snap, m);
    return m.surface === 'coordinator' || !!(agent && snap.directory.agents[agent]?.chat);
}

/** The charge's thing along `dim`. */
export function thingOf(snap: UsageSnapshot, row: UsageRow, dim: Dimension): string {
    const m = row.metadata;
    switch (dim) {
        case 'service':
            return rowOf(row).service;
        case 'automation':
            return inChat(snap, m) ? CHAT : m.workflow_id ?? OUTSIDE;
        case 'agent': {
            if (inChat(snap, m)) return CHAT;
            const agent = platformAgentOf(snap, m);
            if (agent) return agent;
            if (m.workflow_id) return m.node_id ? `${m.workflow_id}:${m.node_id}` : EARLIER;
            return OUTSIDE;
        }
        case 'app':
            return m.project_id ?? m.platform_api?.project_id ?? OUTSIDE;
        case 'person': {
            // A platform user; the member who ran it when the owner pays; else the payer.
            const tenant = m.platform_api?.tenant_id;
            return tenant && tenant !== 'self' ? tenant : m.actual_user_id ?? row.user_id;
        }
        case 'key':
            return m.platform_api?.key_id ?? OUTSIDE;
    }
}

export function thingLabel(snap: UsageSnapshot, dim: Dimension, id: string): string {
    const d = snap.directory;
    if (dim === 'service') return SERVICES[id as ServiceId]?.label ?? id;
    if (id === CHAT) return 'Chat with NoClick';
    if (id === EARLIER) return 'Earlier charges (agent not recorded)';
    if (id === OUTSIDE) {
        if (dim === 'automation') return 'Not in an automation';
        if (dim === 'agent') return 'Not an agent';
        if (dim === 'app') return 'Not a site';
        return 'Not through a key';
    }
    if (dim === 'automation') return d.workflows[id]?.name ?? 'Deleted automation';
    if (dim === 'agent') return agentName(snap, id);
    if (dim === 'app') return d.projects?.[id]?.name ?? 'A site';
    if (dim === 'person') return d.people[id] ? `${d.people[id].name}${id === snap.account.id ? ' (you)' : ''}` : 'Former member';
    return d.keys?.[id]?.name ?? 'A key';
}

/** An agent node by its automation ("Support agent · Inbox triage"), or a platform agent by name. An automation named
 *  after its agent (a platform agent's own) isn't named twice. */
function agentName(snap: UsageSnapshot, id: string): string {
    const d = snap.directory;
    if (d.agents[id]) {
        const wf = id.includes(':') ? d.workflows[id.split(':')[0]]?.name : null;
        return wf && wf !== d.agents[id].name ? `${d.agents[id].name} · ${wf}` : d.agents[id].name;
    }
    const wf = id.includes(':') ? d.workflows[id.split(':')[0]]?.name : null;
    return wf ? `A removed step · ${wf}` : 'An agent';
}

// ── the period ───────────────────────────────────────────────────────────────

export interface Period {
    start: number;
    end: number;
    /** UTC day keys from the window's first day up to its last. */
    days: string[];
    todayKey: string;
    /** Days fully or partly gone, counting today. */
    elapsedDays: number;
    /** Today's elapsed fraction (0-1). */
    todayFraction: number;
    /** Days left after now, fractional. */
    remainingDays: number;
}

export function periodOf(start: string, end: string, now: string): Period {
    const s = Date.parse(start);
    const e = Date.parse(end);
    const n = Date.parse(now);
    const days: string[] = [];
    for (let t = dayStart(s); t < e; t += DAY_MS) days.push(dayKey(t));
    const todayKey = dayKey(n);
    const idx = days.indexOf(todayKey);
    return {
        start: s,
        end: e,
        days,
        todayKey,
        elapsedDays: idx === -1 ? (n >= e ? days.length : 0) : idx + 1,
        todayFraction: (n - dayStart(n)) / DAY_MS,
        remainingDays: Math.max(0, (e - n) / DAY_MS),
    };
}

// ── the view ─────────────────────────────────────────────────────────────────

export interface DayRow {
    key: string;
    /** 'past' and 'today' carry what was spent; 'future' carries the projection and anything scheduled. */
    when: 'past' | 'today' | 'future';
    total: number;
    byService: Partial<Record<ServiceId, number>>;
    /** Projected metered spend for a future day (and the rest of today). */
    projected: number;
    scheduled: { label: string; usd: number }[];
    /** Predicted auto top-up landing that day. */
    topup: number;
    /** The day the money runs out on this pace. */
    runsOut: boolean;
    /** Before the account's first charge (a new account's first days). */
    before: boolean;
}

export interface ThingRow {
    id: string;
    label: string;
    total: number;
    share: number;
    previous: number;
    projected: number;
    /** The thing's spend each day of the period so far. */
    daily: number[];
    byService: Partial<Record<ServiceId, number>>;
    /** What drives the cost, in its unit: "1.2M tokens", "42 min", "318 requests". */
    count?: string;
    /** How many charges it holds. */
    charges: number;
}

export interface Projection {
    /** Point estimate for the whole period. */
    mid: number;
    low: number;
    high: number;
    /** Metered dollars a day the estimate runs at. */
    rate: number;
    /** Known charges still to land this period. */
    scheduled: number;
    basisDays: number;
    /** Day-to-day spread of metered spend (one standard deviation). */
    sd: number;
    /** How settled the pace is: a handful of days says little. */
    confidence: 'early' | 'settling' | 'steady';
    /** What the pace alone would come to; `mid` is what the money can pay for. */
    demand: number;
    /** The money runs out inside the period, so spend stops short of the pace. */
    capped: boolean;
}

export interface UpcomingItem {
    key: string;
    at: string;
    kind: 'number' | 'domain' | 'plan' | 'topup' | 'reset' | 'runout' | 'capstop' | 'whatsapp';
    label: string;
    detail: string;
    usd: number | null;
    /** Card charges (the plan) never touch the balance. */
    paidBy: 'usage' | 'card' | null;
}

export interface Runway {
    /** Dollars that can still be spent before work stops, counting included usage left and the balance. */
    spendable: number;
    /** When the money runs out at this pace (day key), or null if it lasts past the horizon. */
    runsOut: string | null;
    /** Days of headroom at this pace, null if beyond the horizon. */
    days: number | null;
    topups: { at: string; usd: number }[];
    /** The day auto top-up's monthly limit stops it, if within the horizon. */
    capStopsAt: string | null;
    /** Work is stopped now: nothing included left and no balance to carry on. */
    blocked: boolean;
    /** What can be spent from now to the period's end at this pace before anything stops it. */
    periodSpend: number;
}

export interface PaidBy {
    included: number;
    topup: number;
    balance: number;
}

export interface UsageView {
    snap: UsageSnapshot;
    period: Period;
    spent: number;
    paidBy: PaidBy;
    /** Same point in the previous window, for "vs last month at this time". */
    previousToDate: number;
    days: DayRow[];
    projection: Projection;
    /** Where the deployment bills. */
    billed: boolean;
    balance: number;
    hasBalance: boolean;
    fundsAdded: { usd: number; fee: number; count: number };
    included: { used: number; total: number | null; dailyUsed: number | null; daily: number | null };
    runway: Runway;
    upcoming: UpcomingItem[];
    /** Charges recorded this period. */
    chargeCount: number;
    /** Included usage still unspent this window (to the cent). */
    includedLeft: number;
    /** The older plans' monthly top-up pool still unspent. */
    topupLeft: number;
    /** Everything that can still be spent: included, top-up pool and balance; negative when the balance is owed. */
    left: number;
    /** Calls on the user's own keys this period: nobody is charged for them. */
    ownKeyCalls: number;
    onOldPlan: boolean;
    /** What the period cost at vendors' prices (an older plan charges more). */
    atCost: number;
}

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
export const includedShare = (r: UsageRow) => r.total_cost - (r.topup_paid ?? 0) - (r.balance_paid ?? 0);

// A drill regroups every group on each move, so each one's parse is done once.
const ROW = new WeakMap<UsageRow, { t: number; day: string; service: ServiceId }>();
function rowOf(r: UsageRow) {
    let info = ROW.get(r);
    if (!info) {
        const t = Date.parse(r.created_at);
        info = { t, day: 'day' in r ? (r as UsageGroup).day : dayKey(t), service: serviceOf(r) };
        ROW.set(r, info);
    }
    return info;
}

const METERED = new WeakMap<UsageSnapshot, UsageGroup[]>();
/** The groups someone was charged for (the user's own keys charge nobody). */
export function metered(snap: UsageSnapshot): UsageGroup[] {
    let rows = METERED.get(snap);
    if (!rows) {
        rows = snap.groups.filter((r) => !r.user_resource);
        METERED.set(snap, rows);
    }
    return rows;
}

/** `usage:page`'s flat groups as rows every breakdown reads. */
export function toSnapshot(data: UsagePageData): UsageSnapshot {
    const str = (v: unknown) => (typeof v === 'string' && v ? v : undefined);
    const groups: UsageGroup[] = data.groups.map((g) => {
        const pa = {
            agent_id: str(g.pa_agent_id),
            tenant_id: str(g.pa_tenant_id),
            key_id: str(g.pa_key_id),
            project_id: str(g.pa_project_id),
            surface: str(g.pa_surface),
        };
        const metadata = {
            workflow_id: str(g.workflow_id),
            node_id: str(g.node_id),
            surface: str(g.surface),
            actual_user_id: str(g.actual_user_id),
            project_id: str(g.project_id),
            database_id: str(g.database_id),
            repo_id: str(g.repo_id),
            inbox_id: str(g.inbox_id),
            phone_number_id: str(g.phone_number_id),
            number: str(g.number),
            channel: str(g.channel),
            from: str(g.sender),
            credential_id: str(g.credential_id),
            domain: str(g.domain),
            ...(Object.values(pa).some(Boolean) ? { platform_api: pa } : {}),
        };
        return {
            id: `${g.k}:${g.day}:${g.current ? 1 : 0}`,
            created_at: g.created_at,
            user_id: g.user_id,
            usage_type: g.usage_type,
            usage_subtype: g.usage_subtype,
            quantity: g.quantity,
            unit_type: g.unit_type,
            total_cost: g.total_cost,
            cost_usd: g.cost_usd ?? null,
            topup_paid: g.topup_paid ?? 0,
            balance_paid: g.balance_paid ?? 0,
            user_resource: g.user_resource,
            metadata,
            k: g.k,
            n: g.n,
            current: g.current,
            day: g.day,
            prompt_tokens: g.prompt_tokens,
            completion_tokens: g.completion_tokens,
        };
    });
    return { now: data.now, account: data.account, period: data.period, billing: data.billing, groups, directory: data.directory };
}

/** Rate and spread from the last full days; recent days weigh as much as the whole history would (recency = pace). */
function paceOf(dailyMetered: number[]) {
    const basis = dailyMetered.slice(-10);
    const n = basis.length;
    if (!n) return { rate: 0, sd: 0, n: 0 };
    const rate = sum(basis) / n;
    const sd = n > 1 ? Math.sqrt(sum(basis.map((v) => (v - rate) ** 2)) / (n - 1)) : rate;
    return { rate, sd, n };
}

export function deriveView(snap: UsageSnapshot): UsageView {
    const billing = snap.billing;
    const plan = billing?.plan ?? null;
    const nowT = Date.parse(snap.now);
    const period = periodOf(snap.period.window_start, snap.period.window_end, snap.now);
    const rows = metered(snap);
    const cur = rows.filter((r) => r.current);
    const prev = rows.filter((r) => !r.current);
    const spent = sum(cur.map((r) => r.total_cost));
    const paidBy: PaidBy = {
        included: sum(cur.map(includedShare)),
        topup: sum(cur.map((r) => r.topup_paid ?? 0)),
        balance: sum(cur.map((r) => r.balance_paid ?? 0)),
    };
    const prevS = Date.parse(snap.period.previous_start);
    const previousToDate = sum(prev.filter((r) => rowOf(r).t < prevS + (nowT - period.start)).map((r) => r.total_cost));

    // Each day: what was spent, by service.
    const byDay = new Map<string, { total: number; meteredTotal: number; byService: Partial<Record<ServiceId, number>> }>();
    for (const r of cur) {
        const d = byDay.get(r.day) ?? { total: 0, meteredTotal: 0, byService: {} };
        d.total += r.total_cost;
        if (!isScheduled(r)) d.meteredTotal += r.total_cost;
        const s = rowOf(r).service;
        d.byService[s] = (d.byService[s] ?? 0) + r.total_cost;
        byDay.set(r.day, d);
    }
    // The pace: metered spend on full days since the first charge (or the window's start).
    const firstRow = rows.length ? Math.min(...rows.map((r) => rowOf(r).t)) : nowT;
    const fullDays = period.days.slice(0, Math.max(0, period.elapsedDays - 1)).filter((k) => Date.parse(`${k}T00:00:00Z`) >= dayStart(firstRow));
    const pace = paceOf(fullDays.map((k) => byDay.get(k)?.meteredTotal ?? 0));
    const todayMetered = byDay.get(period.todayKey)?.meteredTotal ?? 0;
    const restOfToday = Math.max(0, pace.rate * (1 - period.todayFraction) - Math.max(0, todayMetered - pace.rate * period.todayFraction));

    // Scheduled charges still to come this period, by day.
    const scheduledByDay = new Map<string, { label: string; usd: number }[]>();
    const addScheduled = (at: string, label: string, usd: number) => {
        const k = dayKey(at);
        scheduledByDay.set(k, [...(scheduledByDay.get(k) ?? []), { label, usd }]);
    };
    const upcoming: UpcomingItem[] = [];
    const horizon = Math.max(period.end, nowT + 31 * DAY_MS);
    for (const c of billing?.recurring ?? []) {
        if (c.period_amount != null && c.paid_through) {
            for (let t = Date.parse(c.paid_through); t < horizon; t += 30 * DAY_MS) {
                if (t <= nowT) continue;
                if (t < period.end) addScheduled(new Date(t).toISOString(), c.label, c.period_amount);
                upcoming.push({ key: `${c.id}:${t}`, at: new Date(t).toISOString(), kind: 'number', label: c.label || 'A number', detail: 'Phone number, a month', usd: c.period_amount, paidBy: 'usage' });
            }
        } else if (c.hourly_amount != null && c.period_amount == null) {
            upcoming.push({ key: c.id, at: snap.now, kind: 'whatsapp', label: c.label || 'A connection', detail: `WhatsApp, ${money(c.hourly_amount * 24 * 30)} a month by the hour`, usd: null, paidBy: 'usage' });
        }
    }
    for (const d of billing?.domains ?? []) {
        const t = Date.parse(d.expires_at);
        if (t > nowT && t < nowT + 60 * DAY_MS) {
            if (t < period.end && d.auto_renew) addScheduled(d.expires_at, d.name, d.renewal_usd);
            upcoming.push({ key: d.id, at: d.expires_at, kind: 'domain', label: d.name, detail: d.auto_renew ? `Renews for ${d.renewal_years === 1 ? 'a year' : `${d.renewal_years} years`}` : 'Expires: renewal is off', usd: d.auto_renew ? d.renewal_usd : null, paidBy: d.auto_renew ? 'usage' : null });
        }
    }
    if (plan?.renews_at && plan.plan_price_usd > 0) {
        upcoming.push({ key: 'plan', at: plan.renews_at, kind: 'plan', label: `${planName(plan.tier)} plan`, detail: plan.renews_yearly ? 'A year, to your card' : `To your card, ${plan.included_usd ? `${roundMoney(plan.included_usd)} included again` : 'a month'}`, usd: plan.plan_price_usd, paidBy: 'card' });
    } else if (plan?.included_usd) {
        upcoming.push({ key: 'reset', at: plan.window_end, kind: 'reset', label: 'Included usage resets', detail: `${money(plan.included_usd)} for ${new Date(plan.window_end).toLocaleDateString('en-US', { month: 'long', timeZone: 'UTC' })}`, usd: null, paidBy: null });
    }
    const scheduledLeft = sum([...scheduledByDay.values()].flat().map((s) => s.usd));

    // The money: balance, included usage left, and how long both last at this pace (auto top-up included). Where
    // nothing is billed, or the plan is unlimited, nothing runs out.
    const hasBalance = !!billing?.balance.has;
    const balance = billing?.balance.usd ?? 0;
    const included = {
        used: plan?.included_used_usd ?? 0,
        total: plan?.included_usd ?? null,
        dailyUsed: plan?.daily_used_usd ?? null,
        daily: plan?.daily_usd ?? null,
    };
    const includedLeft = included.total == null ? 0 : Math.max(0, included.total - included.used);
    const topupLeft = Math.max(0, (plan?.topup_usd ?? 0) - (plan?.topup_used_usd ?? 0));
    const runway: Runway =
        plan && plan.included_usd != null
            ? simulate(snap, plan, {
                  balance,
                  hasBalance,
                  includedLeft,
                  topupLeft,
                  dailyLeft: plan.daily_usd != null ? Math.max(0, plan.daily_usd - (plan.daily_used_usd ?? 0)) : null,
                  rate: pace.rate,
                  restOfToday,
                  scheduledByDay,
                  period,
              })
            : { spendable: Infinity, runsOut: null, days: null, topups: [], capStopsAt: null, blocked: false, periodSpend: pace.rate * period.remainingDays + scheduledLeft };

    // The projection and its 80% range: day-to-day spread plus how little a few days say about the pace. The range is
    // the pace's; the point is what the money can pay for, which stops short when it runs out inside the period.
    const R = period.remainingDays;
    const variance = pace.n ? R * pace.sd ** 2 + (R * R * pace.sd ** 2) / pace.n : (spent || 1) ** 2;
    const half = 1.2816 * Math.sqrt(variance);
    const demand = spent + pace.rate * R + scheduledLeft;
    const capped = runway.blocked || (runway.runsOut != null && Date.parse(`${runway.runsOut}T00:00:00Z`) < period.end);
    const mid = capped ? spent + runway.periodSpend : demand;
    const projection: Projection = {
        mid,
        low: capped ? mid : Math.max(spent + scheduledLeft, demand - half),
        high: capped ? mid : demand + half,
        rate: pace.rate,
        scheduled: scheduledLeft,
        basisDays: pace.n,
        sd: pace.sd,
        confidence: pace.n < 4 ? 'early' : pace.n < 10 ? 'settling' : 'steady',
        demand,
        capped,
    };
    const auto = billing?.autoTopUp ?? null;
    if (runway.runsOut && !runway.blocked) {
        upcoming.push({ key: 'runout', at: `${runway.runsOut}T12:00:00Z`, kind: 'runout', label: hasBalance ? 'Balance runs out' : plan?.billing_model === 'legacy' ? 'Credits run out' : 'Included usage runs out', detail: 'At this pace, unless funds are added', usd: null, paidBy: null });
    }
    for (const t of runway.topups.filter((x) => Date.parse(`${x.at}T00:00:00Z`) < horizon)) upcoming.push({ key: `topup:${t.at}`, at: `${t.at}T12:00:00Z`, kind: 'topup', label: 'Auto top-up', detail: auto ? `Balance under ${roundMoney(auto.thresholdUsd)}` : '', usd: t.usd, paidBy: 'card' });
    if (runway.capStopsAt) upcoming.push({ key: 'capstop', at: `${runway.capStopsAt}T12:00:00Z`, kind: 'capstop', label: 'Auto top-up reaches its monthly limit', detail: auto ? `${money(auto.monthlyCapUsd)} a month` : '', usd: null, paidBy: null });
    upcoming.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));

    const days: DayRow[] = period.days.map((k, idx) => {
        const when: DayRow['when'] = k === period.todayKey ? 'today' : idx < period.elapsedDays - 1 ? 'past' : 'future';
        const d = byDay.get(k);
        return {
            key: k,
            when,
            total: when === 'future' ? 0 : d?.total ?? 0,
            byService: when === 'future' ? {} : d?.byService ?? {},
            // Nothing is spent once the money has run out (or while work is stopped).
            projected: runway.blocked || (runway.runsOut != null && k > runway.runsOut) ? 0 : when === 'future' ? pace.rate : when === 'today' ? restOfToday : 0,
            scheduled: scheduledByDay.get(k) ?? [],
            topup: sum(runway.topups.filter((t) => t.at === k).map((t) => t.usd)),
            runsOut: !runway.blocked && runway.runsOut === k,
            before: k < dayKey(firstRow),
        };
    });

    const round = (x: number) => Math.round(x * 100) / 100;
    return {
        snap,
        period,
        spent,
        paidBy,
        previousToDate,
        days,
        projection,
        billed: !!billing,
        balance,
        hasBalance,
        fundsAdded: billing?.funds ?? { usd: 0, fee: 0, count: 0 },
        included,
        runway,
        upcoming,
        chargeCount: sum(cur.map((r) => r.n)),
        includedLeft: round(includedLeft),
        topupLeft: round(topupLeft),
        left: balance < 0 ? balance : round(includedLeft) + round(topupLeft) + (hasBalance ? balance : 0),
        ownKeyCalls: sum(snap.groups.filter((r) => r.user_resource && r.current).map((r) => r.n)),
        onOldPlan: plan?.billing_model === 'legacy',
        atCost: sum(cur.map((r) => r.cost_usd ?? r.total_cost)),
    };
}

/** A label inside a sentence: "AI models" keeps its capitals, "Calls and texts" becomes "calls and texts". */
export function inSentence(label: string): string {
    return /^[A-Z]{2}/.test(label) ? label : label.charAt(0).toLowerCase() + label.slice(1);
}

export function planName(tier: string): string {
    return tier.charAt(0).toUpperCase() + tier.slice(1);
}

/** Walk forward a day at a time at this pace: included usage first (Free's day, then the window), then the balance,
 *  with auto top-up refilling under its threshold within its daily and monthly limits. */
function simulate(
    snap: UsageSnapshot,
    plan: NonNullable<UsageSnapshot['billing']>['plan'],
    s: { balance: number; hasBalance: boolean; includedLeft: number; topupLeft: number; dailyLeft: number | null; rate: number; restOfToday: number; scheduledByDay: Map<string, { usd: number }[]>; period: Period }
): Runway {
    const settings = snap.billing?.autoTopUp ?? null;
    const auto = settings?.enabled && settings.hasMethod && !settings.pausedReason ? settings : null;
    let balance = s.balance;
    let monthLeft = s.includedLeft;
    let topupLeft = s.topupLeft;
    let dayLeft = s.dailyLeft;
    let autoMonth = settings?.monthUsd ?? 0;
    const topups: { at: string; usd: number }[] = [];
    let capStopsAt: string | null = null;
    let periodSpend = 0;
    const spendable = monthLeft + topupLeft + (s.hasBalance ? Math.max(0, balance) : 0);
    const nowT = Date.parse(snap.now);
    const end = (runsOut: string | null, days: number | null, blocked = false): Runway => ({ spendable, runsOut, days, topups, capStopsAt, blocked, periodSpend });
    // Stopped now: the window's included usage and the top-up pool are spent and there's no balance to carry on.
    if (monthLeft <= 0.0001 && topupLeft <= 0.0001 && (!s.hasBalance || balance <= 0)) return end(dayKey(nowT), 0, true);
    const windowEnd = Date.parse(plan.window_end);
    const included = plan.included_usd ?? 0;
    for (let i = 0; i < 62; i++) {
        const t = dayStart(nowT) + i * DAY_MS;
        const k = dayKey(t);
        if (i > 0 && dayLeft != null) dayLeft = plan.daily_usd;
        if (t >= windowEnd && t < windowEnd + DAY_MS) {
            monthLeft = included; // the window renews
            topupLeft = plan.topup_usd;
        }
        if (k.endsWith('-01')) autoMonth = 0; // auto top-up's limit counts the UTC month
        let need = (i === 0 ? s.restOfToday : s.rate) + (s.scheduledByDay.get(k)?.reduce((a, b) => a + b.usd, 0) ?? 0);
        const inc = Math.min(need, dayLeft != null ? Math.min(dayLeft, monthLeft) : monthLeft);
        monthLeft -= inc;
        if (dayLeft != null) dayLeft -= inc;
        need -= inc;
        const top = Math.min(need, topupLeft);
        topupLeft -= top;
        need -= top;
        let spentToday = inc + top;
        let stop = false;
        if (need > 1e-9) {
            if (!s.hasBalance) {
                // Free's daily dollar stops work for the day; the window's included usage running out stops it for good.
                stop = monthLeft <= 1e-9 && topupLeft <= 1e-9;
            } else {
                balance -= need;
                spentToday += need;
                let todays = 0;
                while (auto && balance < auto.thresholdUsd && todays < 3) {
                    if (autoMonth + auto.amountUsd > auto.monthlyCapUsd) {
                        capStopsAt = capStopsAt ?? k;
                        break;
                    }
                    balance += auto.amountUsd;
                    autoMonth += auto.amountUsd;
                    todays += 1;
                    topups.push({ at: k, usd: auto.amountUsd });
                }
                if (balance < 0) {
                    spentToday += balance; // only what was there gets spent
                    stop = true;
                }
            }
        }
        if (t < s.period.end) periodSpend += Math.max(0, t + DAY_MS > s.period.end ? spentToday * ((s.period.end - t) / DAY_MS) : spentToday);
        if (stop) return end(k, i);
    }
    return end(null, null);
}

// ── breakdowns ───────────────────────────────────────────────────────────────

/** Groups regrouped by `keyOf`, within `where`: the period's spend, share, each day, last period and the pace's
 *  estimate. */
function groupRows(view: UsageView, keyOf: (r: UsageGroup) => { id: string; label: string }, where?: ((r: UsageGroup) => boolean) | null): ThingRow[] {
    const { snap, period, runway } = view;
    // Days left that money will be spent on: none while stopped, up to the day it runs out.
    const activeDaysLeft = runway.blocked ? 0 : runway.runsOut ? Math.min(period.remainingDays, Math.max(0, (Date.parse(`${runway.runsOut}T00:00:00Z`) + DAY_MS - Date.parse(snap.now)) / DAY_MS)) : period.remainingDays;
    const rows = metered(snap).filter((r) => !where || where(r));
    const cur = rows.filter((r) => r.current);
    const prev = rows.filter((r) => !r.current);
    const total = sum(cur.map((r) => r.total_cost)) || 1;
    const groups = new Map<string, ThingRow>();
    const units = new Map<string, Map<string, { q: number; usd: number }>>();
    const dayIdx = new Map(period.days.map((k, i) => [k, i]));
    for (const r of cur) {
        const key = keyOf(r);
        const g = groups.get(key.id) ?? { id: key.id, label: key.label, total: 0, share: 0, previous: 0, projected: 0, daily: period.days.slice(0, period.elapsedDays).map(() => 0), byService: {}, charges: 0 };
        g.total += r.total_cost;
        g.charges += r.n;
        const info = rowOf(r);
        const i = dayIdx.get(info.day);
        if (i != null && i < g.daily.length) g.daily[i] += r.total_cost;
        g.byService[info.service] = (g.byService[info.service] ?? 0) + r.total_cost;
        groups.set(key.id, g);
        const u = units.get(key.id) ?? new Map();
        const t = u.get(r.unit_type) ?? { q: 0, usd: 0 };
        t.q += r.quantity;
        t.usd += r.total_cost;
        u.set(r.unit_type, t);
        units.set(key.id, u);
    }
    for (const r of prev) {
        const g = groups.get(keyOf(r).id);
        if (g) g.previous += r.total_cost;
    }
    for (const g of groups.values()) {
        g.share = g.total / total;
        const full = g.daily.slice(0, -1);
        const recent = full.slice(-10);
        const rate = recent.length ? sum(recent) / recent.length : 0;
        g.projected = g.total + rate * activeDaysLeft;
        // The unit that carries most of the money is the count worth reading.
        const main = [...(units.get(g.id) ?? [])].sort(([, a], [, b]) => b.usd - a.usd)[0];
        if (main) g.count = totalQuantity(main[0], main[1].q);
    }
    return [...groups.values()].sort((a, b) => b.total - a.total);
}

export function breakdown(view: UsageView, dim: Dimension, where?: { dim: Dimension; id: string } | ((r: UsageGroup) => boolean) | null): ThingRow[] {
    const filter = !where ? null : typeof where === 'function' ? where : (r: UsageGroup) => thingOf(view.snap, r, where.dim) === where.id;
    return groupRows(
        view,
        (r) => {
            const id = thingOf(view.snap, r, dim);
            return { id, label: thingLabel(view.snap, dim, id) };
        },
        filter
    );
}

// ── inside a service: what in it cost the most ───────────────────────────────

const HOURS_PER_MONTH = 730;
/** One decimal under ten, whole above: "2.4", "18". */
const decimal = (n: number) => (n >= 10 ? `${Math.round(n)}` : n.toFixed(1));

/** A total of one unit, as a person reads it: "1.2M tokens", "42 min", "318 requests", "6.4 MB·h". */
export function totalQuantity(unit: string, q: number): string {
    const big = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}K` : `${Math.round(n)}`);
    switch (unit) {
        case 'tokens':
            return `${big(q)} tokens`;
        case 'seconds':
            return q >= 5400 ? `${(q / 3600).toFixed(1)} h` : `${Math.max(1, Math.round(q / 60))} min`;
        case 'requests':
            return `${big(q)} ${q === 1 ? 'request' : 'requests'}`;
        case 'rows':
            return `${big(q)} rows`;
        case 'month':
            // A fraction of a month is what a site keeps for an hour: its hours, times the things kept.
            return q >= 0.95 ? `${Math.round(q)} ${Math.round(q) === 1 ? 'month' : 'months'}` : `${decimal(q * HOURS_PER_MONTH)} h`;
        case 'hour':
            return `${Math.round(q)} h`;
        case 'gb_hours':
            return q >= 1 ? `${decimal(q)} GB·h` : q * 1024 >= 1 ? `${decimal(q * 1024)} MB·h` : `${decimal(q * 1024 * 1024)} KB·h`;
        case 'mb':
            return q >= 1 ? `${big(q)} MB` : `${decimal(q * 1024)} KB`;
        case 'million_requests':
            return `${big(q * 1e6)} requests`;
        case 'images':
            return `${big(q)} images`;
        default:
            return `${big(q)} ${unit}`;
    }
}

const NOCLICK_MODEL = 'noclick-model';
const isNoClickModel = (r: UsageRow) => r.usage_type === 'ai_builder' || r.usage_type === 'ai_testing' || r.usage_subtype.startsWith('noclick/');

const nodeName = (s: UsageSnapshot, m: UsageRow['metadata']) => (m.workflow_id && m.node_id ? agentName(s, `${m.workflow_id}:${m.node_id}`) : m.workflow_id ? s.directory.workflows[m.workflow_id]?.name ?? 'An automation' : 'An agent');

/** What each service's items are, from fields its charges carry. Charges recorded before a field was stamped group
 *  under one "earlier" row rather than be guessed into a place. `used`: the item already says what used it (an
 *  agent's sandbox, a site's hosting, what the account itself holds), so it doesn't open onto that. */
export const FACETS: Record<ServiceId, { by: string; used?: true; of: (snap: UsageSnapshot, r: UsageRow) => { id: string; label: string } }> = {
    // usage_subtype is the model for every model call; the builder's and test runs' is NoClick's own, which they name
    // by what used it, so that is the next level down.
    ai: { by: 'Model', of: (_, r) => (isNoClickModel(r) ? { id: NOCLICK_MODEL, label: 'NoClick’s own model' } : { id: r.usage_subtype, label: getDisplayName(r.usage_subtype) }) },
    sandboxes: {
        by: 'Agent',
        used: true,
        of: (s, r) => {
            const a = platformAgentOf(s, r.metadata);
            if (a) return { id: `agent:${a}`, label: s.directory.agents[a]?.name ?? 'An agent' };
            return { id: `${r.metadata.workflow_id ?? '-'}:${r.metadata.node_id ?? '-'}`, label: nodeName(s, r.metadata) };
        },
    },
    machines: { by: 'Machine', of: (_, r) => ({ id: r.usage_subtype, label: getDisplayName(r.usage_subtype) }) },
    browsers: { by: 'Browser', of: (_, r) => ({ id: r.usage_subtype, label: getDisplayName(r.usage_subtype) }) },
    calls: {
        by: 'Line',
        of: (s, r) => {
            const m = r.metadata;
            if (r.usage_subtype === 'voice/call') {
                if (m.number) return { id: `calls:${m.number}`, label: `Calls on ${phoneLabel(m.number)}` };
                if (m.channel === 'number') return { id: 'calls:earlier', label: 'Earlier calls on your numbers (number not recorded)' };
                return { id: `calls:${m.channel ?? 'noclick'}`, label: m.channel === 'whatsapp' ? 'Calls with NoClick on WhatsApp' : 'Calls with NoClick' };
            }
            if (r.usage_subtype.startsWith('phone/text_') && m.phone_number_id) return { id: `texts:${m.phone_number_id}`, label: `Texts on ${s.directory.numbers?.[m.phone_number_id]?.name ?? 'a number'}` };
            if (r.usage_subtype.startsWith('whatsapp/')) return { id: 'whatsapp', label: 'WhatsApp messages from NoClick' };
            return { id: r.usage_subtype, label: getDisplayName(r.usage_subtype) };
        },
    },
    // A number's month and a WhatsApp connection's hours carry their credential.
    numbers: {
        by: 'Number',
        used: true,
        of: (s, r) => {
            const c = s.billing?.recurring.find((x) => x.credential_id === r.metadata.credential_id);
            return { id: r.metadata.credential_id ?? r.usage_subtype, label: c ? (c.charge_type === 'whatsapp_connection' ? `WhatsApp, ${c.label}` : c.label) : 'A removed number' };
        },
    },
    email: {
        by: 'Sender',
        of: (s, r) => {
            const m = r.metadata;
            if (m.project_id) return { id: `app:${m.project_id}`, label: `${s.directory.projects?.[m.project_id]?.name ?? 'A site'} (site email)` };
            if (m.inbox_id) return { id: `inbox:${m.inbox_id}`, label: s.directory.inboxes?.[m.inbox_id]?.name ?? 'An inbox' };
            if (m.from) return { id: `from:${m.from}`, label: m.from };
            if (r.usage_subtype === 'email/coordinator') return { id: 'coordinator', label: 'NoClick’s address' };
            if (r.usage_subtype === 'email/send_node' && m.workflow_id) return { id: `send:${m.workflow_id}:${m.node_id ?? ''}`, label: `${nodeName(s, m)} (email step)` };
            if (r.usage_subtype === 'email/agent_update') return { id: 'updates:earlier', label: 'Earlier agent updates (address not recorded)' };
            return { id: r.usage_subtype, label: getDisplayName(r.usage_subtype) };
        },
    },
    apps: { by: 'Site', used: true, of: (s, r) => ({ id: r.metadata.project_id ?? '-', label: s.directory.projects?.[r.metadata.project_id ?? '']?.name ?? 'A site' }) },
    databases: { by: 'Database', of: (s, r) => ({ id: r.metadata.database_id ?? '-', label: s.directory.databases?.[r.metadata.database_id ?? '']?.name ?? 'A database' }) },
    storage: { by: 'Store', of: (_, r) => ({ id: r.metadata.repo_id ?? r.usage_subtype, label: r.metadata.repo_id ? `Repo ${r.metadata.repo_id}` : getDisplayName(r.usage_subtype) }) },
    domains: { by: 'Domain', used: true, of: (_, r) => ({ id: r.metadata.domain ?? '-', label: r.metadata.domain ?? 'A domain' }) },
    tools: { by: 'Tool', of: (_, r) => ({ id: r.usage_subtype, label: getDisplayName(r.usage_subtype) }) },
};

/** Work every group's facet out ahead of the first drill, when the page is idle. */
export function warmFacets(snap: UsageSnapshot): void {
    for (const r of metered(snap)) facetOf(snap, r);
}

// A group belongs to one snapshot, so its place in its service's breakdown is worked out once.
const FACET = new WeakMap<UsageRow, { id: string; label: string }>();
export function facetOf(snap: UsageSnapshot, r: UsageRow): { id: string; label: string } {
    let f = FACET.get(r);
    if (!f) {
        f = FACETS[rowOf(r).service].of(snap, r);
        FACET.set(r, f);
    }
    return f;
}

/** What the drill picked, as one row: its spend, each day, and its share of the whole period. */
export function selectionOf(view: UsageView, match: (r: UsageGroup) => boolean): ThingRow | null {
    const [row] = groupRows(view, () => ({ id: 'selection', label: '' }), match);
    return row ? { ...row, share: view.spent ? row.total / view.spent : 0 } : null;
}

/** "All services", "All automations": the top of a drill. */
export const ROOT_LABEL: Record<Dimension, string> = { service: 'All services', automation: 'All automations', agent: 'All agents', app: 'All sites', person: 'Everyone', key: 'All keys' };

const NOUN: Partial<Record<ServiceId, string>> = { email: 'emails', calls: 'messages' };

export function facets(view: UsageView, service: ServiceId, where?: ((r: UsageGroup) => boolean) | null): ThingRow[] {
    const rows = groupRows(view, (r) => facetOf(view.snap, r), (r) => rowOf(r).service === service && (!where || where(r)));
    const noun = NOUN[service];
    return noun ? rows.map((r) => ({ ...r, count: r.count?.replace(/requests?$/, noun) })) : rows;
}

/** Who used a charge: the agent or automation step it ran in, the account's chat with NoClick, the AI Builder, a site,
 *  an API key, or the account itself for what it holds. Charges recorded before that was stamped on them share
 *  one "earlier" row; nothing is guessed. */
export function consumerOf(snap: UsageSnapshot, r: UsageRow): { id: string; label: string } {
    const m = r.metadata;
    const d = snap.directory;
    // The builder and test runs, by the automation they worked on.
    const on = (id: string, label: string) => (m.workflow_id ? { id: `${id}:${m.workflow_id}`, label: `${label} · ${d.workflows[m.workflow_id]?.name ?? 'a deleted automation'}` } : { id, label });
    // Naming an automation is the builder's call too (workflow_builder_handler's naming charge).
    if (r.usage_type === 'ai_builder' || r.usage_subtype.startsWith('noclick/builder') || m.surface === 'workflow_name') return on('builder', 'AI Builder');
    if (r.usage_type === 'ai_testing') return on('testing', 'Test runs');
    if (inChat(snap, m)) return { id: CHAT, label: 'Chat with NoClick' };
    const agent = platformAgentOf(snap, m);
    if (agent) return { id: `agent:${agent}`, label: d.agents[agent]?.name ?? 'An agent' };
    if (m.workflow_id && m.node_id) return { id: `${m.workflow_id}:${m.node_id}`, label: agentName(snap, `${m.workflow_id}:${m.node_id}`) };
    if (m.workflow_id) return { id: `workflow:${m.workflow_id}`, label: `${d.workflows[m.workflow_id]?.name ?? 'A deleted automation'} (step not recorded)` };
    const project = m.project_id ?? m.platform_api?.project_id;
    if (project) return { id: `app:${project}`, label: d.projects?.[project]?.name ?? 'A site' };
    const key = m.platform_api?.key_id;
    if (key) return { id: `key:${key}`, label: d.keys?.[key]?.name ? `API key ${d.keys[key].name}` : 'An API key' };
    if (r.usage_type === 'recurring' || r.usage_subtype.startsWith('domain/')) return { id: ACCOUNT, label: 'Your account' };
    return { id: EARLIER, label: 'Earlier (not recorded)' };
}

export type ConsumerKind = 'step' | 'agent' | 'site' | 'chat' | 'builder' | 'key' | 'account' | 'earlier';

/** What kind of thing a consumer is, from its id. */
export function consumerKind(id: string): ConsumerKind {
    if (id === CHAT) return 'chat';
    if (id === ACCOUNT) return 'account';
    if (id === EARLIER) return 'earlier';
    const prefix = id.includes(':') ? id.slice(0, id.indexOf(':')) : id;
    if (prefix === 'builder' || prefix === 'testing') return 'builder';
    if (prefix === 'agent') return 'agent';
    if (prefix === 'app') return 'site';
    if (prefix === 'key') return 'key';
    return 'step';
}

const CONSUMER = new WeakMap<UsageRow, { id: string; label: string }>();
function consumerOfCached(snap: UsageSnapshot, r: UsageRow) {
    let c = CONSUMER.get(r);
    if (!c) {
        c = consumerOf(snap, r);
        CONSUMER.set(r, c);
    }
    return c;
}

/** What used one item of a service (a model, a number, a tool, a site). */
export function consumers(view: UsageView, service: ServiceId, item: string, where?: ((r: UsageGroup) => boolean) | null): ThingRow[] {
    const rows = groupRows(view, (r) => consumerOfCached(view.snap, r), (r) => rowOf(r).service === service && facetOf(view.snap, r).id === item && (!where || where(r)));
    const noun = NOUN[service];
    return noun ? rows.map((r) => ({ ...r, count: r.count?.replace(/requests?$/, noun) })) : rows;
}

/** A step of a drill: a thing along a dimension, or an item inside the service picked above it. */
export type Step = { dim: Dimension | 'item'; id: string };

/** Where a person is in "Where it goes": the steps taken on the way down, and one row picked at the bottom. */
export interface Drill {
    path: Step[];
    /** The bottom row picked: what used an item, or an item when the drill already names who used it. */
    pick: string | null;
}

export const NO_DRILL: Drill = { path: [], pick: null };

export type DrillList = { kind: 'dim'; dim: Dimension } | { kind: 'facet'; service: ServiceId } | { kind: 'consumer'; service: ServiceId; item: string };

/** The list a drill shows: the root tab; inside a service, its items; inside an item, what used it; inside any other
 *  thing, its services. */
export function drillList(drill: Pick<Drill, 'path'>, root: Dimension): DrillList {
    const last = drill.path[drill.path.length - 1];
    if (!last) return { kind: 'dim', dim: root };
    if (last.dim === 'service') return { kind: 'facet', service: last.id as ServiceId };
    if (last.dim === 'item') {
        const service = [...drill.path].reverse().find((s) => s.dim === 'service');
        return { kind: 'consumer', service: service?.id as ServiceId, item: last.id };
    }
    return { kind: 'dim', dim: 'service' };
}

/** Whether a service's items open onto what used them: not where the item already says, nor once the drill names
 *  one agent. */
export function itemsOpen(drill: Pick<Drill, 'path'>, service: ServiceId): boolean {
    return !FACETS[service].used && !drill.path.some((s) => s.dim === 'agent');
}

function stepMatches(snap: UsageSnapshot, r: UsageRow, step: Step): boolean {
    return step.dim === 'item' ? facetOf(snap, r).id === step.id : thingOf(snap, r, step.dim) === step.id;
}

export function drillMatch(snap: UsageSnapshot, drill: Drill, withPick = true): ((r: UsageRow) => boolean) | null {
    if (!drill.path.length && !drill.pick) return null;
    const atConsumers = drillList(drill, 'service').kind === 'consumer';
    return (r) =>
        drill.path.every((s) => stepMatches(snap, r, s)) &&
        (!withPick || !drill.pick || (atConsumers ? consumerOfCached(snap, r).id : facetOf(snap, r).id) === drill.pick);
}

/** A drill's steps as a person reads them. */
export function drillLabels(view: UsageView, drill: Drill): string[] {
    const labels = drill.path.map((s, i) => {
        if (s.dim !== 'item') return thingLabel(view.snap, s.dim, s.id);
        const above = { path: drill.path.slice(0, i), pick: null };
        const at = drillList(above, 'service');
        const row = at.kind === 'facet' ? facets(view, at.service, drillMatch(view.snap, above)).find((f) => f.id === s.id) : null;
        return row?.label ?? s.id;
    });
    if (drill.pick) {
        const at = drillList(drill, 'service');
        const within = drillMatch(view.snap, { path: drill.path, pick: null });
        const rows = at.kind === 'consumer' ? consumers(view, at.service, at.item, within) : at.kind === 'facet' ? facets(view, at.service, within) : [];
        labels.push(rows.find((f) => f.id === drill.pick)?.label ?? drill.pick);
    }
    return labels;
}

/** A drill in a URL: `in=service:ai,automation:wf_1` and `pick=<row>`. */
export function drillToParams(drill: Drill): Record<string, string | null> {
    return { in: drill.path.length ? drill.path.map((s) => `${s.dim}:${encodeURIComponent(s.id)}`).join(',') : null, pick: drill.pick };
}

export function drillFromParams(inParam: string | null, pick: string | null): Drill {
    const path = (inParam ?? '')
        .split(',')
        .filter(Boolean)
        .map((s) => {
            const i = s.indexOf(':');
            return { dim: s.slice(0, i), id: decodeURIComponent(s.slice(i + 1)) };
        })
        .filter((s) => s.dim in DIMENSION_LABEL || s.dim === 'item') as Step[];
    return { path, pick: path.length ? pick : null };
}

/** Which dimensions the charges have anything to say about. */
export function dimensionsFor(view: UsageView): Dimension[] {
    const rows = metered(view.snap);
    const dims: Dimension[] = ['service', 'automation'];
    if (rows.some((r) => r.metadata.platform_api?.agent_id || (r.metadata.workflow_id && r.metadata.node_id))) dims.push('agent');
    if (rows.some((r) => r.metadata.project_id ?? r.metadata.platform_api?.project_id)) dims.push('app');
    if (rows.some((r) => thingOf(view.snap, r, 'person') !== view.snap.account.id)) dims.push('person');
    return dims;
}

// ── charges ──────────────────────────────────────────────────────────────────

export interface LineItem {
    id: string;
    at: string;
    /** What it was: a model, a call, sandbox time, a day of hosting. */
    what: string;
    /** A detail a hover reveals: tokens in and out, a call's length. */
    detail: string | null;
    service: ServiceId;
    /** What used it (consumerOf), and what kind of thing that is. */
    thing: string;
    thingKind: ConsumerKind;
    /** Who ran it, when a workspace's owner pays for someone else's work. */
    runner: string | null;
    quantity: string;
    usd: number;
    paidFrom: 'Included' | 'Balance' | 'Top-up' | 'Split' | null;
    split: PaidBy;
    row: ChargeRow;
    /** A site's hourly reading folded into one line: the charges it's made of. */
    parts?: LineItem[];
}

const compact = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}K` : `${n}`);

const QUANTITY: Partial<Record<string, (q: number) => string>> = {
    tokens: (q) => `${compact(q)} tokens`,
    seconds: (q) => (q >= 3600 ? `${Math.floor(q / 3600)}h ${Math.round((q % 3600) / 60)}m` : q >= 60 ? `${Math.floor(q / 60)}m ${String(Math.round(q % 60)).padStart(2, '0')}s` : `${Math.round(q)}s`),
    requests: (q) => `${q} ${q === 1 ? 'request' : 'requests'}`,
    rows: (q) => `${q.toLocaleString('en-US')} ${q === 1 ? 'row' : 'rows'}`,
    month: (q) => (q === 1 ? 'a month' : totalQuantity('month', q)),
    images: (q) => `${q} ${q === 1 ? 'image' : 'images'}`,
};

/** One charge's quantity: a site's traffic by the requests it counted (the ledger keeps millions). */
export const quantityLabel = (r: UsageRow) =>
    r.unit_type === 'million_requests' && r.metadata.requests != null
        ? `${r.metadata.requests.toLocaleString('en-US')} ${r.metadata.requests === 1 ? 'request' : 'requests'}`
        : QUANTITY[r.unit_type]?.(r.quantity) ?? totalQuantity(r.unit_type, r.quantity);

function forOf(snap: UsageSnapshot, r: UsageRow): { thing: string; thingKind: ConsumerKind } {
    const c = consumerOfCached(snap, r);
    return { thing: c.label, thingKind: consumerKind(c.id) };
}

/** The text a search matches a group or a charge by. */
export function searchText(snap: UsageSnapshot, r: UsageRow): string {
    const actual = r.metadata.actual_user_id;
    return `${getDisplayName(r.usage_subtype)} ${forOf(snap, r).thing} ${actual ? thingLabel(snap, 'person', actual) : ''} ${SERVICES[rowOf(r).service].label} ${r.usage_subtype} ${facetOf(snap, r).label}`.toLowerCase();
}

/** What narrows the charges table: a drill, a service, a search, a day. */
export interface ChargeFilter {
    match?: ((r: UsageRow) => boolean) | null;
    service?: ServiceId | null;
    query?: string;
    day?: string | null;
}

/** The groups a filter keeps, as the query the charges are read by, and what they come to each day. */
export function chargeQuery(view: UsageView, filter: ChargeFilter): { query: ChargesQuery; total: number; count: number; byDay: Map<string, { usd: number; count: number }>; services: ServiceId[] } {
    const q = filter.query?.trim().toLowerCase();
    const scoped = metered(view.snap).filter((r) => r.current && (!filter.match || filter.match(r)));
    const services = (Object.keys(SERVICES) as ServiceId[]).filter((s) => scoped.some((r) => rowOf(r).service === s));
    const kept = scoped.filter((r) => (!filter.service || rowOf(r).service === filter.service) && (!q || searchText(view.snap, r).includes(q)));
    const byDay = new Map<string, { usd: number; count: number }>();
    for (const r of kept) {
        if (filter.day && r.day !== filter.day) continue;
        const d = byDay.get(r.day) ?? { usd: 0, count: 0 };
        d.usd += r.total_cost;
        d.count += r.n;
        byDay.set(r.day, d);
    }
    const narrowed = !!(filter.match || filter.service || q);
    return {
        query: { keys: narrowed ? [...new Set(kept.map((r) => r.k))] : null, day: filter.day ?? null },
        total: sum([...byDay.values()].map((d) => d.usd)),
        count: sum([...byDay.values()].map((d) => d.count)),
        byDay,
        services,
    };
}

/** The lines one hourly reading of a site's hosting records together (what it served, and what it keeps). */
const READING = new Set(['apps/hosting', 'apps/releases', 'apps/hostnames', 'apps/build_outputs', 'apps/build_cache']);

/** A site's hourly reading, recorded as up to five charges in the same second, as one line ("Site hosting", an hour)
 *  with its charges as its parts; everything else as it came. Lines of one reading fold wherever paging put them. */
export function foldReadings(items: LineItem[]): LineItem[] {
    const out: LineItem[] = [];
    const readings = new Map<string, number>();
    for (const item of items) {
        const m = item.row.metadata;
        const key = READING.has(item.row.usage_subtype) && m.project_id && m.from ? `${m.project_id}|${m.from}` : null;
        const at = key ? readings.get(key) : undefined;
        if (key == null || at === undefined) {
            if (key) readings.set(key, out.length);
            out.push(item);
            continue;
        }
        const first = out[at];
        const parts = [...(first.parts ?? [first]), item];
        const sum = (f: (p: LineItem) => number) => parts.reduce((a, p) => a + f(p), 0);
        const split = { included: sum((p) => p.split.included), balance: sum((p) => p.split.balance), topup: sum((p) => p.split.topup) };
        const paying = [split.included > 1e-9, split.balance > 1e-9, split.topup > 1e-9].filter(Boolean).length;
        const hours = m.from && m.to ? Math.max(1, Math.round((Date.parse(m.to) - Date.parse(m.from)) / 3_600_000)) : 1;
        out[at] = {
            ...first,
            id: `reading:${key}`,
            what: 'Site hosting',
            detail: m.from && m.to ? `${timeLabel(m.from)} to ${timeLabel(m.to)}` : null,
            quantity: hours === 1 ? 'an hour' : `${hours} hours`,
            usd: sum((p) => p.usd),
            paidFrom: first.paidFrom == null ? null : paying > 1 ? 'Split' : split.balance > 1e-9 ? 'Balance' : split.topup > 1e-9 ? 'Top-up' : 'Included',
            split,
            parts,
        };
    }
    return out;
}

// A charge's line is the same however the table is filtered, so it's built once.
const LINE = new WeakMap<ChargeRow, LineItem>();
export function lineItem(snap: UsageSnapshot, r: ChargeRow): LineItem {
    let item = LINE.get(r);
    if (!item) {
        item = buildLineItem(snap, r);
        LINE.set(r, item);
    }
    return item;
}

function buildLineItem(snap: UsageSnapshot, r: ChargeRow): LineItem {
    const m = r.metadata;
    const split = { included: includedShare(r), balance: r.balance_paid ?? 0, topup: r.topup_paid ?? 0 };
    const parts = [split.included > 1e-9, split.balance > 1e-9, split.topup > 1e-9].filter(Boolean).length;
    const actual = m.actual_user_id && m.actual_user_id !== r.user_id ? m.actual_user_id : null;
    return {
        id: r.id,
        at: r.created_at,
        what: getDisplayName(r.usage_subtype),
        detail: m.prompt_tokens != null ? `${compact(m.prompt_tokens)} in · ${compact(m.completion_tokens ?? 0)} out` : m.minutes != null ? `${m.minutes} min` : null,
        service: rowOf(r).service,
        ...forOf(snap, r),
        runner: actual ? thingLabel(snap, 'person', actual) : null,
        quantity: quantityLabel(r),
        usd: r.total_cost,
        paidFrom: !snap.billing || r.user_resource ? null : parts > 1 ? 'Split' : split.balance > 1e-9 ? 'Balance' : split.topup > 1e-9 ? 'Top-up' : 'Included',
        split,
        row: r,
    };
}
