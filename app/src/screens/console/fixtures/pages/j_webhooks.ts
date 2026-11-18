// Fixtures for webhooks, the event log and publishable keys (built, read from fixtures in
// the lab): the lab story's healthy
// https://api.yourco.test/noclick/events and failing https://hooks.yourco.test/ops,
// the events of the last days with their deliveries, and a publishable key for the
// booking site. Webhook writes keep session state; tests call `resetWebhookFixtures()`.
import {
    AGENTS,
    DAY,
    FIXTURE_NOW_MS,
    HOUR,
    KEYS,
    MIN,
    PAGE_ERROR,
    USERS,
    ago,
    apiError,
    fixtureId,
    list,
    ok,
    pageList,
    type FixtureReply,
    type FixtureRequest,
    type FixtureRoute,
} from '../core';
import { userMatches } from './c';

const ACME = USERS[0].id;
const USER_42 = USERS[1].id;
const GLOBEX = USERS[2].id;
const SUPPORT_BOT = AGENTS[0].id;
const CONCIERGE = AGENTS[1].id;
const NOW = new Date(FIXTURE_NOW_MS).toISOString();

/** Ids under kind digit 7 from 90,000: webhooks 90,1xx, deliveries 90,2xx, events 90,3xx, public endpoints 90,4xx. */
const wid = (n: number) => fixtureId(7, 90_000 + n);
export const PROD_HOOK_ID = wid(101);
export const OPS_HOOK_ID = wid(102);
export const ACME_HOOK_ID = wid(103);
export const LAB_WEBHOOK_SECRET = 'nk_whsec_lab0000000000000000000000000000000';
export const LAB_PUBLISHABLE_KEY = 'nk_pub_00000000000000000000000000000000';

// ── the event catalog ───────────────────────────────────────────────────────

export const EVENT_TYPES = [
    { name: 'operation.succeeded', description: 'An operation finished: an agent turn, a connect link, a call.', emitted: true },
    { name: 'operation.failed', description: 'An operation failed, was canceled or expired; data.error says why.', emitted: true },
    { name: 'human.answered', description: 'A person answered a request, an approval or a form.', emitted: true },
    { name: 'human.expired', description: 'A request to a person expired unanswered.', emitted: true },
    { name: 'connection.connected', description: "A connection's account was connected, or reconnected.", emitted: true },
    { name: 'connection.disconnected', description: 'A connection stopped working: its account was revoked or removed at the provider.', emitted: true },
    { name: 'connection.deleted', description: 'A connection was deleted, and its account disconnected with it.', emitted: true },
    { name: 'agent.turn.completed', description: 'An agent finished a turn; data holds the reply.', emitted: true },
    { name: 'agent.turn.failed', description: "An agent's turn failed; data.error says why.", emitted: true },
    { name: 'agent.conversation.handed_off', description: 'An agent handed a conversation to a person with its hand_off tool.', emitted: false },
    { name: 'agent.wakeup.delivered', description: 'A wake-up started its turn; data is the wake-up, with its operation_id.', emitted: true },
    { name: 'agent.wakeup.missed', description: "A recurring wake-up came due and its turn couldn't be paid for, so it missed that time and comes round at its next; data.reason says why.", emitted: true },
    { name: 'agent.wakeup.failed', description: "A wake-up's turn couldn't run and it won't come again: a one-off the money ran out for, or the agent expired; data.error says why.", emitted: true },
    { name: 'agent.job.update', description: 'A job sent its parent an update; data is the update, with its job_id.', emitted: true },
    { name: 'inbox.message.received', description: 'Mail arrived at an inbox.', emitted: true },
    { name: 'phone.call.completed', description: 'A call an agent placed from one of your numbers ended; data holds the transcript.', emitted: true },
    { name: 'channel.halted', description: 'A channel stopped: its budget ran out, it hit its turn limit, or it was closed.', emitted: true },
    { name: 'sandbox.terminated', description: 'A sandbox stopped: its time ran out, it was terminated, or it failed.', emitted: true },
    { name: 'deployment.ready', description: "An app's deployment is live.", emitted: false },
    { name: 'deployment.failed', description: "An app's deployment failed to build or start.", emitted: false },
    {
        name: 'schedule.paused',
        description: "An agent's trigger (a schedule, a webhook, an event) kept failing the same way and stopped until the agent is resumed; data is the trigger.",
        emitted: true,
    },
    { name: 'domain.active', description: "A domain's records are in place and it's serving.", emitted: false },
    { name: 'domain.expiring', description: "A domain expires within 30 days and won't renew on its own.", emitted: false },
    { name: 'database.quota_warning', description: 'A database reached 80% of its size limit.', emitted: false },
    { name: 'card.authorization.requested', description: 'A card purchase waits for your approval.', emitted: false },
    { name: 'card.transaction.declined', description: 'A card purchase was declined.', emitted: false },
    { name: 'spend.cap_reached', description: 'A key, user or agent reached its monthly spend cap; data.scope says which.', emitted: true },
    {
        name: 'usage.recorded',
        description: 'Spend for one of your users settled: a turn, an AI request, a span of a call or a sandbox, a purchase or a renewal; data is the usage record, to bill them on.',
        emitted: true,
    },
    { name: 'user.spending.paused', description: "You paused a user's spending; data is the user's spending.", emitted: true },
    { name: 'user.spending.resumed', description: "You resumed a user's spending; data.replayed says how many held messages are running now.", emitted: true },
].map((t) => ({ object: 'event_type', ...t }));

