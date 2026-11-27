// Fixtures for Databases and Storage: canned /v1 answers shaped like the API's own, filtered
// the way the routes would, so the lab and the page tests run the real client.
import { AGENTS, DAY, FIXTURE_NOW_MS, HOUR, MIN, USERS, ago, apiError, fixtureId, list, ok, pageList, type FixtureReply, type FixtureRequest, type FixtureRoute } from '../core';
import { userMatches } from './c';
// The app's id lives with the domain that serves it; e_build.ts imports this file, so importing it here would cycle.
import { BOOKING_APP_ID } from './g_domains';

const ACME = USERS[0].id;
const NOW = new Date(FIXTURE_NOW_MS).toISOString();
const GB = 1024 ** 3;
const MB = 1024 ** 2;
const KB = 1024;

/** Ids under kind digit 7: databases 5xxx, buckets 6xxx; operations 45xx. */
const rid = (group: number, n: number) => fixtureId(7, group + n);
const opId = (n: number) => fixtureId(4, 4500 + n);

// ── databases ──────────────────────────────────────────────────────────────

const BOOKING_APP = { kind: 'project', id: BOOKING_APP_ID, name: 'booking', binding: 'DB' };
/** Acme's concierge reads the bookings (its tools hold booking-db's query and schema). */
const CONCIERGE = { kind: 'agent', id: AGENTS[1].id, name: AGENTS[1].name, binding: null };

export const DATABASES = [
    {
        object: 'database',
        id: rid(5000, 1),
        name: 'booking-db',
        engine: 'sqlite',
        status: 'ready',
        size_bytes: Math.round(1.8 * GB),
        table_count: 4,
        parent_id: null,
        used_by: [BOOKING_APP, CONCIERGE],
        user_id: null,
        created_at: ago(62 * DAY),
    },
    {
        object: 'database',
        id: rid(5000, 2),
        name: 'analytics',
        engine: 'postgres',
        status: 'ready',
        size_bytes: 240 * MB,
        table_count: 3,
        parent_id: null,
        used_by: [],
        user_id: ACME,
        created_at: ago(34 * DAY),
    },
    {
        object: 'database',
        id: rid(5000, 3),
        name: 'booking-db-preview',
        engine: 'sqlite',
        status: 'ready',
        size_bytes: Math.round(1.79 * GB),
        table_count: 4,
        parent_id: rid(5000, 1),
        used_by: [],
        user_id: null,
        created_at: ago(3 * DAY),
    },
];

type Row = Record<string, string | number | null>;

interface TableFixture {
    name: string;
    row_count: number;
    columns: { name: string; type: string; nullable: boolean; primary_key: boolean; default: string | null }[];
    rows: Row[];
}

const col = (name: string, type: string, extra: { pk?: boolean; notNull?: boolean; default?: string } = {}) => ({
    name,
    type,
    nullable: !(extra.pk || extra.notNull),
    primary_key: !!extra.pk,
    default: extra.default ?? null,
});

const at = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString().replace('.000Z', 'Z');

