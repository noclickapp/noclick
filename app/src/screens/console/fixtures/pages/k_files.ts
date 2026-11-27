// Fixtures for Volumes and Secrets: canned /v1 answers shaped like the API's own, filtered the way the routes
// would, so the lab and the page tests run the real client. Values are write-only here too:
// a secret's answers carry key names and never a value.
import { AGENTS, DAY, FIXTURE_NOW_MS, HOUR, MIN, USERS, ago, apiError, fixtureId, list, ok, pageList, type FixtureReply, type FixtureRequest, type FixtureRoute } from '../core';
import { SANDBOXES, userMatches } from './c';
import { BOOKING_APP_ID } from './g_domains';

const ACME = USERS[0].id;
const NOW = new Date(FIXTURE_NOW_MS).toISOString();
const GB = 1024 ** 3;
const MB = 1024 ** 2;
const KB = 1024;

/** Ids under kind digit 7: volumes 111_0xx, secrets 112_0xx; operations 111_0xx under kind 4. */
const vid = (n: number) => fixtureId(7, 111_000 + n);
const sid = (n: number) => fixtureId(7, 112_000 + n);
const opId = (n: number) => fixtureId(4, 111_000 + n);

/** Ana's `assistant` (the account's `datasets` and `openai` are hers to use too). */
const ANA_ASSISTANT = AGENTS.find((a) => a.name === 'assistant' && a.user_id === USERS[1].id)!;
/** Acme's running sandbox. */
const LIVE_SANDBOX = SANDBOXES.find((s) => s.status === 'running')!;

// ── volumes ────────────────────────────────────────────────────────────────

export const VOLUMES = [
    {
        object: 'volume',
        id: vid(1),
        name: 'datasets',
        size_bytes: Math.round(12.4 * GB),
        file_count: 1840,
        mounted_by: [
            { kind: 'agent', id: ANA_ASSISTANT.id, name: 'assistant', path: '/data' },
            { kind: 'sandbox', id: LIVE_SANDBOX.id, name: null, path: '/data' },
        ],
        user_id: null,
        created_at: ago(48 * DAY),
    },
    {
        object: 'volume',
        id: vid(2),
        name: 'acme-exports',
        size_bytes: Math.round(386 * MB),
        file_count: 214,
        mounted_by: [] as { kind: string; id: string; name: string | null; path: string }[],
        user_id: ACME,
        created_at: ago(15 * DAY),
    },
];

interface FileFixture {
    path: string;
    size: number;
    updated_at: string;
}

const file = (path: string, size: number, age: number): FileFixture => ({ path, size, updated_at: ago(age) });

/** A sample of each volume's files (the counts above are the whole volume's). */
export const VOLUME_FILES: Record<string, FileFixture[]> = {
    [vid(1)]: [
        file('/README.md', 2 * KB, 30 * DAY),
        file('/charts/bookings-by-venue.png', 184 * KB, 3 * HOUR),
        file('/charts/party-size.png', 142 * KB, 3 * HOUR),
        file('/models/demand-v3.bin', Math.round(1.9 * GB), 4 * DAY),
        file('/raw/orders-2026-08.csv', Math.round(410 * MB), 26 * DAY),
        file('/raw/orders-2026-09.csv', Math.round(388 * MB), 20 * HOUR),
        file('/raw/venues.json', 96 * KB, 12 * DAY),
        file('/raw/weather/lisbon.parquet', Math.round(64 * MB), 9 * DAY),
        file('/raw/weather/porto.parquet', Math.round(58 * MB), 9 * DAY),
    ],
    [vid(2)]: [
        file('/exports/2026-08/invoices.csv', Math.round(2.1 * MB), 27 * DAY),
        file('/exports/2026-09/invoices.csv', Math.round(2.4 * MB), 40 * MIN),
        file('/exports/2026-09/ledger.xlsx', Math.round(6.8 * MB), 40 * MIN),
    ],
};

