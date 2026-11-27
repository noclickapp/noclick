// Fixtures for Dicts and Queues: canned /v1 answers shaped like the API's own, filtered the way the
// routes would, so the lab and the page tests run the real client. Writes answer as the
// API would and change nothing here; the pages keep what they wrote.
import { AGENTS, DAY, FIXTURE_NOW_MS, HOUR, MIN, USERS, ago, apiError, fixtureId, list, ok, pageList, type FixtureReply, type FixtureRequest, type FixtureRoute } from '../core';
import { userMatches } from './c';
import { BOOKING_APP_ID } from './g_domains';

const ACME = USERS[0].id;
const SUPPORT = AGENTS[0];
const NOW = new Date(FIXTURE_NOW_MS).toISOString();
const MB = 1024 ** 2;

/** Ids under kind digit 7 from 120,000: dicts 120,0xx, queues 121,0xx, messages 122,xxx; operations 120,xxx. */
const dictId = (n: number) => fixtureId(7, 120_000 + n);
const queueId = (n: number) => fixtureId(7, 121_000 + n);
const messageId = (n: number) => fixtureId(7, 122_000 + n);
const opId = (n: number) => fixtureId(4, 120_000 + n);

const inFuture = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString();

// ── dicts ──────────────────────────────────────────────────────────────────

export const DICTS = [
    {
        object: 'dict',
        id: dictId(1),
        name: 'processed-orders',
        key_count: 18240,
        size_bytes: Math.round(3.4 * MB),
        used_by: [{ kind: 'project', id: BOOKING_APP_ID, name: 'booking', binding: 'SEEN' }],
        user_id: null,
        created_at: ago(58 * DAY),
    },
    {
        object: 'dict',
        id: dictId(2),
        name: 'feature-flags',
        key_count: 12,
        size_bytes: 1_236,
        used_by: [] as { kind: string; id: string; name: string; binding: string | null }[],
        user_id: ACME,
        created_at: ago(26 * DAY),
    },
];

interface ItemFixture {
    key: string;
    value: unknown;
    expires_at: string | null;
    updated_at: string;
}

const STATUSES = ['refunded', 'confirmed', 'confirmed', 'cancelled', 'confirmed'];

/** 30 handled orders (`o_1811` … `o_1840`), then the counters and locks the booking app keeps beside them. */
const ORDER_ITEMS: ItemFixture[] = [
    { key: 'evt_9f2c1a7e', value: true, expires_at: inFuture(6 * DAY), updated_at: ago(DAY) },
    { key: 'lock:nightly-report', value: 'worker-3', expires_at: inFuture(4 * MIN), updated_at: ago(MIN) },
    ...Array.from({ length: 30 }, (_, i) => {
        const n = 1840 - i;
        const status = STATUSES[i % STATUSES.length];
        return {
            key: `o_${n}`,
            value: { status, by: i % 3 === 0 ? 'support-bot' : 'booking', at: ago((i + 1) * 47 * MIN) },
            expires_at: null,
            updated_at: ago((i + 1) * 47 * MIN),
        };
    }),
    { key: 'refunds-today', value: 7, expires_at: inFuture(7 * HOUR + 40 * MIN), updated_at: ago(12 * MIN) },
];

const FLAG_ITEMS: ItemFixture[] = [
    ['beta-search', false],
    ['checkout-v2', true],
    ['dark-mode', true],
    ['max-upload-mb', 50],
    ['new-checkout', true],
    ['onboarding-video', false],
    ['pricing-page', { variant: 'b', split: 0.5 }],
    ['sms-reminders', true],
    ['support-hours', { start: '08:00', end: '18:00', tz: 'America/New_York' }],
    ['theme', 'ocean'],
    ['trial-days', 14],
    ['waitlist', false],
].map(([key, value], i) => ({ key: key as string, value, expires_at: null, updated_at: ago((i + 2) * DAY) }));

const ITEMS: Record<string, ItemFixture[]> = {
    [dictId(1)]: [...ORDER_ITEMS].sort((a, b) => (a.key < b.key ? -1 : 1)),
    [dictId(2)]: FLAG_ITEMS,
};

const sizeOf = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).length;

function itemView(item: ItemFixture, keysOnly = false) {
    return {
        object: 'dict_item',
        key: item.key,
        ...(keysOnly ? {} : { value: item.value }),
        expires_at: item.expires_at,
        updated_at: item.updated_at,
        size_bytes: sizeOf(item.value),
    };
}