const BOOKING_TABLES: TableFixture[] = [
    {
        name: 'bookings',
        row_count: 48210,
        columns: [
            col('id', 'TEXT', { pk: true }),
            col('venue_id', 'TEXT', { notNull: true }),
            col('customer_id', 'TEXT', { notNull: true }),
            col('party_size', 'INTEGER', { notNull: true, default: '2' }),
            col('starts_at', 'TEXT', { notNull: true }),
            col('status', 'TEXT', { notNull: true, default: "'confirmed'" }),
        ],
        rows: [
            { id: 'b_48210', venue_id: 'v_harbor', customer_id: 'c_12904', party_size: 4, starts_at: at(2 * DAY + 2 * HOUR), status: 'confirmed' },
            { id: 'b_48209', venue_id: 'v_loft', customer_id: 'c_880', party_size: 2, starts_at: at(DAY + 3 * HOUR), status: 'confirmed' },
            { id: 'b_48208', venue_id: 'v_harbor', customer_id: 'c_12901', party_size: 6, starts_at: at(DAY), status: 'pending' },
            { id: 'b_48207', venue_id: 'v_garden', customer_id: 'c_4410', party_size: 3, starts_at: at(5 * HOUR), status: 'confirmed' },
            { id: 'b_48206', venue_id: 'v_loft', customer_id: 'c_117', party_size: 2, starts_at: at(-2 * HOUR), status: 'cancelled' },
            { id: 'b_48205', venue_id: 'v_garden', customer_id: 'c_9021', party_size: 8, starts_at: at(-DAY), status: 'completed' },
        ],
    },
    {
        name: 'customers',
        row_count: 12904,
        columns: [col('id', 'TEXT', { pk: true }), col('name', 'TEXT', { notNull: true }), col('email', 'TEXT'), col('created_at', 'TEXT', { notNull: true })],
        rows: [
            { id: 'c_12904', name: 'Ana Silva', email: 'ana@example.com', created_at: at(-9 * DAY) },
            { id: 'c_12903', name: 'Bo Chen', email: 'bo@example.com', created_at: at(-10 * DAY) },
            { id: 'c_12902', name: 'Carmen Ortiz', email: null, created_at: at(-12 * DAY) },
        ],
    },
    {
        name: 'slots',
        row_count: 1344,
        columns: [col('venue_id', 'TEXT', { pk: true }), col('time', 'TEXT', { pk: true }), col('taken', 'INTEGER', { notNull: true, default: '0' })],
        rows: [
            { venue_id: 'v_harbor', time: '18:00', taken: 1 },
            { venue_id: 'v_harbor', time: '18:30', taken: 0 },
            { venue_id: 'v_loft', time: '19:00', taken: 1 },
        ],
    },
    {
        name: 'venues',
        row_count: 37,
        columns: [col('id', 'TEXT', { pk: true }), col('name', 'TEXT', { notNull: true }), col('city', 'TEXT', { notNull: true }), col('capacity', 'INTEGER')],
        rows: [
            { id: 'v_harbor', name: 'Harbor Room', city: 'Lisbon', capacity: 60 },
            { id: 'v_loft', name: 'The Loft', city: 'Porto', capacity: 24 },
            { id: 'v_garden', name: 'Garden Terrace', city: 'Lisbon', capacity: 80 },
        ],
    },
];

const ANALYTICS_TABLES: TableFixture[] = [
    {
        name: 'events',
        row_count: 2481003,
        columns: [
            col('id', 'bigint', { pk: true }),
            col('name', 'text', { notNull: true }),
            col('user_id', 'text'),
            col('properties', 'jsonb', { notNull: true, default: "'{}'::jsonb" }),
            col('at', 'timestamptz', { notNull: true, default: 'now()' }),
        ],
        rows: [
            { id: 2481003, name: 'booking.created', user_id: 'u_881', properties: '{"venue":"v_harbor"}', at: at(-4 * MIN) },
            { id: 2481002, name: 'page.viewed', user_id: 'u_881', properties: '{"path":"/venues"}', at: at(-6 * MIN) },
            { id: 2481001, name: 'page.viewed', user_id: null, properties: '{"path":"/"}', at: at(-9 * MIN) },
        ],
    },
    {
        name: 'sessions',
        row_count: 310442,
        columns: [col('id', 'uuid', { pk: true }), col('user_id', 'text'), col('started_at', 'timestamptz', { notNull: true }), col('pages', 'integer', { notNull: true, default: '0' })],
        rows: [
            { id: '5c1e0f2a-7b3d-4e8a-9c21-0f6d2b8a4e17', user_id: 'u_881', started_at: at(-12 * MIN), pages: 7 },
            { id: '8a2f3c4d-1e6b-4f0a-b7c9-2d5e8f1a3b60', user_id: null, started_at: at(-30 * MIN), pages: 1 },
        ],
    },
    {
        name: 'daily_rollups',
        row_count: 1280,
        columns: [col('day', 'date', { pk: true }), col('metric', 'text', { pk: true }), col('value', 'numeric', { notNull: true })],
        rows: [
            { day: '2026-09-25', metric: 'bookings', value: 412 },
            { day: '2026-09-25', metric: 'visitors', value: 9120 },
        ],
    },
];

const TABLES: Record<string, TableFixture[]> = {
    [rid(5000, 1)]: BOOKING_TABLES,
    [rid(5000, 2)]: ANALYTICS_TABLES,
    [rid(5000, 3)]: BOOKING_TABLES,
};