// ── events ──────────────────────────────────────────────────────────────────

interface EventRow {
    object: 'event';
    id: string;
    type: string;
    user_id: string | null;
    created_at: string;
    data: Record<string, unknown>;
}

const event = (n: number, type: string, user: string | null, age: number, data: Record<string, unknown>): EventRow => ({
    object: 'event',
    id: wid(300 + n),
    type,
    user_id: user,
    created_at: ago(age),
    data,
});

/** Newest first, as `/v1/events` lists them. */
export const EVENTS: readonly EventRow[] = [
    event(1, 'deployment.failed', ACME, 4 * MIN, {
        object: 'deployment', id: wid(901), project: 'status-page', branch: 'preview/new-header', status: 'failed',
        url: null, error: 'Build failed: `npm run build` exited with code 1.',
    }),
    event(2, 'operation.succeeded', null, 6 * MIN, {
        object: 'operation', id: fixtureId(4, 1), kind: 'agent.message', status: 'succeeded', agent_id: SUPPORT_BOT,
        summary: 'Where is my refund for invoice 1042?', result: { text: 'Your refund went out on Sep 24 and should land in 3 to 5 days.' },
    }),
    event(3, 'human.answered', ACME, 25 * MIN, {
        object: 'human_request', id: fixtureId(5, 20), kind: 'human.approve', status: 'answered', agent_id: CONCIERGE,
        message: 'Book a table for 6 at Nopa, Friday 7pm, with a $120 deposit?', answer: { approved: true }, answered_by: 'ops@acme.test',
    }),
    event(4, 'card.authorization.requested', ACME, 40 * MIN, {
        object: 'card_authorization', id: wid(902), card: 'Office supplies', agent_id: CONCIERGE, merchant: 'Staples',
        amount_usd: 1240, status: 'pending_approval',
    }),
    event(5, 'operation.failed', GLOBEX, 3 * HOUR, {
        object: 'operation', id: fixtureId(4, 5), kind: 'agent.message', status: 'failed', agent_id: SUPPORT_BOT,
        summary: 'Refund the duplicate charge on invoice 1042',
        error: { type: 'spend_cap_exceeded', message: "User globex's spend cap of $20 this month is used up ($20.4100 spent)." },
    }),
    event(6, 'spend.cap_reached', GLOBEX, 3 * HOUR - 1000, {
        object: 'spend_cap', scope: 'user', id: GLOBEX, cap_usd: 20, spent_usd: 20.41, resets_at: '2026-10-01T00:00:00Z',
    }),
    event(7, 'channel.halted', null, 5 * HOUR, {
        object: 'channel', id: fixtureId(7, 102), name: 'triage', status: 'closed', reason: 'budget', spent_usd: 5, budget_usd: 5,
    }),
    event(8, 'domain.active', null, 26 * HOUR, {
        object: 'domain', id: fixtureId(7, 70_001), name: 'acmebooking.com', status: 'active', serves: 'booking',
    }),
    event(9, 'deployment.ready', null, 27 * HOUR, {
        object: 'deployment', id: wid(903), project: 'booking', branch: 'main', status: 'ready', url: 'https://booking.noclick.site',
    }),
    event(10, 'agent.turn.completed', null, 32 * HOUR, {
        object: 'agent_turn', id: wid(904), agent: 'digest', conversation: 'cron', trigger: 'cron',
        reply: 'Posted the overnight summary: 14 new tickets, 3 urgent.',
    }),
    event(11, 'inbox.message.received', ACME, 2 * DAY, {
        object: 'inbox_message', id: wid(905), inbox_id: fixtureId(7, 201), to: 'support-acme@in.noclick.app',
        from: 'dana@customer.test', subject: 'Invoice 1042 was charged twice',
    }),
    event(12, 'human.expired', USER_42, 2 * DAY + 3 * HOUR, {
        object: 'human_request', id: fixtureId(5, 21), kind: 'human.ask', status: 'expired', message: 'Which calendar should I use for work?',
    }),
    event(13, 'sandbox.terminated', null, 2 * DAY + 5 * HOUR, {
        object: 'sandbox', id: fixtureId(7, 402), status: 'terminated', end_reason: 'timeout', image: 'python',
    }),
    event(14, 'agent.conversation.handed_off', null, 2 * DAY + 8 * HOUR, {
        object: 'agent_conversation', agent: 'digest', conversation: 'overnight-0924', to: { email: 'ops@yourco.test' },
        summary: 'Three refunds over $500 came in overnight; they need a person to check them.',
    }),
];