/** `/raw/weather/porto.parquet` → `["/raw", "/raw/weather"]`. */
function folders(path: string): string[] {
    const parts = path.split('/').filter(Boolean).slice(0, -1);
    return parts.map((_, i) => `/${parts.slice(0, i + 1).join('/')}`);
}

function entryOf(path: string, files: FileFixture[]) {
    const f = files.find((x) => x.path === path);
    if (f) return { object: 'volume_entry', path, type: 'file', size: f.size, updated_at: f.updated_at };
    const under = files.filter((x) => x.path.startsWith(`${path}/`)).map((x) => x.updated_at);
    return { object: 'volume_entry', path, type: 'directory', size: null, updated_at: under.sort().at(-1) ?? null };
}

/** `?view=list&path=&recursive=`: what's in the folder (or everything below it), in path order; `cursor` is an offset. */
function listFiles(r: FixtureRequest, volumeId: string): FixtureReply {
    if (r.set === 'error') return apiError(500, 'server_error', 'The platform API failed to answer.', 'Retry in a moment.');
    const files = r.set === 'populated' ? (VOLUME_FILES[volumeId] ?? []) : [];
    const root = (r.query.get('path') ?? '/').replace(/\/+$/, '');
    const recursive = r.query.get('recursive') === 'true';
    const all = new Set<string>();
    for (const f of files) [...folders(f.path), f.path].forEach((p) => all.add(p));
    if (root && !all.has(root)) return apiError(404, 'not_found', `Nothing at ${root}.`);
    const below = [...all].filter((p) => p.startsWith(`${root}/`) && (recursive || !p.slice(root.length + 1).includes('/'))).sort();
    const start = Number(r.query.get('cursor') ?? 0);
    const limit = Number(r.query.get('limit') ?? 100);
    const page = below.slice(start, start + limit).map((p) => entryOf(p, files));
    return list(page, start + limit < below.length ? String(start + limit) : null);
}

function exportOperation(n: number, kind: string, name: string, userId: string | null, detail: string) {
    return {
        object: 'operation',
        id: opId(n),
        kind,
        status: 'succeeded',
        summary: name,
        user_id: userId,
        result: {
            object: 'export',
            url: `https://exports.noclick.test/${name}-2026-09-26.zip`,
            expires_at: new Date(FIXTURE_NOW_MS + 7 * DAY).toISOString(),
            size_bytes: 482_133,
            contents: [{ kind: 'files', name, detail }],
            remaining_dependencies: [],
        },
        error: null,
        created_at: NOW,
        updated_at: NOW,
        events: [],
    };
}

// ── secrets ────────────────────────────────────────────────────────────────

export const SECRETS = [
    {
        object: 'secret',
        id: sid(1),
        name: 'openai',
        keys: ['OPENAI_API_KEY'],
        user_id: null,
        used_by: [
            { kind: 'agent', id: ANA_ASSISTANT.id, name: 'assistant', binding: null },
            { kind: 'sandbox', id: LIVE_SANDBOX.id, name: null, binding: null },
        ],
        created_at: ago(40 * DAY),
        updated_at: ago(6 * DAY),
    },
    {
        object: 'secret',
        id: sid(2),
        name: 'shipping',
        keys: ['SHIPPING_API_KEY'],
        user_id: null,
        used_by: [{ kind: 'project', id: BOOKING_APP_ID, name: 'booking', binding: 'SHIPPING' }],
        created_at: ago(20 * DAY),
        updated_at: ago(20 * DAY),
    },
    {
        object: 'secret',
        id: sid(3),
        name: 'acme-erp',
        keys: ['ERP_PASSWORD', 'ERP_USER'],
        user_id: ACME,
        used_by: [] as { kind: string; id: string; name: string; binding: string | null }[],
        created_at: ago(9 * DAY),
        updated_at: ago(2 * DAY),
    },
    // Designed: the account's own Google OAuth app, which the Brand fixture names.
    {
        object: 'secret',
        id: sid(4),
        name: 'google-oauth',
        keys: ['CLIENT_ID', 'CLIENT_SECRET'],
        user_id: null,
        used_by: [] as { kind: string; id: string; name: string; binding: string | null }[],
        created_at: ago(12 * DAY),
        updated_at: ago(12 * DAY),
    },
];