const MIGRATIONS: Record<string, { name: string; applied_at: string; checksum: string }[]> = {
    [rid(5000, 1)]: [
        { name: '0001_init.sql', applied_at: ago(62 * DAY), checksum: 'sha256:9f2c41d7' },
        { name: '0002_add_slots.sql', applied_at: ago(40 * DAY), checksum: 'sha256:1b7e03aa' },
        { name: '0003_customer_email.sql', applied_at: ago(6 * DAY), checksum: 'sha256:c4d8e912' },
    ],
    [rid(5000, 2)]: [{ name: '0001_events.sql', applied_at: ago(34 * DAY), checksum: 'sha256:77a0b5e1' }],
};

const tablesOf = (id: string) => TABLES[id] ?? [];

function tableView(t: TableFixture) {
    return { object: 'table', name: t.name, row_count: t.row_count, columns: t.columns };
}

/** A read-only `select` against the canned rows: `from <table>`, `count(*)` and `limit n`. */
function runQuery(r: FixtureRequest): FixtureReply {
    const body = (r.body ?? {}) as { sql?: string; read_only?: boolean; statements?: unknown[] };
    const sql = String(body.sql ?? '').trim();
    if (body.statements || !/^(select|with)\b/i.test(sql)) {
        return apiError(400, 'invalid_request', 'query() runs read-only, and this statement writes.', 'Run writes with db.execute(...).');
    }
    const from = /\bfrom\s+"?([\w.]+)"?/i.exec(sql)?.[1];
    const table = tablesOf(r.params.id).find((t) => t.name === from?.split('.').pop());
    if (from && !table) return apiError(400, 'invalid_request', `no such table: ${from}`);
    const started = { rows_written: 0, last_row_id: null, duration_ms: 3.2 };
    if (!table) return ok({ object: 'query_result', columns: ['?column?'], rows: [{ '?column?': 1 }], rows_read: 0, ...started });
    if (/count\(\*\)/i.test(sql)) {
        const alias = /count\(\*\)\s+as\s+(\w+)/i.exec(sql)?.[1] ?? 'count';
        return ok({ object: 'query_result', columns: [alias], rows: [{ [alias]: table.row_count }], rows_read: table.row_count, ...started });
    }
    const limit = Number(/\blimit\s+(\d+)/i.exec(sql)?.[1] ?? table.rows.length);
    const rows = table.rows.slice(0, limit);
    return ok({ object: 'query_result', columns: table.columns.map((c) => c.name), rows, rows_read: rows.length, ...started });
}

function databaseOperation(n: number, kind: string, db: (typeof DATABASES)[number], status: string, summary: string, result: unknown = null) {
    return {
        object: 'operation',
        id: opId(n),
        kind,
        status,
        summary,
        user_id: db.user_id,
        result,
        error: null,
        created_at: NOW,
        updated_at: NOW,
        events: [{ status, at: NOW, by: null }],
    };
}

function exportBundle(name: string, kind: 'database' | 'files', detail: string) {
    return {
        object: 'export',
        url: `https://exports.noclick.test/${name}-2026-09-26.zip`,
        expires_at: new Date(FIXTURE_NOW_MS + 7 * DAY).toISOString(),
        size_bytes: 482_133,
        contents: [{ kind, name, detail }],
        remaining_dependencies: [],
    };
}

// ── buckets ────────────────────────────────────────────────────────────────

export const BUCKETS = [
    {
        object: 'bucket',
        id: rid(6000, 1),
        name: 'uploads',
        public: false,
        size_bytes: Math.round(42.1 * GB),
        object_count: 18204,
        public_base_url: null,
        used_by: [{ ...BOOKING_APP, binding: 'FILES' }],
        // Designed: new files under a prefix become queue messages.
        notifications: [{ queue: 'transcribe', prefix: 'recordings/' }],
        user_id: null,
        created_at: ago(62 * DAY),
    },
    {
        object: 'bucket',
        id: rid(6000, 2),
        name: 'public-assets',
        public: true,
        size_bytes: Math.round(86.4 * MB),
        object_count: 412,
        public_base_url: 'https://files.noclick.site/acme-public-assets',
        used_by: [],
        user_id: ACME,
        created_at: ago(21 * DAY),
    },
];

interface ObjectFixture {
    key: string;
    size: number;
    content_type: string;
    updated_at: string;
    metadata?: Record<string, string>;
}

