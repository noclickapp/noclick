// Synthetic accounts for the usage page's tests, built the way billing builds them: usage rows drawn at a seeded random pace,
// then charged in time order against the plan's pools exactly as the tracker does (included usage first, Free's day
// inside its month, the old plans' top-up pool, then the dollar balance, with auto top-up refilling it). A row that
// would find no money is never recorded, as the gate refuses it. Fixed clock; nothing here is a real account.
import { DAY_MS, dayKey } from '@/screens/usage/derive';
import type { AutoTopUpState, ChargeRow, ChargesPage, ChargesSource, UsageGroup, UsageSnapshot as PageSnapshot } from '@/screens/usage/types';
import type { BalanceEntryRow, BalanceRechargeRow, Directory, PlanState, UnitType, UsageEventMetadata, UsageEventRow, UsageSnapshot, UsageType } from './fixtureTypes';

/** The fixtures' clock: a Friday afternoon, UTC. */
export const NOW = '2026-10-16T15:20:00Z';
const NOW_T = Date.parse(NOW);

function rng(seed: number) {
    let a = seed >>> 0;
    return () => {
        a = (a + 0x6d2b79f5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

const iso = (t: number) => new Date(t).toISOString();
const at = (day: string, h: number, m = 0) => Date.parse(`${day}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00Z`);

interface Source {
    /** Mean events a day on an active day. */
    perDay: number;
    /** UTC weekdays it runs (0 = Sunday); every day when absent. */
    weekdays?: number[];
    from?: string;
    to?: string;
    /** UTC hours it runs between. */
    hours?: [number, number];
    /** Vendor cost of one event, drawn log-uniformly. */
    cost: [number, number];
    usage_type: UsageType;
    subtype: string | ((r: () => number) => string);
    unit: UnitType;
    /** Quantity for a cost. */
    quantity: (cost: number, r: () => number) => number;
    meta: UsageEventMetadata;
    /** A spike: multiply this day's events. */
    surge?: Record<string, number>;
}

interface Fixed {
    t: number;
    cost: number;
    usage_type: UsageType;
    subtype: string;
    unit: UnitType;
    quantity: number;
    meta: UsageEventMetadata;
    /** Charged even when no pool covers it (a renewal, a call in progress): the balance can go below zero. */
    force?: boolean;
}

interface Build {
    seed: number;
    payer: string;
    org: string | null;
    plan: PlanState;
    /** The first day rows exist. */
    since: string;
    sources: Source[];
    fixed: Fixed[];
    deposits: { t: number; usd: number; source?: string }[];
    autoTopUp: AutoTopUpState | null;
    /** From this moment auto top-up's charges are declined. */
    autoFailsFrom?: number;
}

const MODEL_TOKENS = (cost: number, r: () => number) => Math.round((cost / 0.000009) * (0.8 + 0.4 * r()));

/** What a row's writer records beside it: a model call's tokens in and out, a call's sid, the run it belongs to (runs
 *  of an automation fire every few hours here, so neighbouring rows share one). */
/** What a row's writer records beside it, as the real writers do (checked against user_usage_events, 2026-10-16):
 *  a model call its model and tokens but no agent node or run (coder/openai_agent/billing.py:344); sandbox time its
 *  agent node and minutes (cloud/billing/sandbox_billing.py:420); a call its sid and channel but not its number or
 *  automation (cloud/voice/internal_routes.py:375); an agent's email update its run (utils/agent_email.py:495). */
function enrich(meta: UsageEventMetadata, type: UsageType, subtype: string, quantity: number, time: number, r: () => number): UsageEventMetadata {
    const out: UsageEventMetadata = { ...meta };
    if (type === 'ai_usage' || type === 'ai_builder' || type === 'ai_testing') {
        const prompt = Math.round(quantity * (0.72 + 0.2 * r()));
        delete out.node_id;
        // The builder's rows rarely know the workflow they built (2% in the 14 days checked).
        if (type === 'ai_builder') delete out.workflow_id;
        Object.assign(out, { model: subtype, prompt_tokens: prompt, completion_tokens: Math.max(0, quantity - prompt) });
    }
    if (type === 'cpu_usage') Object.assign(out, { minutes: Math.round((quantity / 60) * 10) / 10 });
    if (subtype === 'voice/call') {
        delete out.workflow_id;
        delete out.node_id;
        Object.assign(out, { call_sid: `CA${Math.floor(r() * 0xffffffff).toString(16).padStart(8, '0')}`, channel: meta.channel ?? 'number', verified_by: meta.channel ?? 'number', minutes: Math.round((quantity / 60) * 10) / 10 });
    }
    if (subtype === 'email/agent_update' && meta.workflow_id) {
        const block = Math.floor(time / (3 * 3_600_000));
        out.execution_id = `run_${meta.workflow_id.slice(3, 9)}_${block.toString(36)}`;
    }
    return out;
}

type Draft = Omit<UsageEventRow, 'total_cost' | 'topup_paid' | 'balance_paid' | 'fee_usd' | 'user_id' | 'organization_id'> & { force?: boolean };

function draw(b: Build): Draft[] {
    const r = rng(b.seed);
    const out: Draft[] = [];
    let n = 0;
    for (let t = Date.parse(`${b.since}T00:00:00Z`); t <= NOW_T; t += DAY_MS) {
        const k = dayKey(t);
        const wd = new Date(t).getUTCDay();
        for (const s of b.sources) {
            if (s.weekdays && !s.weekdays.includes(wd)) continue;
            if ((s.from && k < s.from) || (s.to && k > s.to)) continue;
            const mean = s.perDay * (s.surge?.[k] ?? 1);
            // Poisson by inversion: whole events, a pace that wanders day to day.
            let count = 0;
            const L = Math.exp(-mean);
            for (let p = r(); p > L && count < 400; p *= r()) count += 1;
            for (let i = 0; i < count; i++) {
                const [h0, h1] = s.hours ?? [7, 23];
                const time = t + (h0 + r() * (h1 - h0)) * 3_600_000;
                if (time > NOW_T) continue;
                const cost = s.cost[0] * Math.pow(s.cost[1] / s.cost[0], r());
                const subtype = typeof s.subtype === 'string' ? s.subtype : s.subtype(r);
                const quantity = s.quantity(cost, r);
                out.push({
                    id: `ev_${b.seed}_${n++}`,
                    created_at: iso(time),
                    usage_type: s.usage_type,
                    usage_subtype: subtype,
                    quantity,
                    unit_type: s.unit,
                    cost_usd: cost,
                    user_resource: false,
                    metadata: enrich(s.meta, s.usage_type, subtype, quantity, time, rng(b.seed * 7919 + n)),
                });
            }
        }
    }
    for (const f of b.fixed) {
        if (f.t > NOW_T) continue;
        out.push({ id: `ev_${b.seed}_${n++}`, created_at: iso(f.t), usage_type: f.usage_type, usage_subtype: f.subtype, quantity: f.quantity, unit_type: f.unit, cost_usd: f.cost, user_resource: false, metadata: enrich(f.meta, f.usage_type, f.subtype, f.quantity, f.t, rng(b.seed * 7919 + n)), force: f.force });
    }
    return out.sort((x, y) => Date.parse(x.created_at) - Date.parse(y.created_at));
}

/** Month windows: Free's UTC calendar month, a subscription's anchored month (plan_limits.monthly_window_start). */
function windowStartFor(t: number, plan: PlanState): number {
    const anchor = new Date(plan.window_start);
    const d = new Date(t);
    const day = plan.tier === 'free' ? 1 : anchor.getUTCDate();
    let s = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), day, plan.tier === 'free' ? 0 : anchor.getUTCHours());
    if (s > t) s = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 1, day, plan.tier === 'free' ? 0 : anchor.getUTCHours());
    return s;
}