/** `?prefix=&view=keys`, in key order; `cursor` is an offset. */
function listItems(r: FixtureRequest, id: string): FixtureReply {
    if (r.set === 'error') return apiError(500, 'server_error', 'The platform API failed to answer.', 'Retry in a moment.');
    const prefix = r.query.get('prefix') ?? '';
    const rows = (ITEMS[id] ?? []).filter((i) => i.key.startsWith(prefix));
    const start = Number(r.query.get('cursor') ?? 0);
    const limit = Number(r.query.get('limit') ?? 100);
    const keysOnly = r.query.get('view') === 'keys';
    return list(
        rows.slice(start, start + limit).map((i) => itemView(i, keysOnly)),
        start + limit < rows.length ? String(start + limit) : null
    );
}

const missingKey = (key: string) => apiError(404, 'not_found', `No key ${key} in this dict.`, undefined, { key });

// ── queues ─────────────────────────────────────────────────────────────────

export const QUEUES = [
    {
        object: 'queue',
        id: queueId(1),
        name: 'invoices',
        depth: 14,
        in_flight: 2,
        dead_letter_count: 1,
        max_attempts: 5,
        used_by: [{ kind: 'agent', id: SUPPORT.id, name: SUPPORT.name, binding: null }],
        user_id: null,
        created_at: ago(44 * DAY),
    },
    {
        object: 'queue',
        id: queueId(2),
        name: 'webhook-buffer',
        depth: 0,
        in_flight: 0,
        dead_letter_count: 0,
        max_attempts: 8,
        used_by: [{ kind: 'project', id: BOOKING_APP_ID, name: 'booking', binding: 'JOBS' }],
        user_id: null,
        created_at: ago(30 * DAY),
    },
];

const CUSTOMERS = ['acme', 'user_42', 'acme', 'harbor-room', 'acme', 'the-loft', 'user_42', 'garden-terrace'];

function message(n: number, fields: Record<string, unknown>) {
    return {
        object: 'queue_message',
        id: messageId(n),
        queue_id: queueId(1),
        status: 'waiting',
        attempts: 0,
        visible_at: null,
        lease_expires_at: null,
        last_error: null,
        dead_lettered_at: null,
        ...fields,
    };
}

/** What `peek` sees on invoices, oldest first: two that support-bot is on, then those waiting. */
const INVOICE_MESSAGES = [
    message(1, { body: { invoice: 'INV-1031', customer: 'acme', amount_usd: 480 }, status: 'in_flight', attempts: 3, enqueued_at: ago(3 * HOUR), lease_expires_at: inFuture(4 * MIN), last_error: 'The turn ran out of time before it finished.' }),
    message(2, { body: { invoice: 'INV-1032', customer: 'user_42', amount_usd: 64 }, status: 'in_flight', attempts: 1, enqueued_at: ago(2 * HOUR + 10 * MIN), lease_expires_at: inFuture(9 * MIN) }),
    ...Array.from({ length: 8 }, (_, i) =>
        message(3 + i, {
            body: { invoice: `INV-${1033 + i}`, customer: CUSTOMERS[i], amount_usd: [120, 1250, 89, 310, 42, 760, 199, 55][i] },
            enqueued_at: ago((110 - i * 13) * MIN),
        })
    ),
    message(11, { body: { check_payment: 'INV-1029' }, status: 'delayed', enqueued_at: ago(20 * MIN), visible_at: inFuture(40 * MIN) }),
];

const DEAD_LETTERS: Record<string, unknown[]> = {
    [queueId(1)]: [
        message(90, {
            body: { invoice: 'INV-0998', customer: 'globex', amount_usd: 2400 },
            status: 'dead',
            attempts: 5,
            enqueued_at: ago(DAY + 5 * HOUR),
            last_error: "Stripe says invoice INV-0998 doesn't exist, so there was nothing to chase.",
            dead_lettered_at: ago(3 * HOUR),
        }),
    ],
};

const JITTER = [0, 1, 0, -1, 1, 0, 0, -1];

/** Webhook bursts on the buffer, by point: how many deliveries waited. */
const BURSTS: Record<number, number> = { 18: 120, 19: 36, 44: 240, 45: 90, 46: 12, 71: 64, 88: 180 };

/** 96 points, 15 minutes apart: invoices build up through the working day; the buffer spikes with webhook bursts. */
function depthSeries(id: string) {
    return Array.from({ length: 96 }, (_, i) => {
        const at = new Date(FIXTURE_NOW_MS - (95 - i) * 15 * MIN).toISOString();
        if (id === queueId(1)) {
            const d = new Date(at);
            const hour = d.getUTCHours() + d.getUTCMinutes() / 60;
            const workday = hour >= 12 ? Math.sin((Math.PI * (hour - 12)) / 12) : 0; // New York's business day
            const depth = i === 95 ? 14 : Math.max(0, Math.round(2 + 13 * workday + JITTER[i % JITTER.length]));
            return { at, depth, in_flight: i === 95 ? 2 : Math.min(2, depth) };
        }
        const burst = BURSTS[i] ?? 0;
        return { at, depth: burst, in_flight: Math.min(8, burst) };
    });
}