// ── webhooks and deliveries ─────────────────────────────────────────────────

interface HookRow {
    object: 'webhook';
    id: string;
    url: string;
    events: string[];
    enabled: boolean;
    status: 'healthy' | 'failing' | 'disabled';
    description: string | null;
    success_rate_24h: number | null;
    last_failure: { at: string; response_status: number | null; error: string } | null;
    user_id: string | null;
    created_at: string;
}

const INITIAL_HOOKS: readonly HookRow[] = [
    {
        object: 'webhook', id: PROD_HOOK_ID, url: 'https://api.yourco.test/noclick/events',
        events: ['operation.*', 'human.answered', 'human.expired', 'connection.disconnected'], enabled: true, status: 'healthy',
        description: 'Production receiver', success_rate_24h: 0.998, last_failure: { at: ago(3 * HOUR), response_status: 500, error: 'Internal Server Error' },
        user_id: null, created_at: ago(21 * DAY),
    },
    {
        object: 'webhook', id: OPS_HOOK_ID, url: 'https://hooks.yourco.test/ops',
        events: ['deployment.failed', 'domain.*', 'spend.cap_reached', 'card.authorization.requested', 'channel.halted'], enabled: true,
        status: 'failing', description: 'Ops alerts', success_rate_24h: 0.38, last_failure: { at: ago(4 * MIN), response_status: 502, error: 'Bad Gateway' },
        user_id: null, created_at: ago(18 * DAY),
    },
    {
        object: 'webhook', id: ACME_HOOK_ID, url: 'https://acme.yourco.test/connections', events: ['connection.*'], enabled: false,
        status: 'disabled', description: "Acme's connection alerts", success_rate_24h: null, last_failure: null, user_id: ACME, created_at: ago(12 * DAY),
    },
];

interface DeliveryRow {
    object: 'webhook_delivery';
    id: string;
    webhook_id: string;
    event_id: string;
    event_type: string;
    status: 'pending' | 'retrying' | 'succeeded' | 'failed';
    attempts: number;
    response_status: number | null;
    response_body: string | null;
    request_body: string;
    duration_ms: number | null;
    next_retry_at: string | null;
    created_at: string;
}