/** The names NoClick sets in every sandbox and agent shell. */
export function reservedKey(key: string): boolean {
    return ['PATH', 'HOME', 'PYTHONPATH'].includes(key) || key.startsWith('LD_') || key.startsWith('NOCLICK_');
}

const MAX_VALUE = 64 * KB;

/** Why a set of values can't be saved, as the API would refuse it, or null. */
function refusal(values: Record<string, string | null>): FixtureReply | null {
    for (const [key, value] of Object.entries(values)) {
        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) return apiError(400, 'invalid_request', `${key || 'An empty name'} isn't an environment variable name.`, 'Use letters, digits and _, not starting with a digit.');
        if (reservedKey(key)) return apiError(400, 'invalid_request', `${key} is reserved: NoClick sets it in every sandbox and agent shell.`, 'Pick another name.');
        if (value !== null && value.length > MAX_VALUE) return apiError(400, 'invalid_request', `The value of ${key} is over 64 KB.`);
    }
    return Object.keys(values).length > 100 ? apiError(400, 'invalid_request', 'A secret holds at most 100 keys.') : null;
}

// ── routes ─────────────────────────────────────────────────────────────────

/** A list read: with `user_id`, the users it names; acting for a user (header), their rows and the account's. */
function listed<T extends { user_id: string | null; name: string }>(r: FixtureRequest, rows: readonly T[]): FixtureReply {
    const name = r.query.get('name');
    const acting = r.headers.get('NoClick-User');
    const visible = rows.filter((row) => (!name || row.name === name) && (r.query.has('user_id') || !acting ? userMatches(r.query, row.user_id) : row.user_id === acting || row.user_id === null));
    return pageList(r, visible);
}

function found<T>(row: T | undefined, what: string): FixtureReply {
    return row ? ok(row) : apiError(404, 'not_found', `No such ${what}.`);
}

const volume = (r: FixtureRequest) => VOLUMES.find((v) => v.id === r.params.id);
const secret = (r: FixtureRequest) => SECRETS.find((s) => s.id === r.params.id);

const volumeRoutes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/volumes', reply: (r) => listed(r, VOLUMES) },
    { method: 'GET', path: '/v1/volumes/:id', reply: (r) => found(volume(r), 'volume') },
    {
        method: 'GET',
        path: '/v1/volumes/:id/files',
        reply: (r) => {
            const v = volume(r);
            if (!v) return apiError(404, 'not_found', 'No such volume.');
            if (r.query.get('view') === 'list') return listFiles(r, v.id);
            const path = r.query.get('path') ?? '';
            const f = (VOLUME_FILES[v.id] ?? []).find((x) => x.path === path);
            if (!f) return apiError(404, 'not_found', `No file at ${path}.`);
            return { status: 200, raw: `contents of ${path}` };
        },
    },
    {
        method: 'PUT',
        path: '/v1/volumes/:id/files',
        reply: (r) => (volume(r) ? ok({ object: 'volume_entry', path: r.query.get('path'), type: 'file', size: 0, updated_at: NOW }) : apiError(404, 'not_found', 'No such volume.')),
    },
    { method: 'DELETE', path: '/v1/volumes/:id/files', reply: (r) => (volume(r) ? { status: 204 } : apiError(404, 'not_found', 'No such volume.')) },
    {
        method: 'POST',
        path: '/v1/volumes/:id/copy',
        reply: (r) => {
            const v = volume(r);
            const body = (r.body ?? {}) as { src?: string; dst?: string };
            if (!v) return apiError(404, 'not_found', 'No such volume.');
            const src = (VOLUME_FILES[v.id] ?? []).find((x) => x.path === body.src);
            return ok({ object: 'volume_entry', path: body.dst, type: src ? 'file' : 'directory', size: src?.size ?? null, updated_at: NOW });
        },
    },
    {
        method: 'POST',
        path: '/v1/volumes/:id/export',
        reply: (r) => {
            const v = volume(r);
            if (!v) return apiError(404, 'not_found', 'No such volume.');
            return ok(exportOperation(v === VOLUMES[0] ? 1 : 2, 'volume.export', v.name, v.user_id, `volumes/${v.name}/: the volume's files under files/ in their folders; index.jsonl lists each path with its size and when it last changed.`));
        },
    },
    {
        method: 'DELETE',
        path: '/v1/volumes/:id',
        reply: (r) => {
            const v = volume(r);
            if (!v) return apiError(404, 'not_found', 'No such volume.');
            const agent = v.mounted_by.find((m) => m.kind === 'agent');
            if (agent) return apiError(409, 'conflict', `The ${agent.name} agent mounts ${v.name} at ${agent.path}.`, "Take it out of the agent's volumes first.");
            if (v.mounted_by.length) return apiError(409, 'conflict', `A running sandbox mounts ${v.name}.`, 'Let it end, or terminate it, first.');
            return { status: 204 };
        },
    },
];