function queueOperation(q: (typeof QUEUES)[number]) {
    return {
        object: 'operation',
        id: opId(2),
        kind: 'queue.export',
        status: 'succeeded',
        summary: q.name,
        user_id: q.user_id,
        result: exportBundle(q.name, 'queue', `queues/${q.name}.jsonl: its messages as of one moment, oldest first, one per line with its status, attempts and body.`),
        error: null,
        created_at: NOW,
        updated_at: NOW,
        events: [],
    };
}

function exportBundle(name: string, kind: 'dict' | 'queue', detail: string) {
    return {
        object: 'export',
        url: `https://exports.noclick.test/${name}-2026-09-26.zip`,
        expires_at: new Date(FIXTURE_NOW_MS + 7 * DAY).toISOString(),
        size_bytes: 24_576,
        contents: [{ kind, name, detail }],
        remaining_dependencies: [],
    };
}

// ── routes ─────────────────────────────────────────────────────────────────

function listed<T extends { user_id: string | null; name: string }>(r: FixtureRequest, rows: readonly T[]): FixtureReply {
    const name = r.query.get('name');
    return pageList(r, rows.filter((row) => userMatches(r.query, row.user_id) && (!name || row.name === name)));
}

const dict = (r: FixtureRequest) => DICTS.find((d) => d.id === r.params.id);
const queue = (r: FixtureRequest) => QUEUES.find((q) => q.id === r.params.id);
const noDict = apiError(404, 'not_found', 'No such dict.');
const noQueue = apiError(404, 'not_found', 'No such queue.');

const dictRoutes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/dicts', reply: (r) => listed(r, DICTS) },
    { method: 'GET', path: '/v1/dicts/:id', reply: (r) => (dict(r) ? ok(dict(r)) : noDict) },
    { method: 'GET', path: '/v1/dicts/:id/items', reply: (r) => (dict(r) ? listItems(r, r.params.id) : noDict) },
    {
        method: 'GET',
        path: '/v1/dicts/:id/items/:key',
        reply: (r) => {
            if (!dict(r)) return noDict;
            const item = (ITEMS[r.params.id] ?? []).find((i) => i.key === r.params.key);
            return item ? ok(itemView(item)) : missingKey(r.params.key);
        },
    },
    {
        method: 'PUT',
        path: '/v1/dicts/:id/items/:key',
        reply: (r) => {
            if (!dict(r)) return noDict;
            const body = (r.body ?? {}) as { value?: unknown; ttl_s?: number; if_absent?: boolean };
            const exists = (ITEMS[r.params.id] ?? []).some((i) => i.key === r.params.key);
            if (sizeOf(body.value) > MB) return apiError(400, 'invalid_request', 'A value is at most 1 MB as JSON.', undefined, { field: 'value' });
            const written = !(body.if_absent && exists);
            const expires = body.ttl_s ? inFuture(body.ttl_s * 1000) : null;
            return ok({ object: 'dict_item', key: r.params.key, written, value: body.value ?? null, expires_at: expires, updated_at: NOW, size_bytes: sizeOf(body.value) });
        },
    },
    {
        method: 'DELETE',
        path: '/v1/dicts/:id/items/:key',
        reply: (r) => {
            if (!dict(r)) return noDict;
            const item = (ITEMS[r.params.id] ?? []).find((i) => i.key === r.params.key);
            return item ? ok({ ...itemView(item), deleted: true }) : missingKey(r.params.key);
        },
    },
    { method: 'POST', path: '/v1/dicts/:id/clear', reply: (r) => (dict(r) ? ok({ removed: dict(r)!.key_count }) : noDict) },
    {
        method: 'POST',
        path: '/v1/dicts/:id/export',
        reply: (r) => {
            const d = dict(r);
            if (!d) return noDict;
            return ok({
                object: 'operation',
                id: opId(1),
                kind: 'dict.export',
                status: 'succeeded',
                summary: d.name,
                user_id: d.user_id,
                result: exportBundle(d.name, 'dict', `dicts/${d.name}.jsonl: its keys as of one moment, one per line with its JSON value and its expiry.`),
                error: null,
                created_at: NOW,
                updated_at: NOW,
                events: [],
            });
        },
    },
    {
        method: 'DELETE',
        path: '/v1/dicts/:id',
        reply: (r) => {
            const d = dict(r);
            if (!d) return noDict;
            const app = d.used_by[0];
            if (app) return apiError(409, 'conflict', `The ${app.name} app binds ${d.name} as ${app.binding}.`, `Unbind it first: app.unbind("${app.binding}").`);
            return ok({ id: d.id, deleted: true });
        },
    },
];