const BAD_GATEWAY = '<html>\n<head><title>502 Bad Gateway</title></head>\n<body><center><h1>502 Bad Gateway</h1></center></body>\n</html>';

function delivery(n: number, hook: string, eventN: number, fields: Partial<DeliveryRow>): DeliveryRow {
    const e = EVENTS[eventN - 1];
    return {
        object: 'webhook_delivery',
        id: wid(200 + n),
        webhook_id: hook,
        event_id: e.id,
        event_type: e.type,
        status: 'succeeded',
        attempts: 1,
        response_status: 200,
        response_body: '{"received":true}',
        request_body: JSON.stringify(e, null, 2),
        duration_ms: 184,
        next_retry_at: null,
        created_at: e.created_at,
        ...fields,
    };
}

const retrying = (next: number, attempts: number): Partial<DeliveryRow> => ({
    status: 'retrying', attempts, response_status: 502, response_body: BAD_GATEWAY, duration_ms: 1207, next_retry_at: new Date(FIXTURE_NOW_MS + next).toISOString(),
});

const INITIAL_DELIVERIES: readonly DeliveryRow[] = [
    delivery(1, OPS_HOOK_ID, 1, retrying(6 * MIN, 2)),
    delivery(2, PROD_HOOK_ID, 2, { duration_ms: 142 }),
    delivery(3, PROD_HOOK_ID, 3, { duration_ms: 156, response_status: 204, response_body: null }),
    delivery(4, OPS_HOOK_ID, 4, retrying(21 * MIN, 3)),
    delivery(5, PROD_HOOK_ID, 5, { attempts: 2, duration_ms: 212 }),
    delivery(6, OPS_HOOK_ID, 6, retrying(2 * HOUR, 5)),
    delivery(7, OPS_HOOK_ID, 7, retrying(3 * HOUR, 6)),
    delivery(8, OPS_HOOK_ID, 8, { duration_ms: 311 }),
    delivery(9, PROD_HOOK_ID, 12, { duration_ms: 170 }),
];

let hooks: HookRow[] = INITIAL_HOOKS.map((h) => ({ ...h }));
let deliveries: DeliveryRow[] = INITIAL_DELIVERIES.map((d) => ({ ...d }));
let created = 0;

/** Back to the story's webhooks and deliveries (tests call it between cases). */
export function resetWebhookFixtures(): void {
    hooks = INITIAL_HOOKS.map((h) => ({ ...h }));
    deliveries = INITIAL_DELIVERIES.map((d) => ({ ...d }));
    created = 0;
}

export const WEBHOOKS: readonly HookRow[] = INITIAL_HOOKS;

const body = (r: FixtureRequest) => (r.body ?? {}) as Record<string, unknown>;

function hookFor(r: FixtureRequest): HookRow | undefined {
    return hooks.find((h) => h.id === r.params.id);
}

function notFound(what: string): FixtureReply {
    return apiError(404, 'not_found', `No ${what} has that id.`);
}

/** `operation.*` matches both operation types; `*` everything. */
function typeMatches(pattern: string, type: string): boolean {
    if (pattern === '*') return true;
    return pattern.endsWith('.*') ? type.startsWith(pattern.slice(0, -1)) : pattern === type;
}

const eventOf = (id: string) => EVENTS.find((e) => e.id === id);

// ── publishable keys ─────────────────────────────────────────────────────────

/** What the owner marked public: a workflow's endpoint and an agent's share page. */
export const PUBLIC_ENDPOINTS = [
    { object: 'public_endpoint', kind: 'workflow', id: fixtureId(8, 90_001), name: 'order-intake', url: `https://api.noclick.com/v1/workflows/${fixtureId(8, 90_001)}/endpoint`, user_id: null },
    { object: 'public_endpoint', kind: 'agent_share', id: CONCIERGE, name: 'concierge', url: `https://api.noclick.com/v1/agents/${CONCIERGE}/share/messages`, user_id: null },
    { object: 'public_endpoint', kind: 'workflow', id: fixtureId(8, 90_002), name: 'availability', url: `https://api.noclick.com/v1/workflows/${fixtureId(8, 90_002)}/endpoint`, user_id: null },
];