const secretRoutes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/secrets', reply: (r) => listed(r, SECRETS) },
    { method: 'GET', path: '/v1/secrets/:id', reply: (r) => found(secret(r), 'secret') },
    {
        method: 'POST',
        path: '/v1/secrets',
        reply: (r) => {
            const body = (r.body ?? {}) as { name: string; values?: Record<string, string> };
            const user = r.headers.get('NoClick-User');
            const taken = SECRETS.find((s) => s.name === body.name && s.user_id === user);
            if (taken) return apiError(409, 'conflict', `A secret named ${body.name} already exists.`, 'Use Secret.from_name to reach it, or pick another name.', { existing_id: taken.id });
            const refused = refusal(body.values ?? {});
            if (refused) return refused;
            return ok({ ...SECRETS[2], id: sid(9), name: body.name, keys: Object.keys(body.values ?? {}).sort(), used_by: [], user_id: user, created_at: NOW, updated_at: NOW });
        },
    },
    {
        method: 'PATCH',
        path: '/v1/secrets/:id',
        reply: (r) => {
            const s = secret(r);
            if (!s) return apiError(404, 'not_found', 'No such secret.');
            const body = (r.body ?? {}) as { values?: Record<string, string | null>; replace?: boolean };
            const values = body.values ?? {};
            const refused = refusal(values);
            if (refused) return refused;
            const kept = body.replace ? [] : s.keys;
            const keys = new Set([...kept, ...Object.keys(values).filter((k) => values[k] !== null)]);
            for (const [k, v] of Object.entries(values)) if (v === null) keys.delete(k);
            return ok({ ...s, keys: [...keys].sort(), updated_at: NOW });
        },
    },
    {
        method: 'DELETE',
        path: '/v1/secrets/:id',
        reply: (r) => {
            const s = secret(r);
            if (!s) return apiError(404, 'not_found', 'No such secret.');
            const app = s.used_by.find((u) => u.kind === 'project');
            if (app) return apiError(409, 'conflict', `The ${app.name} app binds ${s.name} as ${app.binding}.`, `Unbind it first: app.unbind("${app.binding}").`);
            const agent = s.used_by.find((u) => u.kind === 'agent');
            if (agent) return apiError(409, 'conflict', `The ${agent.name} agent uses ${s.name}.`, "Take it out of the agent's secrets first.");
            return { status: 204 };
        },
    },
];

export const routes: readonly FixtureRoute[] = [...volumeRoutes, ...secretRoutes];