const file = (key: string, size: number, content_type: string, age: number, metadata: Record<string, string> = {}): ObjectFixture => ({
    key,
    size,
    content_type,
    updated_at: ago(age),
    metadata,
});

const OBJECTS: Record<string, ObjectFixture[]> = {
    [rid(6000, 1)]: [
        file('avatars/c_117.jpg', 61 * KB, 'image/jpeg', 30 * DAY),
        file('avatars/c_12904.png', 48 * KB, 'image/png', 9 * DAY),
        file('exports/bookings-2026-08.csv', Math.round(11.2 * MB), 'text/csv', 26 * DAY),
        file('exports/bookings-2026-09.csv', Math.round(12.4 * MB), 'text/csv', 20 * HOUR, { source: 'nightly' }),
        file('invoices/2026-08/0031.pdf', 88 * KB, 'application/pdf', 40 * DAY, { user: 'acme' }),
        file('invoices/2026-09/0041.pdf', 91 * KB, 'application/pdf', 6 * DAY, { user: 'acme' }),
        file('invoices/2026-09/0042.pdf', 94 * KB, 'application/pdf', 2 * DAY, { user: 'acme' }),
        file('invoices/2026-09/0043.pdf', 90 * KB, 'application/pdf', 3 * HOUR, { user: 'user_42' }),
        file('receipts/b_48205.pdf', 32 * KB, 'application/pdf', DAY),
        file('receipts/b_48207.pdf', 31 * KB, 'application/pdf', 40 * MIN),
        file('terms.pdf', 212 * KB, 'application/pdf', 55 * DAY),
    ],
    [rid(6000, 2)]: [
        file('css/status.css', 14 * KB, 'text/css', 4 * DAY),
        file('fonts/inter-var.woff2', 318 * KB, 'font/woff2', 21 * DAY),
        file('logo-dark.svg', 3 * KB, 'image/svg+xml', 21 * DAY),
        file('logo.png', 22 * KB, 'image/png', 21 * DAY),
        file('og/cover.png', 410 * KB, 'image/png', 12 * DAY),
    ],
};

function objectView(o: ObjectFixture) {
    return { object: 'bucket_object', key: o.key, size: o.size, content_type: o.content_type, etag: `"${o.key.length.toString(16)}${o.size.toString(16)}"`, metadata: o.metadata ?? {}, updated_at: o.updated_at };
}

/** `?prefix=&delimiter=/`: files right under the prefix and one folder entry per deeper prefix, in key order; `cursor` is an offset. */
function listObjects(r: FixtureRequest, bucketId: string): FixtureReply {
    if (r.set === 'error') return apiError(500, 'server_error', 'The platform API failed to answer.', 'Retry in a moment.');
    const prefix = r.query.get('prefix') ?? '';
    const delimiter = r.query.get('delimiter');
    const entries: unknown[] = [];
    const folders = new Set<string>();
    for (const o of OBJECTS[bucketId] ?? []) {
        if (!o.key.startsWith(prefix)) continue;
        const rest = o.key.slice(prefix.length);
        const cut = delimiter ? rest.indexOf(delimiter) : -1;
        if (cut >= 0) {
            const folder = prefix + rest.slice(0, cut + delimiter!.length);
            if (!folders.has(folder)) {
                folders.add(folder);
                entries.push({ object: 'bucket_object', key: folder, folder: true });
            }
        } else entries.push(objectView(o));
    }
    const start = Number(r.query.get('cursor') ?? 0);
    const limit = Number(r.query.get('limit') ?? 100);
    const page = entries.slice(start, start + limit);
    return list(page, start + limit < entries.length ? String(start + limit) : null);
}

const S3_CREDENTIALS = (bucket: (typeof BUCKETS)[number], readOnly: boolean, ttlS: number) => ({
    object: 's3_credentials',
    endpoint: 'https://s3.noclick.test',
    bucket: `nc-${bucket.name}-7f3a`,
    access_key_id: 'NCLABLABLABLABLABLAB',
    secret_access_key: 'LABLABLABLABLABLABLABLABLABLABLABLABLABL',
    session_token: 'LABLABLABLABLABLABLABLABLABLABLABLABLABLABLABLABLABLABL',
    region: 'auto',
    read_only: readOnly,
    expires_at: new Date(FIXTURE_NOW_MS + ttlS * 1000).toISOString(),
});