const queueRoutes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/queues', reply: (r) => listed(r, QUEUES) },
    { method: 'GET', path: '/v1/queues/:id', reply: (r) => (queue(r) ? ok(queue(r)) : noQueue) },
    {
        method: 'PATCH',
        path: '/v1/queues/:id',
        reply: (r) => {
            const q = queue(r);
            return q ? ok({ ...q, max_attempts: (r.body as { max_attempts?: number })?.max_attempts ?? q.max_attempts }) : noQueue;
        },
    },
    {
        method: 'POST',
        path: '/v1/queues/:id/messages',
        reply: (r) => {
            if (!queue(r)) return noQueue;
            const messages = ((r.body ?? {}) as { messages?: { body: unknown; delay_s?: number }[] }).messages ?? [];
            if (messages.some((m) => sizeOf(m.body) > 256 * 1024)) return apiError(400, 'invalid_request', 'A message is at most 256 KB of JSON.');
            return list(
                messages.map((m, i) => ({
                    object: 'queue_message',
                    id: messageId(500 + i),
                    queue_id: r.params.id,
                    body: m.body,
                    status: m.delay_s ? 'delayed' : 'waiting',
                    attempts: 0,
                    enqueued_at: NOW,
                    visible_at: m.delay_s ? inFuture(m.delay_s * 1000) : null,
                }))
            );
        },
    },
    {
        method: 'GET',
        path: '/v1/queues/:id/messages',
        reply: (r) => {
            if (!queue(r)) return noQueue;
            if (r.set === 'error') return apiError(500, 'server_error', 'The platform API failed to answer.', 'Retry in a moment.');
            const waiting = r.params.id === queueId(1) ? INVOICE_MESSAGES : [];
            const limit = Number(r.query.get('limit') ?? 10);
            if (r.query.get('view') === 'peek') return list(waiting.slice(0, limit));
            const next = waiting.find((m) => m.status === 'waiting');
            const lease = Number(r.query.get('lease_s') ?? 60);
            return list(next ? [{ ...next, status: 'in_flight', attempts: 1, lease_id: 'lease_7fQ2', lease_expires_at: inFuture(lease * 1000) }] : []);
        },
    },
    {
        method: 'GET',
        path: '/v1/queues/:id/dead_letters',
        reply: (r) => {
            if (!queue(r)) return noQueue;
            if (r.set === 'error') return apiError(500, 'server_error', 'The platform API failed to answer.', 'Retry in a moment.');
            return list(DEAD_LETTERS[r.params.id] ?? []);
        },
    },
    { method: 'POST', path: '/v1/queues/:id/dead_letters/:message/retry', reply: (r) => (queue(r) ? { status: 204 } : noQueue) },
    { method: 'DELETE', path: '/v1/queues/:id/dead_letters/:message', reply: (r) => (queue(r) ? { status: 204 } : noQueue) },
    { method: 'GET', path: '/v1/queues/:id/depth', reply: (r) => (queue(r) ? list(depthSeries(r.params.id)) : noQueue) },
    { method: 'POST', path: '/v1/queues/:id/clear', reply: (r) => (queue(r) ? ok({ removed: queue(r)!.depth + queue(r)!.dead_letter_count }) : noQueue) },
    { method: 'POST', path: '/v1/queues/:id/export', reply: (r) => (queue(r) ? ok(queueOperation(queue(r)!)) : noQueue) },
    {
        method: 'DELETE',
        path: '/v1/queues/:id',
        reply: (r) => {
            const q = queue(r);
            if (!q) return noQueue;
            const user = q.used_by[0];
            if (user?.kind === 'agent') return apiError(409, 'conflict', `${user.name}'s OnQueue trigger reads ${q.name}.`, `Remove the trigger first: agent.remove_trigger(noclick.OnQueue("${q.name}")).`);
            if (user) return apiError(409, 'conflict', `The ${user.name} app binds ${q.name} as ${user.binding}.`, `Unbind it first: app.unbind("${user.binding}").`);
            return ok({ id: q.id, deleted: true });
        },
    },
];

export const routes: FixtureRoute[] = [...dictRoutes, ...queueRoutes];
