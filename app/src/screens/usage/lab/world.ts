// The Usage lab's world: the page's reads on the platform's API (GET /v1/usage/groups, GET /v1/usage/billing and
// POST /v1/usage/charges) answered as the API answers them, to the account's signed-in owner or to one of its keys, over
// the seven accounts the fixtures charge the way billing does (../fixtures.ts) or an account nobody bills, and the
// change stream refused as the API refuses it where it isn't served. A scene picks one, and the state its read is in.
import type { NoClick } from 'noclick';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import type { ChargeRow, ChargesPage, ChargesQuery, UsageBilling, UsageGroup, UsagePageData } from '@/screens/usage/types';
import { NOW, fixturePage } from '../fixtures';

/** An answer that never comes, for a page drawn while its read still waits. */
export const NO_ANSWER = Symbol('no answer');

/** Who reads: the account's signed-in owner, or one of its own secret keys (as this app is served). */
export type ActsAs = 'owner' | 'key';

/** The fixtures' moment: every date in them reads against it. */
export const CLOCK = NOW;

/** A billed fixture account (fixtures.ts USAGE_FIXTURES). */
export type BilledAccount = 'member' | 'free-new' | 'running-out' | 'debt' | 'workspace' | 'legacy' | 'platform';

/** An account the page reads (billed, or one nobody bills with charges or with none), or a read that never answers
 *  (`waiting`) or fails (`failed`, with the backend's own words). */
export type UsageWorld = { billed: BilledAccount } | { unbilled: 'busy' | 'empty' } | { read: 'waiting' | 'failed' };

/** A group as the API sends it: its breakdown fields flat beside it (repositories/usage_page.py GROUP_FIELDS). */
function wireGroup(g: UsageGroup): UsagePageData['groups'][number] {
    const m = g.metadata;
    const pa = m.platform_api ?? {};
    return {
        current: g.current,
        day: g.day,
        created_at: g.created_at,
        k: g.k,
        user_id: g.user_id,
        usage_type: g.usage_type,
        usage_subtype: g.usage_subtype,
        unit_type: g.unit_type,
        user_resource: g.user_resource,
        n: g.n,
        quantity: g.quantity,
        total_cost: g.total_cost,
        cost_usd: g.cost_usd,
        topup_paid: g.topup_paid,
        balance_paid: g.balance_paid,
        prompt_tokens: g.prompt_tokens,
        completion_tokens: g.completion_tokens,
        workflow_id: m.workflow_id ?? null,
        node_id: m.node_id ?? null,
        surface: m.surface ?? null,
        actual_user_id: m.actual_user_id ?? null,
        project_id: m.project_id ?? null,
        database_id: m.database_id ?? null,
        repo_id: m.repo_id ?? null,
        inbox_id: m.inbox_id ?? null,
        phone_number_id: m.phone_number_id ?? null,
        number: m.number ?? null,
        channel: m.channel ?? null,
        // Only an email's `from` is a sender: a metered reading names the stretch it covers there.
        sender: g.usage_subtype.startsWith('email/') ? m.from ?? null : null,
        credential_id: m.credential_id ?? null,
        domain: m.domain ?? null,
        pa_agent_id: pa.agent_id ?? null,
        pa_tenant_id: pa.tenant_id ?? null,
        pa_key_id: pa.key_id ?? null,
        pa_project_id: pa.project_id ?? null,
        pa_surface: pa.surface ?? null,
    };
}

// ── an account nobody bills ──────────────────────────────────────────────────

const ME = 'u_ada';
const TRIAGE = 'wf_triage';
const SONNET = 'openrouter/anthropic/claude-sonnet-4.6';
const MINI = 'openrouter/openai/gpt-4o-mini';

const unbilledGroup = (day: string, subtype: string, usd: number, n: number): UsagePageData['groups'][number] => {
    const ai = subtype.startsWith('openrouter/');
    return {
        current: true,
        day,
        created_at: `${day}T09:00:00Z`,
        k: `${subtype}|${TRIAGE}|agent`,
        user_id: ME,
        usage_type: ai ? 'ai_usage' : subtype === 'agent/sandbox' ? 'cpu_usage' : 'api_usage',
        usage_subtype: subtype,
        unit_type: ai ? 'tokens' : subtype === 'agent/sandbox' ? 'seconds' : 'requests',
        user_resource: false,
        n,
        quantity: ai ? 40_000 * n : n,
        total_cost: usd,
        prompt_tokens: ai ? 30_000 * n : 0,
        completion_tokens: ai ? 10_000 * n : 0,
        workflow_id: TRIAGE,
        node_id: 'agent',
    };
};