export const PUBLISHABLE_KEYS = [
    {
        object: 'key', id: fixtureId(1, 90), kind: 'publishable', type: 'publishable', name: 'booking-site', key_prefix: LAB_PUBLISHABLE_KEY.slice(0, 11),
        publishable_key: LAB_PUBLISHABLE_KEY, scopes: ['public'], spend_cap_usd_per_month: 25, user_id: null,
        public_endpoints: [PUBLIC_ENDPOINTS[2], PUBLIC_ENDPOINTS[1]].map((e) => ({ ...e, public: true })), per_visitor_limit_per_minute: 20,
        allowed_origins: ['https://acmebooking.com', 'https://booking.noclick.site'],
        created_at: ago(6 * DAY), last_used_at: ago(3 * MIN), expires_at: null, revoked_at: null, spent_usd_this_month: 1.84,
    },
];

/** A new publishable key: the endpoints it may call (from the dialog's picks) and its visitor limit. */
export function publishableKeyView(b: Record<string, unknown>) {
    const picked = Array.isArray(b.public_endpoints) ? (b.public_endpoints as { kind: string; id: string }[]) : [];
    return {
        ...PUBLISHABLE_KEYS[0],
        id: fixtureId(1, 91),
        name: b.name,
        public_endpoints: PUBLIC_ENDPOINTS.filter((e) => picked.some((p) => p.kind === e.kind && p.id === e.id)).map((e) => ({ ...e, public: true })),
        per_visitor_limit_per_minute: typeof b.per_visitor_limit_per_minute === 'number' ? b.per_visitor_limit_per_minute : 20,
        allowed_origins: Array.isArray(b.allowed_origins) ? b.allowed_origins : [],
        spend_cap_usd_per_month: b.spend_cap_usd_per_month ?? null,
        created_at: new Date(FIXTURE_NOW_MS).toISOString(),
        last_used_at: null,
        spent_usd_this_month: 0,
    };
}