// ── routes ─────────────────────────────────────────────────────────────────

function listed<T extends { user_id: string | null }>(r: FixtureRequest, rows: readonly T[]): FixtureReply {
    return pageList(r, rows.filter((row) => userMatches(r.query, row.user_id)));
}

function found<T>(row: T | undefined, what: string): FixtureReply {
    return row ? ok(row) : apiError(404, 'not_found', `No such ${what}.`);
}

const database = (r: FixtureRequest) => DATABASES.find((d) => d.id === r.params.id);
const bucket = (r: FixtureRequest) => BUCKETS.find((b) => b.id === r.params.id);

const databaseRoutes: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/databases',
        reply: (r) => {
            const engine = r.query.get('engine');
            const name = r.query.get('name');
            return listed(r, DATABASES.filter((d) => (!engine || d.engine === engine) && (!name || d.name === name)));
        },
    },
    { method: 'GET', path: '/v1/databases/:id', reply: (r) => found(database(r), 'database') },
    { method: 'POST', path: '/v1/databases/:id/query', reply: (r) => (database(r) ? runQuery(r) : apiError(404, 'not_found', 'No such database.')) },
    { method: 'GET', path: '/v1/databases/:id/schema', reply: (r) => (database(r) ? list(tablesOf(r.params.id).map(tableView)) : apiError(404, 'not_found', 'No such database.')) },
    { method: 'GET', path: '/v1/databases/:id/migrations', reply: (r) => list((MIGRATIONS[r.params.id] ?? []).map((m) => ({ object: 'migration', ...m }))) },
    { method: 'GET', path: '/v1/databases/:id/branches', reply: (r) => list(DATABASES.filter((d) => d.parent_id === r.params.id)) },
    {
        method: 'POST',
        path: '/v1/databases/:id/branches',
        reply: (r) => {
            const db = database(r);
            if (!db) return apiError(404, 'not_found', 'No such database.');
            const body = (r.body ?? {}) as { name: string; engine?: string; at?: string };
            if (DATABASES.some((d) => d.name === body.name && d.user_id === db.user_id)) {
                return apiError(409, 'conflict', `A database named ${body.name} already exists.`, 'Pick another name for the branch.');
            }
            return { status: 202, body: databaseOperation(1, 'database.branch', db, 'running', `${db.name} → ${body.name}`) };
        },
    },
    {
        method: 'POST',
        path: '/v1/databases/:id/restore',
        reply: (r) => {
            const db = database(r);
            if (!db) return apiError(404, 'not_found', 'No such database.');
            const when = String((r.body as { at?: string })?.at ?? '');
            const days = db.engine === 'postgres' ? 7 : 30;
            const engine = db.engine === 'postgres' ? 'Postgres' : 'SQLite';
            if (Date.parse(when) < FIXTURE_NOW_MS - days * DAY) return apiError(400, 'invalid_request', `A ${engine} database keeps ${days} days of history.`, `Pick a time within the last ${days} days.`);
            return { status: 202, body: databaseOperation(2, 'database.restore', db, 'running', `${db.name} to ${when}`) };
        },
    },
    {
        method: 'POST',
        path: '/v1/databases/:id/export',
        reply: (r) => {
            const db = database(r);
            if (!db) return apiError(404, 'not_found', 'No such database.');
            const detail = `SQL (schema and data) that loads into any ${db.engine === 'sqlite' ? 'SQLite' : 'Postgres'} database.`;
            return ok(databaseOperation(3, 'database.export', db, 'succeeded', db.name, exportBundle(db.name, 'database', detail)));
        },
    },
    {
        method: 'POST',
        path: '/v1/databases/:id/connection_url',
        reply: (r) => {
            const db = database(r);
            if (!db) return apiError(404, 'not_found', 'No such database.');
            if (db.engine === 'sqlite') return apiError(409, 'not_available', 'A SQLite database has no connection URL.', 'Use db.query and db.execute, or branch it into Postgres.');
            const ttl = Number((r.body as { ttl_s?: number })?.ttl_s ?? 3600);
            return ok({ url: `postgresql://nc_ro_7f3a:pw_2kQ9@pg.noclick.test:5432/${db.name}?sslmode=require`, expires_at: new Date(FIXTURE_NOW_MS + ttl * 1000).toISOString() });
        },
    },
    {
        method: 'DELETE',
        path: '/v1/databases/:id',
        reply: (r) => {
            const db = database(r);
            if (!db) return apiError(404, 'not_found', 'No such database.');
            const app = db.used_by[0];
            if (app) return apiError(409, 'conflict', `The ${app.name} app binds ${db.name} as ${app.binding}.`, `Unbind it first: app.unbind("${app.binding}").`);
            return ok({ id: db.id, deleted: true });
        },
    },
];