const UNBILLED_GROUPS = [
    unbilledGroup('2026-10-12', SONNET, 1.9, 14),
    unbilledGroup('2026-10-13', SONNET, 2.6, 18),
    unbilledGroup('2026-10-14', SONNET, 3.1, 22),
    unbilledGroup('2026-10-14', 'exa/search_api', 0.4, 80),
    unbilledGroup('2026-10-15', SONNET, 2.2, 16),
    unbilledGroup('2026-10-15', MINI, 0.6, 30),
    unbilledGroup('2026-10-16', MINI, 0.35, 18),
    unbilledGroup('2026-10-16', 'agent/sandbox', 0.25, 12),
];

/** One charge of each group, newest first. */
const UNBILLED_CHARGES: ChargeRow[] = UNBILLED_GROUPS.map((g, i) => ({
    id: `ch_${i}`,
    created_at: `${g.day}T1${i % 10}:20:00Z`,
    user_id: ME,
    organization_id: null,
    usage_type: g.usage_type,
    usage_subtype: g.usage_subtype,
    quantity: g.quantity / g.n,
    unit_type: g.unit_type,
    total_cost: g.total_cost / g.n,
    user_resource: false,
    metadata: { workflow_id: TRIAGE, node_id: 'agent' },
    k: g.k,
})).reverse();

/** The ledger of an account nobody bills, with these groups. */
function unbilled(groups: UsagePageData['groups']): Ledger {
    return {
        now: CLOCK,
        account: { id: ME },
        period: { window_start: '2026-10-01T00:00:00Z', window_end: '2026-11-01T00:00:00Z', previous_start: '2026-09-01T00:00:00Z' },
        groups,
        directory: { workflows: { [TRIAGE]: { name: 'Inbox triage' } }, agents: { [`${TRIAGE}:agent`]: { name: 'Triage agent' } }, people: { [ME]: { name: 'Ada Brooks' } } },
    };
}

// ── the API ──────────────────────────────────────────────────────────────────

/** GET /v1/usage/groups's answer but its `object`: the page's read without the money behind it or its charges. */
export type Ledger = Omit<UsagePageData, 'billing' | 'charges'>;

/** What one of the page's reads answers: its JSON (or a promise of it), a refusal as the API sends one, or nothing
 *  ever (NO_ANSWER). */
type Answer<T> = T | Response | typeof NO_ANSWER | Promise<T | Response | typeof NO_ANSWER>;

/** The page's reads, each as the platform's API answers it. */
export interface LedgerApi {
    /** GET /v1/usage/groups. */
    groups: () => Answer<Ledger>;
    /** GET /v1/usage/billing: the money behind the ledger, null where nobody is billed. */
    billing: () => Answer<UsagePageData['billing']>;
    /** POST /v1/usage/charges: a page of the charges in these groups (all: null), on that day, after that cursor. */
    charges: (query: ChargesQuery, cursor: string | null, limit: number) => Answer<ChargesPage>;
    /** POST /v1/watch/tokens: a token for the change stream; refused by default, as where the API doesn't serve it. */
    watch?: () => Answer<{ url: string; token: string; objects: string[] }>;
}

/** A call the client made: its method, its address and the JSON it sent. */
export interface LedgerCall {
    method: string;
    url: URL;
    body: Record<string, unknown> | null;
}

/** Hears each call the client makes, and the answer it gets. */
export type Observe = (call: LedgerCall, answered: Promise<Response>) => void;

/** How many charges a page holds when the call names no `limit`: the API's own (usage_page_handler.FIRST_PAGE). */
const FIRST_PAGE = 50;

/** One read's answer as the API sends it: its `object` beside what was read. */
async function answer<T>(object: string, read: Answer<T>, body: (value: T) => object): Promise<Response> {
    const value = await read;
    if (value === NO_ANSWER) return new Promise<Response>(() => undefined);
    if (value instanceof Response) return value;
    return Response.json({ object, ...body(value) });
}