function charge(b: Build) {
    const rows = draw(b);
    const legacy = b.plan.billing_model === 'legacy';
    const events: UsageEventRow[] = [];
    const entries: BalanceEntryRow[] = [];
    const recharges: BalanceRechargeRow[] = [];
    const deposits = [...b.deposits].sort((x, y) => x.t - y.t);
    let balance = 0;
    let hasBalance = false;
    let windowKey = -1;
    let monthUsed = 0;
    let topupUsed = 0;
    let dayKeyNow = '';
    let dayUsed = 0;
    let autoMonthKey = '';
    let autoMonth = 0;
    const autoDay = new Map<string, number>();
    const fee = b.plan.fee_rate ?? 0;
    const deposit = (t: number, usd: number, source: string) => {
        entries.push({ id: `be_${entries.length}`, user_id: b.payer, kind: 'deposit', usd, fee_usd: Math.round(usd * fee * 100) / 100, currency: 'usd', source, created_at: iso(t) });
        balance += usd;
        hasBalance = true;
    };
    const auto = b.autoTopUp;
    const maybeTopUp = (t: number) => {
        if (!auto?.enabled || balance >= auto.thresholdUsd) return;
        const mk = dayKey(t).slice(0, 7);
        if (mk !== autoMonthKey) {
            autoMonthKey = mk;
            autoMonth = 0;
        }
        const dk = dayKey(t);
        if ((autoDay.get(dk) ?? 0) >= 3 || autoMonth + auto.amountUsd > auto.monthlyCapUsd) return;
        if (b.autoFailsFrom && t >= b.autoFailsFrom) {
            if (!recharges.some((x) => x.status === 'failed')) {
                recharges.push({ id: `rc_${recharges.length}`, status: 'failed', amount_usd: auto.amountUsd, fee_usd: Math.round(auto.amountUsd * fee * 100) / 100, attempt: 4, failure: 'Your card was declined.', created_at: iso(t), settled_at: null });
            }
            return;
        }
        autoDay.set(dk, (autoDay.get(dk) ?? 0) + 1);
        autoMonth += auto.amountUsd;
        recharges.push({ id: `rc_${recharges.length}`, status: 'succeeded', amount_usd: auto.amountUsd, fee_usd: Math.round(auto.amountUsd * fee * 100) / 100, attempt: 1, failure: null, created_at: iso(t), settled_at: iso(t + 90_000) });
        deposit(t + 90_000, auto.amountUsd, 'auto_topup');
    };
    for (const row of rows) {
        const t = Date.parse(row.created_at);
        while (deposits.length && deposits[0].t <= t) {
            const d = deposits.shift()!;
            deposit(d.t, d.usd, d.source ?? 'checkout');
        }
        const ws = windowStartFor(t, b.plan);
        if (ws !== windowKey) {
            windowKey = ws;
            monthUsed = 0;
            topupUsed = 0;
        }
        const dk = dayKey(t);
        if (dk !== dayKeyNow) {
            dayKeyNow = dk;
            dayUsed = 0;
        }
        const price = legacy ? row.cost_usd! * 3 : row.cost_usd!;
        const monthLeft = Math.max(0, b.plan.included_usd - monthUsed);
        const avail = b.plan.daily_usd != null ? Math.min(monthLeft, Math.max(0, b.plan.daily_usd - dayUsed)) : monthLeft;
        const topupLeft = Math.max(0, b.plan.topup_usd - topupUsed);
        // The gate: nothing included, no top-up pool and nothing in the balance refuses new work.
        if (!row.force && avail <= 1e-9 && topupLeft <= 1e-9 && (!hasBalance || balance <= 0)) continue;
        const inc = Math.min(price, avail);
        let rest = price - inc;
        const top = Math.min(rest, topupLeft);
        rest -= top;
        if (rest > 1e-9 && !hasBalance && !row.force) continue;
        monthUsed += inc;
        dayUsed += inc;
        topupUsed += top;
        balance -= rest;
        const { force: _force, ...clean } = row;
        void _force;
        events.push({ ...clean, user_id: b.payer, organization_id: b.org, total_cost: price, fee_usd: legacy ? null : 0, topup_paid: top, balance_paid: rest, cost_usd: row.cost_usd });
        if (rest > 0) maybeTopUp(t);
    }
    while (deposits.length && deposits[0].t <= NOW_T) {
        const d = deposits.shift()!;
        deposit(d.t, d.usd, d.source ?? 'checkout');
    }
    return { events, entries, recharges, autoMonth };
}