const bucketRoutes: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/buckets',
        reply: (r) => {
            const name = r.query.get('name');
            return listed(r, BUCKETS.filter((b) => !name || b.name === name));
        },
    },
    { method: 'GET', path: '/v1/buckets/:id', reply: (r) => found(bucket(r), 'bucket') },
    {
        method: 'PATCH',
        path: '/v1/buckets/:id',
        reply: (r) => {
            const b = bucket(r);
            if (!b) return apiError(404, 'not_found', 'No such bucket.');
            const open = (r.body as { public?: boolean })?.public ?? b.public;
            return ok({ ...b, public: open, public_base_url: open ? (b.public_base_url ?? `https://files.noclick.site/${b.name}`) : null });
        },
    },
    {
        method: 'GET',
        path: '/v1/buckets/:id/objects',
        reply: (r) => {
            const b = bucket(r);
            if (!b) return apiError(404, 'not_found', 'No such bucket.');
            const key = r.query.get('key');
            if (key === null) return listObjects(r, b.id);
            const o = (OBJECTS[b.id] ?? []).find((x) => x.key === key);
            if (!o) return apiError(404, 'not_found', `No file at ${key}.`);
            return ok(r.query.get('view') === 'metadata' ? objectView(o) : `contents of ${key}`);
        },
    },
    {
        method: 'POST',
        path: '/v1/buckets/:id/signed_urls',
        reply: (r) => {
            const b = bucket(r);
            const body = (r.body ?? {}) as { key: string; method?: string; expires_in?: number };
            if (!b) return apiError(404, 'not_found', 'No such bucket.');
            const expires = new Date(FIXTURE_NOW_MS + (body.expires_in ?? 3600) * 1000).toISOString();
            return ok({ url: `https://files.noclick.site/s/${b.name}/${encodeURI(body.key)}?sig=3c9f1a7e&expires=${Date.parse(expires) / 1000}`, method: body.method ?? 'GET', expires_at: expires });
        },
    },
    {
        method: 'POST',
        path: '/v1/buckets/:id/s3_credentials',
        reply: (r) => {
            const b = bucket(r);
            if (!b) return apiError(404, 'not_found', 'No such bucket.');
            const body = (r.body ?? {}) as { read_only?: boolean; ttl_s?: number };
            return ok(S3_CREDENTIALS(b, !!body.read_only, body.ttl_s ?? 3600));
        },
    },
    {
        method: 'POST',
        path: '/v1/buckets/:id/export',
        reply: (r) => {
            const b = bucket(r);
            if (!b) return apiError(404, 'not_found', 'No such bucket.');
            return ok({
                object: 'operation',
                id: opId(4),
                kind: 'bucket.export',
                status: 'succeeded',
                summary: b.name,
                user_id: b.user_id,
                result: exportBundle(b.name, 'files', `buckets/${b.name}/: the bucket's files under files/ at their keys; index.jsonl lists each key with its content type and metadata.`),
                error: null,
                created_at: NOW,
                updated_at: NOW,
                events: [],
            });
        },
    },
    {
        method: 'DELETE',
        path: '/v1/buckets/:id',
        reply: (r) => {
            const b = bucket(r);
            if (!b) return apiError(404, 'not_found', 'No such bucket.');
            const app = b.used_by[0];
            if (app) return apiError(409, 'conflict', `The ${app.name} app binds ${b.name} as ${app.binding}.`, `Unbind it first: app.unbind("${app.binding}").`);
            if (b.object_count > 0 && r.query.get('force') !== 'true') {
                return apiError(409, 'conflict', `${b.name} holds ${b.object_count.toLocaleString('en-US')} files.`, 'Delete them first, or pass force=True to delete them with it.');
            }
            return ok({ id: b.id, deleted: true });
        },
    },
];

export const routes: FixtureRoute[] = [...databaseRoutes, ...bucketRoutes];