/** Watching for changes, refused as the API refuses it where it doesn't serve it (`POST /v1/watch/tokens`). */
const streamOff = () =>
    Response.json(
        { error: { type: 'not_available', message: "Watching for changes isn't available on this deployment yet.", next_step: 'Read the objects again on a timer meanwhile.' } },
        { status: 409 }
    );

function respond(api: LedgerApi, { method, url, body }: LedgerCall): Promise<Response> {
    const route = `${method} ${url.pathname}`;
    if (route === 'GET /v1/usage/groups') return answer('usage_groups', api.groups(), (ledger) => ledger);
    if (route === 'GET /v1/usage/billing') return answer('usage_billing', api.billing(), (billing) => ({ billing }));
    if (route === 'POST /v1/usage/charges') {
        const asked = (body ?? {}) as { keys?: string[]; day?: string; cursor?: string; limit?: number };
        return answer('usage_charges', api.charges({ keys: asked.keys ?? null, day: asked.day ?? null }, asked.cursor ?? null, asked.limit ?? FIRST_PAGE), (page) => page);
    }
    if (route === 'POST /v1/watch/tokens') return api.watch ? answer('watch_token', api.watch(), (token) => token) : Promise.resolve(streamOff());
    console.warn(`[usage-lab] ${route}: the lab has no answer for it.`);
    return Promise.resolve(Response.json({ error: { type: 'not_found', message: `The Usage lab has no ${route}.` } }, { status: 404 }));
}

/** The platform's API as the page reads it, over `api`; `observe` hears every call. */
export function ledgerFetch(api: LedgerApi, observe?: Observe): typeof fetch {
    return (async (input: RequestInfo | URL, init?: RequestInit) => {
        const call: LedgerCall = {
            method: (init?.method ?? 'GET').toUpperCase(),
            url: new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url),
            body: typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : null,
        };
        const answered = respond(api, call);
        observe?.(call, answered);
        return answered;
    }) as typeof fetch;
}

/** A client over `api`: no retries, so a refused read fails at once. */
export function ledgerClient(api: LedgerApi, observe?: Observe): NoClick {
    return workFixtureClient(ledgerFetch(api, observe), { maxRetries: 0 });
}

/** The money behind the ledger as one of the account's keys reads it (`GET /v1/usage/billing`): the plan, the
 *  balance, funds added and what's scheduled; not auto top-up (its payment method) nor friends' credit (their names). */
function forKey(billing: UsageBilling | null): UsageBilling | null {
    if (!billing) return null;
    const { plan, balance, funds, recurring, domains } = billing;
    return { plan, balance, funds, recurring, domains } as UsageBilling;
}

/** The page's reads in a world, answered to `actsAs`. */
export function worldApi(world: UsageWorld, actsAs: ActsAs = 'owner'): LedgerApi {
    if ('read' in world) {
        // The backend's own words when a read fails.
        const read = () => (world.read === 'waiting' ? NO_ANSWER : Response.json({ error: { type: 'server_error', message: "Usage didn't load" } }, { status: 500 }));
        return { groups: read, billing: read, charges: read };
    }
    if ('unbilled' in world) {
        const ledger = unbilled(world.unbilled === 'busy' ? UNBILLED_GROUPS : []);
        return {
            groups: () => ledger,
            billing: () => null,
            charges: (query) => {
                const keys = query.keys ? new Set(query.keys) : null;
                const rows = UNBILLED_CHARGES.filter((c) => (!keys || keys.has(c.k)) && (!query.day || c.created_at.startsWith(query.day)));
                return { rows: ledger.groups.length ? rows : [], runs: {}, next: null };
            },
        };
    }
    const { snap, charges } = fixturePage(world.billed);
    const { billing, groups, ...ledger } = snap;
    return { groups: () => ({ ...ledger, groups: groups.map(wireGroup) }), billing: () => (actsAs === 'key' ? forKey(billing) : billing), charges };
}

/** A client in a world, reading as `actsAs`; `observe` hears every call it makes. */
export function usageClient(world: UsageWorld, observe?: Observe, actsAs: ActsAs = 'owner'): NoClick {
    return ledgerClient(worldApi(world, actsAs), observe);
}