export const routes: FixtureRoute[] = [
    // ── webhooks ──────────────────────────────────────────────────────────
    {
        method: 'GET',
        path: '/v1/webhooks',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            return list(r.set === 'populated' ? hooks.filter((h) => userMatches(r.query, h.user_id)) : []);
        },
    },
    { method: 'GET', path: '/v1/webhooks/:id', reply: (r) => (hookFor(r) ? ok(hookFor(r)) : notFound('webhook')) },
    {
        method: 'POST',
        path: '/v1/webhooks',
        reply: (r) => {
            const b = body(r);
            const url = String(b.url ?? '');
            if (!url.startsWith('https://')) return apiError(400, 'invalid_request', 'A webhook URL must start with https://.', 'Use noclick webhooks listen to try it on your machine.', { field: 'url' });
            if (!Array.isArray(b.events) || !b.events.length) return apiError(400, 'invalid_request', 'Pick at least one event type.', undefined, { field: 'events' });
            created += 1;
            const row: HookRow = {
                object: 'webhook', id: wid(150 + created), url, events: b.events as string[], enabled: true, status: 'healthy',
                description: typeof b.description === 'string' ? b.description : null, success_rate_24h: null, last_failure: null,
                user_id: r.headers.get('NoClick-User'), created_at: NOW,
            };
            hooks = [row, ...hooks];
            return ok({ ...row, secret: LAB_WEBHOOK_SECRET });
        },
    },
    {
        method: 'PATCH',
        path: '/v1/webhooks/:id',
        reply: (r) => {
            const hook = hookFor(r);
            if (!hook) return notFound('webhook');
            const b = body(r);
            Object.assign(hook, b);
            if ('enabled' in b) hook.status = b.enabled ? (hook.id === OPS_HOOK_ID ? 'failing' : 'healthy') : 'disabled';
            return ok(hook);
        },
    },
    {
        method: 'DELETE',
        path: '/v1/webhooks/:id',
        reply: (r) => {
            if (!hookFor(r)) return notFound('webhook');
            hooks = hooks.filter((h) => h.id !== r.params.id);
            return { status: 204 };
        },
    },
    {
        method: 'POST',
        path: '/v1/webhooks/:id/rotate_secret',
        reply: (r) => (hookFor(r) ? ok({ ...hookFor(r), secret: 'nk_whsec_lab1111111111111111111111111111111' }) : notFound('webhook')),
    },
    {
        method: 'POST',
        path: '/v1/webhooks/:id/test',
        reply: (r) => {
            const hook = hookFor(r);
            if (!hook) return notFound('webhook');
            const type = String(body(r).event_type ?? 'operation.succeeded');
            const sample = { object: 'event', id: wid(399), type, user_id: null, created_at: NOW, data: { object: 'sample', id: wid(398) } };
            const failing = hook.id === OPS_HOOK_ID;
            return ok({
                object: 'webhook_delivery', id: wid(299), webhook_id: hook.id, event_id: sample.id, event_type: type,
                status: failing ? 'failed' : 'succeeded', attempts: 1, response_status: failing ? 502 : 204,
                response_body: failing ? BAD_GATEWAY : null, request_body: JSON.stringify(sample, null, 2),
                duration_ms: failing ? 1180 : 131, next_retry_at: null, created_at: NOW,
            });
        },
    },
    {
        method: 'GET',
        path: '/v1/webhooks/:id/deliveries',
        reply: (r) => {
            if (!hookFor(r)) return notFound('webhook');
            const statuses = r.query.get('status')?.split(',').filter(Boolean);
            const eventId = r.query.get('event_id');
            return list(
                deliveries.filter((d) => d.webhook_id === r.params.id && (!statuses || statuses.includes(d.status)) && (!eventId || d.event_id === eventId))
            );
        },
    },
    {
        method: 'POST',
        path: '/v1/webhooks/:id/deliveries/:delivery/redeliver',
        reply: (r) => {
            const d = deliveries.find((x) => x.id === r.params.delivery && x.webhook_id === r.params.id);
            if (!d) return notFound('delivery');
            const failing = hookFor(r)?.status === 'failing';
            Object.assign(d, failing ? { ...retrying(6 * MIN, d.attempts + 1) } : { status: 'succeeded', attempts: d.attempts + 1, response_status: 200, response_body: '{"received":true}', next_retry_at: null, duration_ms: 163 });
            return ok(d);
        },
    },

    // ── events ────────────────────────────────────────────────────────────
    { method: 'GET', path: '/v1/events/types', reply: (r) => (r.set === 'error' ? PAGE_ERROR : list(EVENT_TYPES)) },
    {
        method: 'GET',
        path: '/v1/events',
        reply: (r) => {
            const types = r.query.get('type')?.split(',').filter(Boolean);
            const rows = EVENTS.filter((e) => userMatches(r.query, e.user_id) && (!types || types.some((t) => typeMatches(t, e.type))));
            const limit = Number(r.query.get('limit') ?? 50);
            return pageList(r, rows.slice(0, limit));
        },
    },
    {
        method: 'GET',
        path: '/v1/events/:id',
        reply: (r) => {
            const e = eventOf(r.params.id);
            return e ? ok({ ...e, deliveries: deliveries.filter((d) => d.event_id === e.id) }) : notFound('event');
        },
    },

    // ── keys: publishable keys and what they may call ─────────────────────
    {
        method: 'GET',
        path: '/v1/keys',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            if (r.set === 'first-run') return list([KEYS[0]]);
            if (r.set !== 'populated') return list(KEYS.slice(0, 2));
            return list(r.query.get('status') === 'revoked' ? KEYS : [...KEYS, ...PUBLISHABLE_KEYS]);
        },
    },
    { method: 'GET', path: '/v1/public_endpoints', reply: (r) => pageList(r, PUBLIC_ENDPOINTS) },
];