// ── shared pieces ────────────────────────────────────────────────────────────

const ai = (meta: UsageEventMetadata, perDay: number, cost: [number, number], models: string[], extra: Partial<Source> = {}): Source => ({
    perDay,
    cost,
    usage_type: 'ai_usage',
    subtype: (r) => models[Math.floor(r() * models.length)],
    unit: 'tokens',
    quantity: MODEL_TOKENS,
    meta,
    ...extra,
});
const sandbox = (meta: UsageEventMetadata, perDay: number, cost: [number, number], extra: Partial<Source> = {}): Source => ({
    perDay,
    cost,
    usage_type: 'cpu_usage',
    subtype: 'agent/sandbox',
    unit: 'seconds',
    // At cost a sandbox minute is about $0.0042.
    quantity: (c) => Math.round((c / 0.0042) * 60),
    meta: { ...meta, label: 'Sandbox time' },
    ...extra,
});
const api = (meta: UsageEventMetadata, perDay: number, cost: [number, number], subtype: string, label: string, unit: UnitType = 'requests', extra: Partial<Source> = {}): Source => ({
    perDay,
    cost,
    usage_type: 'api_usage',
    subtype,
    unit,
    // Rows read at a dollar a million; everything else counts requests.
    quantity: unit === 'rows' ? (c) => Math.round(c / 0.000001) : () => 1,
    meta: { ...meta, label },
    ...extra,
});
const calls = (meta: UsageEventMetadata, perDay: number, extra: Partial<Source> = {}): Source => ({
    perDay,
    cost: [0.08, 0.9],
    usage_type: 'api_usage',
    subtype: 'voice/call',
    unit: 'seconds',
    // A live call costs about $0.075 a minute at cost (carrier and voice model).
    quantity: (c) => Math.round((c / 0.075) * 60),
    meta: { ...meta, label: 'Call' },
    hours: [14, 23],
    ...extra,
});

// Model calls are billed under the model as the agent named it: through OpenRouter, so the subtype carries its route.
const SONNET = 'openrouter/anthropic/claude-sonnet-4.6';
const GPT = 'openrouter/openai/gpt-5.5';
const GPT_MINI = 'openrouter/openai/gpt-4o-mini';
const FLASH = 'openrouter/google/gemini-3.8-flash';
const WEEKDAYS = [1, 2, 3, 4, 5];

function daily(from: string, to: string, hour: number, f: (day: string) => Omit<Fixed, 't'> | null): Fixed[] {
    const out: Fixed[] = [];
    for (let t = Date.parse(`${from}T00:00:00Z`); dayKey(t) <= to; t += DAY_MS) {
        const x = f(dayKey(t));
        if (x) out.push({ ...x, t: t + hour * 3_600_000 });
    }
    return out;
}

function hourly(from: string, usd: number, credential: string): Fixed[] {
    const out: Fixed[] = [];
    for (let t = Date.parse(from); t <= NOW_T; t += 3_600_000) out.push({ t, cost: usd, usage_type: 'recurring', subtype: 'whatsapp_connection', unit: 'hour', quantity: 1, meta: { credential_id: credential, label: 'WhatsApp connection, an hour' }, force: true });
    return out;
}

function numberMonths(first: string, label: string, credential: string, months: number, usd = 1): Fixed[] {
    const out: Fixed[] = [{ t: Date.parse(first), cost: 1, usage_type: 'recurring', subtype: 'phone_number_setup', unit: 'month', quantity: 1, meta: { credential_id: credential, label: `${label}, set up` }, force: true }];
    for (let i = 0; i < months; i++) {
        const t = Date.parse(first) + i * 30 * DAY_MS;
        out.push({ t, cost: usd, usage_type: 'recurring', subtype: 'phone_number', unit: 'month', quantity: 1, meta: { credential_id: credential, charge_id: `rc_${credential}`, paid_through: iso(t + 30 * DAY_MS), label: `${label}, a month` }, force: true });
    }
    return out;
}

function snapshot(b: Build, rest: Omit<UsageSnapshot, 'now' | 'events' | 'balanceEntries' | 'recharges' | 'autoTopUp' | 'plan'>): UsageSnapshot {
    const { events, entries, recharges, autoMonth } = charge(b);
    return {
        now: NOW,
        plan: b.plan,
        events,
        balanceEntries: entries,
        recharges,
        autoTopUp: b.autoTopUp ? { ...b.autoTopUp, monthUsd: autoMonth, pausedReason: b.autoFailsFrom ? 'declined' : b.autoTopUp.pausedReason } : null,
        ...rest,
    };
}

const autoTopUp = (thresholdUsd: number, amountUsd: number, monthlyCapUsd: number, enabled = true): AutoTopUpState => ({
    enabled,
    thresholdUsd,
    amountUsd,
    monthlyCapUsd,
    pausedReason: null,
    methodLabel: 'Visa ending 4242',
    hasMethod: true,
    currency: 'usd',
    monthUsd: 0,
});

const emptyDirectory = (): Directory => ({ workflows: {}, agents: {}, projects: {}, people: {}, keys: {} });

// ── the scenarios ────────────────────────────────────────────────────────────

function freeNew(): UsageSnapshot {
    const you = 'u_ines';
    const wf = { digest: 'wf_digest' };
    const plan: PlanState = { billing_model: 'free_member', tier: 'free', window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', included_usd: 5, daily_usd: 1, fee_rate: 0.15, plan_price_usd: 0, topup_usd: 0 };
    const b: Build = {
        seed: 11,
        payer: you,
        org: null,
        plan,
        since: '2026-10-11',
        sources: [
            ai({}, 9, [0.004, 0.06], [SONNET], { hours: [8, 22] }),
            ai({ workflow_id: wf.digest, node_id: 'agent' }, 2, [0.01, 0.04], [GPT_MINI], { from: '2026-10-13', hours: [7, 8] }),
            api({ workflow_id: wf.digest, node_id: 'search' }, 3, [0.004, 0.006], 'exa/search_api', 'Web search', 'requests', { from: '2026-10-13', hours: [7, 8] }),
            { perDay: 40, cost: [0.012, 0.08], usage_type: 'ai_builder', subtype: 'noclick/builder-1', unit: 'tokens', quantity: MODEL_TOKENS, meta: { workflow_id: wf.digest, label: 'Building the automation' }, from: '2026-10-12', to: '2026-10-12', hours: [19, 22] },
        ],
        fixed: [],
        deposits: [],
        // Off with nothing saved, as the backend reads it for an account in the rollout that never added funds.
        autoTopUp: { ...autoTopUp(5, 25, 250, false), methodLabel: null, hasMethod: false, currency: null },
    };
    return snapshot(b, {
        account: { id: you, name: 'Inès Moreau', email: 'ines@example.com' },
        workspace: { name: 'Inès Moreau', personal: true, members: 1 },
        viewerIsOwner: true,
        recurring: [],
        domains: [],
        caps: [],
        directory: { ...emptyDirectory(), workflows: { [wf.digest]: { name: 'Morning news digest' } }, agents: { [`${wf.digest}:agent`]: { name: 'Digest writer' }, __coordinator__: { name: 'NoClick (chat)' } }, people: { [you]: { name: 'Inès Moreau', you: true } } },
    });
}

function memberBusy(seed = 22, opts: { org?: boolean } = {}): UsageSnapshot {
    const you = 'u_priya';
    const people = opts.org ? ['u_priya', 'u_sam', 'u_lena', 'u_theo'] : undefined;
    const wf = { support: 'wf_support', desk: 'wf_desk', leads: 'wf_leads', investor: 'wf_investor', site: 'wf_site' };
    const proj = 'prj_site';
    const db = 'db_site';
    const plan: PlanState = { billing_model: 'free_member', tier: 'member', window_start: '2026-10-03T09:12:00Z', window_end: '2026-11-03T09:12:00Z', included_usd: 10, daily_usd: null, fee_rate: 0.05, plan_price_usd: 25, topup_usd: 0 };
    const supportMeta = { workflow_id: wf.support, node_id: 'agent' };
    const deskMeta = { workflow_id: wf.desk, node_id: 'receptionist' };
    const leadsMeta = { workflow_id: wf.leads, node_id: 'researcher' };
    const runnerOf = (p: string) => (people ? { actual_user_id: p } : {});
    const b: Build = {
        seed,
        payer: you,
        org: opts.org ? 'org_halden' : null,
        plan,
        since: '2026-09-03',
        sources: [
            ai({ ...runnerOf('u_priya') }, 16, [0.004, 0.09], [SONNET], { hours: [7, 23] }),
            ai({ ...supportMeta, ...runnerOf('u_lena') }, 26, [0.01, 0.11], [SONNET], { surge: { '2026-10-13': 2.6 } }),
            sandbox({ ...supportMeta, ...runnerOf('u_lena') }, 14, [0.02, 0.09], { surge: { '2026-10-13': 2.4 } }),
            api({ workflow_id: wf.support, from: 'fernway-support@noclick.email', ...runnerOf('u_lena') }, 9, [0.0009, 0.0009], 'email/agent_reply', 'Email reply'),
            calls({ ...deskMeta, ...runnerOf('u_sam') }, 6, { weekdays: [1, 2, 3, 4, 5, 6], from: '2026-09-21' }),
            ai({ ...deskMeta, ...runnerOf('u_sam') }, 10, [0.004, 0.03], [FLASH], { from: '2026-09-21', hours: [14, 23] }),
            ai({ ...leadsMeta, ...runnerOf('u_theo') }, 12, [0.01, 0.08], [GPT], { weekdays: WEEKDAYS, hours: [13, 18] }),
            api({ ...leadsMeta, ...runnerOf('u_theo') }, 18, [0.005, 0.005], 'exa/search_api', 'Web search', 'requests', { weekdays: WEEKDAYS, hours: [13, 18] }),
            api({ ...leadsMeta, ...runnerOf('u_theo') }, 7, [0.012, 0.03], 'linkedin/scrape_profile', 'LinkedIn profile', 'requests', { weekdays: WEEKDAYS, hours: [13, 18] }),
            ai({ workflow_id: wf.investor, node_id: 'writer', ...runnerOf('u_priya') }, 8, [0.03, 0.12], [GPT], { weekdays: [1], hours: [9, 10] }),
            api({ database_id: db }, 30, [0.0002, 0.0015], 'database/rows_read', 'Database reads', 'rows'),
            api({ project_id: proj }, 3, [0.0009, 0.0009], 'email/platform_app', 'Order confirmation email'),
            api({ workflow_id: wf.investor, node_id: 'writer', ...runnerOf('u_priya') }, 1, [0.0009, 0.0009], 'email/agent_update', 'Email update', 'requests', { weekdays: [1], hours: [10, 11] }),
            // What NoClick itself sends and takes on its own lines: WhatsApp templates, and calls with the coordinator.
            api({}, 1.6, [0.0034, 0.0034], 'whatsapp/utility', 'WhatsApp message from NoClick'),
            calls({ channel: 'whatsapp' }, 0.35, { hours: [15, 22] }),
        ],
        fixed: [
            ...numberMonths('2026-09-21T16:04:00Z', '+1 415 555 0132', 'cred_desk', 2),
            ...daily('2026-09-03', '2026-10-16', 2, () => ({ cost: 0.034, usage_type: 'api_usage', subtype: 'apps/hosting', unit: 'gb_hours', quantity: 4.1, meta: { project_id: proj, label: 'Hosting, a day' } })),
            ...daily('2026-09-03', '2026-10-16', 3, () => ({ cost: 0.006, usage_type: 'api_usage', subtype: 'database/storage', unit: 'mb', quantity: 212, meta: { database_id: db, label: 'Database storage, a day' } })),
            ...['2026-09-09', '2026-09-24', '2026-10-06', '2026-10-14'].map((d) => ({ t: at(d, 17, 40), cost: 0.21, usage_type: 'api_usage' as const, subtype: 'apps/build', unit: 'seconds' as const, quantity: 94, meta: { project_id: proj, label: 'Build and deploy' } })),
            // A WhatsApp connection bills by the hour (cloud/billing/recurring.py:39).
            ...hourly('2026-09-12T08:00:00Z', 0.99 / 720, 'cred_wa'),
        ],
        deposits: [
            { t: at('2026-09-03', 9, 30), usd: 100 },
            { t: at('2026-09-29', 18, 2), usd: 50 },
        ],
        autoTopUp: autoTopUp(20, 50, 200),
    };
    const directory: Directory = {
        workflows: { [wf.support]: { name: 'Support inbox' }, [wf.desk]: { name: 'Front desk line' }, [wf.leads]: { name: 'Lead research' }, [wf.investor]: { name: 'Weekly investor update' }, [wf.site]: { name: 'Fernway shop' } },
        agents: { [`${wf.support}:agent`]: { name: 'Support agent' }, [`${wf.desk}:receptionist`]: { name: 'Receptionist' }, [`${wf.leads}:researcher`]: { name: 'Researcher' }, [`${wf.investor}:writer`]: { name: 'Update writer' }, __coordinator__: { name: 'NoClick (chat)' } },
        projects: { [proj]: { name: 'fernway.studio' } },
        databases: { [db]: { name: 'fernway-orders' } },
        people: opts.org ? { u_priya: { name: 'Priya Shah', you: true }, u_sam: { name: 'Sam Ortiz' }, u_lena: { name: 'Lena Park' }, u_theo: { name: 'Theo Grant' } } : { [you]: { name: 'Priya Shah', you: true } },
        keys: {},
    };
    return snapshot(b, {
        account: { id: you, name: 'Priya Shah', email: 'priya@fernway.studio' },
        workspace: opts.org ? { name: 'Halden & Co', personal: false, members: 4 } : { name: 'Priya Shah', personal: true, members: 1 },
        viewerIsOwner: true,
        recurring: [
            { id: 'rc_cred_desk', credential_id: 'cred_desk', charge_type: 'phone_number', hourly_amount: null, period_amount: 1, paid_through: '2026-10-21T16:04:00Z', over_cap_since: null, created_at: '2026-09-21T16:04:00Z', label: '+1 415 555 0132' },
            { id: 'rc_cred_wa', credential_id: 'cred_wa', charge_type: 'whatsapp_connection', hourly_amount: 0.99 / 720, period_amount: null, paid_through: null, over_cap_since: null, created_at: '2026-09-12T08:00:00Z', label: '+44 7700 900123' },
        ],
        domains: [{ id: 'dom_fernway', name: 'fernway.studio', renewal_usd: 25.99, renewal_years: 1, expires_at: '2026-11-01T11:00:00Z', auto_renew: true }],
        caps: opts.org ? [{ scope: 'workspace', id: 'org_halden', name: 'Halden & Co', cap_usd: 400, spent_usd: 0 }] : [],
        directory,
    });
}

function runningOut(): UsageSnapshot {
    const you = 'u_marco';
    const wf = { repo: 'wf_repo', inbox: 'wf_triage' };
    const plan: PlanState = { billing_model: 'free_member', tier: 'free', window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', included_usd: 5, daily_usd: 1, fee_rate: 0.15, plan_price_usd: 0, topup_usd: 0 };
    const repo = { workflow_id: wf.repo, node_id: 'maintainer' };
    const b: Build = {
        seed: 33,
        payer: you,
        org: null,
        plan,
        since: '2026-09-20',
        sources: [
            ai(repo, 22, [0.01, 0.13], [GPT], { from: '2026-10-05' }),
            sandbox(repo, 21, [0.04, 0.16], { from: '2026-10-05' }),
            ai({ workflow_id: wf.inbox, node_id: 'triage' }, 6, [0.002, 0.012], [GPT_MINI]),
            ai({}, 5, [0.004, 0.05], [SONNET]),
        ],
        fixed: [],
        deposits: [
            { t: at('2026-09-28', 10, 5), usd: 10 },
            { t: at('2026-10-09', 21, 40), usd: 22 },
        ],
        autoTopUp: autoTopUp(5, 25, 250, false),
    };
    return snapshot(b, {
        account: { id: you, name: 'Marco Bellini', email: 'marco@example.com' },
        workspace: { name: 'Marco Bellini', personal: true, members: 1 },
        viewerIsOwner: true,
        recurring: [],
        domains: [],
        caps: [],
        directory: { ...emptyDirectory(), workflows: { [wf.repo]: { name: 'Repo maintainer' }, [wf.inbox]: { name: 'Inbox triage' } }, agents: { [`${wf.repo}:maintainer`]: { name: 'Maintainer (Codex)' }, [`${wf.inbox}:triage`]: { name: 'Triage' }, __coordinator__: { name: 'NoClick (chat)' } }, people: { [you]: { name: 'Marco Bellini', you: true } } },
    });
}

function inDebt(): UsageSnapshot {
    const you = 'u_ada';
    const wf = { calls: 'wf_callback', notes: 'wf_notes' };
    const plan: PlanState = { billing_model: 'free_member', tier: 'member', window_start: '2026-10-07T12:00:00Z', window_end: '2026-11-07T12:00:00Z', included_usd: 10, daily_usd: null, fee_rate: 0.05, plan_price_usd: 25, topup_usd: 0 };
    const callMeta = { workflow_id: wf.calls, node_id: 'caller' };
    const b: Build = {
        seed: 44,
        payer: you,
        org: null,
        plan,
        since: '2026-09-07',
        sources: [
            calls(callMeta, 11, { surge: { '2026-10-13': 1.6, '2026-10-14': 2.2, '2026-10-15': 2.4 } }),
            ai(callMeta, 14, [0.004, 0.03], [FLASH]),
            ai({ workflow_id: wf.notes, node_id: 'writer' }, 8, [0.01, 0.06], [SONNET]),
            ai({}, 6, [0.004, 0.05], [SONNET]),
        ],
        fixed: [
            ...numberMonths('2026-09-15T10:00:00Z', '+1 312 555 0187', 'cred_cb', 2),
            // A long call already under way when the balance hit zero: in-flight work finishes and the balance owes it.
            { t: at('2026-10-15', 18, 52), cost: 9.4, usage_type: 'api_usage', subtype: 'voice/call', unit: 'seconds', quantity: 7520, meta: { ...callMeta, label: 'Call, already under way' }, force: true },
        ],
        deposits: [{ t: at('2026-09-07', 12, 30), usd: 60 }],
        autoTopUp: autoTopUp(10, 25, 150),
        autoFailsFrom: at('2026-10-13', 0),
    };
    return snapshot(b, {
        account: { id: you, name: 'Ada Okafor', email: 'ada@example.com' },
        workspace: { name: 'Ada Okafor', personal: true, members: 1 },
        viewerIsOwner: true,
        recurring: [{ id: 'rc_cred_cb', credential_id: 'cred_cb', charge_type: 'phone_number', hourly_amount: null, period_amount: 1, paid_through: '2026-11-14T10:00:00Z', over_cap_since: '2026-10-15T19:00:00Z', created_at: '2026-09-15T10:00:00Z', label: '+1 312 555 0187' }],
        domains: [],
        caps: [],
        directory: { ...emptyDirectory(), workflows: { [wf.calls]: { name: 'Callback line' }, [wf.notes]: { name: 'Call notes' } }, agents: { [`${wf.calls}:caller`]: { name: 'Caller' }, [`${wf.notes}:writer`]: { name: 'Notes writer' }, __coordinator__: { name: 'NoClick (chat)' } }, people: { [you]: { name: 'Ada Okafor', you: true } } },
    });
}

function workspace(): UsageSnapshot {
    const s = memberBusy(55, { org: true });
    return s;
}

function legacyPro(): UsageSnapshot {
    const you = 'u_jonas';
    const wf = { social: 'wf_social', crm: 'wf_crm' };
    // Pro on the old plan: 100 credits a month (= $25 of usage at the old prices), a 20-credit monthly add-on, prices
    // at 3× the vendor's cost, no balance and no fee (cloud/billing/plan_limits.py:34-73).
    const plan: PlanState = { billing_model: 'legacy', tier: 'pro', window_start: '2026-10-05T08:00:00Z', window_end: '2026-11-05T08:00:00Z', included_usd: 25, daily_usd: null, fee_rate: null, plan_price_usd: 50, topup_usd: 5 };
    const b: Build = {
        seed: 66,
        payer: you,
        org: null,
        plan,
        since: '2026-09-05',
        sources: [
            ai({ workflow_id: wf.social, node_id: 'writer' }, 12, [0.01, 0.08], [SONNET]),
            api({ workflow_id: wf.social, node_id: 'scrape' }, 6, [0.01, 0.025], 'instagram/scrape_posts', 'Instagram posts'),
            ai({ workflow_id: wf.crm, node_id: 'agent' }, 9, [0.004, 0.04], [GPT_MINI]),
            ai({}, 6, [0.004, 0.05], [SONNET]),
        ],
        fixed: [],
        deposits: [],
        autoTopUp: null,
    };
    return snapshot(b, {
        account: { id: you, name: 'Jonas Weber', email: 'jonas@example.com' },
        workspace: { name: 'Jonas Weber', personal: true, members: 1 },
        viewerIsOwner: true,
        recurring: [],
        domains: [],
        caps: [],
        directory: { ...emptyDirectory(), workflows: { [wf.social]: { name: 'Instagram weekly' }, [wf.crm]: { name: 'CRM follow-ups' } }, agents: { [`${wf.social}:writer`]: { name: 'Post writer' }, [`${wf.crm}:agent`]: { name: 'Follow-up agent' }, __coordinator__: { name: 'NoClick (chat)' } }, people: { [you]: { name: 'Jonas Weber', you: true } } },
    });
}

function platform(): UsageSnapshot {
    const you = 'u_kai';
    const keys = { prod: 'key_prod', staging: 'key_staging' };
    const tenants = ['ten_acme', 'ten_globex', 'ten_umbra', 'ten_initech'];
    const agents = { concierge: 'agt_concierge', scheduler: 'agt_scheduler' };
    const proj = 'prj_portal';
    const plan: PlanState = { billing_model: 'free_member', tier: 'member', window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', included_usd: 10, daily_usd: null, fee_rate: 0.05, plan_price_usd: 25, topup_usd: 0 };
    const sources: Source[] = [];
    tenants.forEach((tenant, i) => {
        const weight = [1, 0.55, 0.3, 0.12][i];
        const pa = (agent: string) => ({ platform_api: { key_id: keys.prod, tenant_id: tenant, agent_id: agent, project_id: proj } });
        sources.push(ai({ ...pa(agents.concierge) }, 30 * weight, [0.004, 0.06], [SONNET, GPT_MINI]));
        sources.push(sandbox({ ...pa(agents.concierge) }, 8 * weight, [0.02, 0.08]));
        sources.push(ai({ ...pa(agents.scheduler) }, 12 * weight, [0.002, 0.02], [FLASH]));
        sources.push(api({ ...pa(agents.scheduler), inbox_id: 'inb_scheduler' }, 10 * weight, [0.0009, 0.0009], 'email/platform_inbox_send', 'Inbox send'));
    });
    sources.push(ai({ platform_api: { key_id: keys.staging, tenant_id: 'ten_test', agent_id: agents.concierge } }, 14, [0.004, 0.05], [SONNET], { weekdays: WEEKDAYS, hours: [9, 19] }));
    for (const [tenant, number, perDay] of [['ten_acme', 'pn_acme', 26], ['ten_globex', 'pn_globex', 11]] as const) {
        const pa = { key_id: keys.prod, tenant_id: tenant, agent_id: agents.scheduler };
        sources.push(api({ platform_api: pa, phone_number_id: number }, perDay, [0.004, 0.0083], 'phone/text_outbound', 'Text sent'));
        sources.push(api({ platform_api: pa, phone_number_id: number }, perDay * 0.6, [0.004, 0.004], 'phone/text_inbound', 'Text received'));
        sources.push(calls({ platform_api: pa, channel: 'number' }, perDay / 9, { hours: [14, 22] }));
    }
    const b: Build = {
        seed: 77,
        payer: you,
        org: null,
        plan,
        since: '2026-09-01',
        sources,
        fixed: daily('2026-09-01', '2026-10-16', 2, () => ({ cost: 0.05, usage_type: 'api_usage', subtype: 'apps/hosting', unit: 'gb_hours', quantity: 6.2, meta: { project_id: proj, platform_api: { key_id: keys.prod, tenant_id: 'self', project_id: proj }, label: 'Hosting, a day' } })),
        deposits: [{ t: at('2026-09-01', 10), usd: 200 }],
        autoTopUp: autoTopUp(50, 100, 500),
    };
    return snapshot(b, {
        account: { id: you, name: 'Kai Lindqvist', email: 'kai@portalworks.dev' },
        workspace: { name: 'Portalworks', personal: true, members: 1 },
        viewerIsOwner: true,
        recurring: [],
        domains: [],
        caps: [
            { scope: 'key', id: keys.staging, name: 'Staging', cap_usd: 25, spent_usd: 0 },
            { scope: 'user', id: 'ten_acme', name: 'Acme', cap_usd: 150, spent_usd: 0 },
            { scope: 'user', id: 'ten_globex', name: 'Globex', cap_usd: 150, spent_usd: 0 },
            { scope: 'agent', id: agents.concierge, name: 'Concierge', cap_usd: 300, spent_usd: 0 },
        ],
        directory: {
            workflows: {},
            agents: { [agents.concierge]: { name: 'Concierge' }, [agents.scheduler]: { name: 'Scheduler' } },
            projects: { [proj]: { name: 'portal-web' } },
            people: { ten_acme: { name: 'Acme' }, ten_globex: { name: 'Globex' }, ten_umbra: { name: 'Umbra Labs' }, ten_initech: { name: 'Initech' }, ten_test: { name: 'test-user' }, u_kai: { name: 'Your account' } },
            numbers: { pn_acme: { name: '+1 628 555 0101' }, pn_globex: { name: '+1 628 555 0177' } },
            inboxes: { inb_scheduler: { name: 'bookings@portalworks.dev' } },
            keys: { [keys.prod]: { name: 'Production' }, [keys.staging]: { name: 'Staging' } },
        },
    });
}

/** Caps read what their scope spent this UTC month (/v1/usage/limits), from the rows. */
function withCapSpend(s: UsageSnapshot): UsageSnapshot {
    const monthStart = Date.parse(`${s.now.slice(0, 7)}-01T00:00:00Z`);
    const rows = s.events.filter((r) => Date.parse(r.created_at) >= monthStart);
    const spentBy = (f: (r: UsageEventRow) => string | undefined, id: string) => rows.filter((r) => f(r) === id).reduce((a, r) => a + r.total_cost, 0);
    return {
        ...s,
        caps: s.caps.map((c) => ({
            ...c,
            spent_usd:
                c.scope === 'key'
                    ? spentBy((r) => r.metadata.platform_api?.key_id, c.id)
                    : c.scope === 'user'
                      ? spentBy((r) => r.metadata.platform_api?.tenant_id, c.id)
                      : c.scope === 'agent'
                        ? spentBy((r) => r.metadata.platform_api?.agent_id, c.id)
                        : c.scope === 'project'
                          ? spentBy((r) => r.metadata.platform_api?.project_id, c.id)
                          : rows.reduce((a, r) => a + r.total_cost, 0),
        })),
    };
}

export interface UsageFixture {
    slug: string;
    name: string;
    premise: string;
    build: () => UsageSnapshot;
    /** The frame this scenario reads best in. */
    console?: boolean;
}

export const USAGE_FIXTURES: UsageFixture[] = [
    { slug: 'member', name: 'Member, mid-month', premise: 'Busy: agents, a phone line, an app and a domain. Auto top-up on.', build: memberBusy },
    { slug: 'free-new', name: 'New on Free', premise: 'Five days in, no funds added. The daily dollar bites.', build: freeNew },
    { slug: 'running-out', name: 'About to run out', premise: 'Free with $2 left, burning $4 a day. Auto top-up off.', build: runningOut },
    { slug: 'debt', name: 'Owes money', premise: 'A declined top-up and a long call left the balance below zero.', build: inDebt },
    { slug: 'workspace', name: 'Workspace of four', premise: 'Owner Pays: four people’s work billed to the owner.', build: workspace },
    { slug: 'legacy', name: 'Pro, old plan', premise: 'Credits and 3× prices, until the switch-over.', build: legacyPro },
    { slug: 'platform', name: 'Developer platform', premise: 'Keys, users and agents on /v1, with caps.', build: platform, console: true },
];

const cache = new Map<string, UsageSnapshot>();
export function fixtureSnapshot(slug: string): UsageSnapshot {
    const f = USAGE_FIXTURES.find((x) => x.slug === slug) ?? USAGE_FIXTURES[0];
    let s = cache.get(f.slug);
    if (!s) {
        s = withCapSpend(f.build());
        cache.set(f.slug, s);
    }
    return s;
}


// ── as usage:page sends them ─────────────────────────────────────────────────

/** The fields the backend groups by (repositories/usage_page.py GROUP_FIELDS), as one key. */
function groupKey(r: UsageEventRow): string {
    const m = r.metadata;
    const pa = m.platform_api;
    return JSON.stringify([r.usage_type, r.usage_subtype, r.unit_type, r.user_resource, m.workflow_id, m.node_id, (m as { surface?: string }).surface, m.actual_user_id, m.responsible_user_id, m.project_id, m.database_id, m.repo_id, m.inbox_id, m.phone_number_id, (m as { number?: string }).number, m.channel, m.from, m.credential_id, m.domain, pa?.agent_id, pa?.tenant_id, pa?.key_id, pa?.project_id, pa?.surface]);
}

const includedOf = (r: UsageEventRow) => r.total_cost - r.topup_paid - r.balance_paid;

/** A fixture as the page reads it: its charges grouped, the money behind it, and its charges a page at a time. */
export function fixturePage(slug: string): { snap: PageSnapshot; firstPage: ChargesPage; charges: ChargesSource } {
    const s = fixtureSnapshot(slug);
    const plan = s.plan;
    const start = Date.parse(plan.window_start);
    const end = Date.parse(plan.window_end);
    const prevStart = new Date(start);
    prevStart.setUTCMonth(prevStart.getUTCMonth() - 1);
    const events = s.events.filter((r) => Date.parse(r.created_at) <= NOW_T && Date.parse(r.created_at) >= prevStart.getTime() && Date.parse(r.created_at) < end);
    const groups = new Map<string, UsageGroup>();
    for (const r of events) {
        const current = Date.parse(r.created_at) >= start;
        const day = dayKey(r.created_at);
        const k = groupKey(r);
        const id = `${k}|${day}|${current}`;
        const g = groups.get(id);
        if (g) {
            g.n += 1;
            g.quantity += r.quantity;
            g.total_cost += r.total_cost;
            g.cost_usd = (g.cost_usd ?? 0) + (r.cost_usd ?? r.total_cost);
            g.topup_paid = (g.topup_paid ?? 0) + r.topup_paid;
            g.balance_paid = (g.balance_paid ?? 0) + r.balance_paid;
            g.prompt_tokens += r.metadata.prompt_tokens ?? 0;
            g.completion_tokens += r.metadata.completion_tokens ?? 0;
            continue;
        }
        groups.set(id, {
            id,
            created_at: r.created_at,
            user_id: r.user_id,
            usage_type: r.usage_type,
            usage_subtype: r.usage_subtype,
            quantity: r.quantity,
            unit_type: r.unit_type,
            total_cost: r.total_cost,
            cost_usd: r.cost_usd ?? r.total_cost,
            topup_paid: r.topup_paid,
            balance_paid: r.balance_paid,
            user_resource: r.user_resource,
            metadata: { ...r.metadata },
            k,
            n: 1,
            current,
            day,
            prompt_tokens: r.metadata.prompt_tokens ?? 0,
            completion_tokens: r.metadata.completion_tokens ?? 0,
        });
    }
    const cur = events.filter((r) => !r.user_resource && Date.parse(r.created_at) >= start);
    const todayStart = Math.floor(NOW_T / DAY_MS) * DAY_MS;
    const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
    const credited = sum(s.balanceEntries.filter((b) => Date.parse(b.created_at) <= NOW_T).map((b) => b.usd));
    const deposits = s.balanceEntries.filter((b) => b.kind === 'deposit' && Date.parse(b.created_at) >= start && Date.parse(b.created_at) <= NOW_T);
    const snap: PageSnapshot = {
        now: NOW,
        account: { id: s.account.id },
        period: { window_start: plan.window_start, window_end: plan.window_end, previous_start: prevStart.toISOString() },
        billing: {
            plan: {
                billing_model: plan.billing_model,
                tier: plan.tier,
                window_start: plan.window_start,
                window_end: plan.window_end,
                previous_start: prevStart.toISOString(),
                included_usd: plan.included_usd,
                included_used_usd: sum(cur.map(includedOf)),
                daily_usd: plan.daily_usd,
                daily_used_usd: plan.daily_usd == null ? null : sum(cur.filter((r) => Date.parse(r.created_at) >= todayStart).map(includedOf)),
                fee_rate: plan.fee_rate,
                topup_usd: plan.topup_usd,
                topup_used_usd: sum(cur.map((r) => r.topup_paid)),
                plan_price_usd: plan.plan_price_usd,
                renews_at: plan.plan_price_usd > 0 ? plan.window_end : null,
            },
            balance: { usd: credited - sum(s.events.filter((r) => !r.user_resource && Date.parse(r.created_at) <= NOW_T).map((r) => r.balance_paid)), has: s.balanceEntries.length > 0 },
            funds: { usd: sum(deposits.map((d) => d.usd)), fee: sum(deposits.map((d) => d.fee_usd)), count: deposits.length },
            autoTopUp: s.autoTopUp,
            recurring: s.recurring.map((r) => ({ ...r })),
            domains: s.domains,
        },
        groups: [...groups.values()],
        directory: { ...s.directory, people: Object.fromEntries(Object.entries(s.directory.people).map(([k, v]) => [k, { name: v.name }])) },
    };
    const charges: ChargesSource = async (query, cursor, limit) => {
        const keys = query.keys ? new Set(query.keys) : null;
        const rows = events
            .filter((r) => Date.parse(r.created_at) >= start && (!keys || keys.has(groupKey(r))) && (!query.day || dayKey(r.created_at) === query.day))
            .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
        const from = cursor ? Number(cursor) : 0;
        const page: ChargeRow[] = rows.slice(from, from + limit).map((r) => ({ ...r, k: groupKey(r) }));
        return { rows: page, runs: {}, next: from + limit < rows.length ? String(from + limit) : null };
    };
    const first = events
        .filter((r) => Date.parse(r.created_at) >= start)
        .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
        .slice(0, 51);
    return {
        snap,
        firstPage: { rows: first.slice(0, 50).map((r) => ({ ...r, k: groupKey(r) })), runs: {}, next: first.length > 50 ? '50' : null },
        charges,
    };
}
