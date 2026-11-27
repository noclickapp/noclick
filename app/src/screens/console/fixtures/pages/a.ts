// Fixtures for Keys, Users, a user's page and Settings: the
// writes those pages make, user spend and credentials. Operations, tool
// calls, human requests, caps, policy and integrations come from b.ts and c.ts,
// so these pages run on the same rows the lab shows.
import {
    DAY,
    FIXTURE_NOW_MS,
    HOUR,
    KEYS,
    MIN,
    PAGE_ERROR,
    USERS,
    ago,
    apiError,
    fixtureAccount,
    fixtureId,
    ok,
    pageList,
    type FixtureReply,
    type FixtureRequest,
    type FixtureRoute,
} from '../core';
import { PUBLISHABLE_KEYS, publishableKeyView } from './j_webhooks';
import { PHONE_PROVIDER_CONNECTIONS } from './m_numbers';

type Json = Record<string, unknown>;

const ACME = USERS[0];
const ANA = USERS[1];
const GLOBEX = USERS[2];

/** This month's spend per user (`GET /v1/usage?group_by=user`); Globex is past its $20 cap. */
export const USER_USAGE = [
    { id: ACME.id, usd: 38.2, events: 412 },
    { id: GLOBEX.id, usd: 21.34, events: 96 },
    { id: ANA.id, usd: 0.004, events: 3 },
];

type ConnectionRow = {
    object: 'connection';
    id: string;
    name: string;
    integration: string;
    credential_type: string;
    user_id: string | null;
    status: 'pending' | 'connected' | 'disconnected';
    account: string | null;
    verification: Json | null;
    connect_link: { id: string; url: string; expires_at: string; operation_id: string } | null;
    connected_at: string | null;
    created_at: string;
    updated_at: string;
    /** Designed: agents and hosted MCP servers with it in their tools, from any scope. */
    used_by?: { kind: string; id: string; name: string; user_id: string | null }[];
};

function connection(n: number, fields: Partial<ConnectionRow> & Pick<ConnectionRow, 'name' | 'integration' | 'credential_type' | 'user_id' | 'status'>, age: number): ConnectionRow {
    const created = ago(age);
    return {
        object: 'connection',
        id: fixtureId(6, n),
        account: null,
        verification: null,
        connect_link: null,
        connected_at: fields.status === 'pending' ? null : created,
        created_at: created,
        updated_at: created,
        ...fields,
    };
}

const openLink = (n: number) => ({
    id: fixtureId(6, 80 + n),
    url: `https://noclick.com/connect/${fixtureId(6, 80 + n)}`,
    expires_at: new Date(FIXTURE_NOW_MS + 5 * DAY).toISOString(),
    operation_id: fixtureId(4, 80 + n),
});

/** Every state a connection takes: connected (proven, rejected, unverified), waiting on a link, disconnected. */
export const CONNECTIONS: ConnectionRow[] = [
    connection(1, {
        name: 'gmail', integration: 'gmail', credential_type: 'gmail_oauth', user_id: ACME.id, status: 'connected', account: 'ops@acme.test',
        verification: { reachable: true, samples: [{ label: 'ops@acme.test', value: null }], message: 'Verified as ops@acme.test.' },
    }, 18 * DAY),
    connection(2, {
        name: 'slack', integration: 'slack', credential_type: 'slack_oauth', user_id: ACME.id, status: 'connected',
        verification: { reachable: false, samples: [], message: 'invalid_auth' },
    }, 6 * DAY),
    connection(3, { name: 'stripe', integration: 'stripe', credential_type: 'stripe_api_key', user_id: ACME.id, status: 'pending', connect_link: openLink(3) }, 2 * HOUR),
    connection(4, { name: 'gmail', integration: 'gmail', credential_type: 'gmail_oauth', user_id: GLOBEX.id, status: 'disconnected' }, 30 * DAY),
    connection(5, {
        name: 'gmail', integration: 'gmail', credential_type: 'gmail_oauth', user_id: null, status: 'connected', account: 'support@yourco.test',
        verification: { reachable: true, samples: [{ label: 'support@yourco.test', value: null }], message: 'Verified as support@yourco.test.' },
        // Acme's concierge emails your support team from it (shared into its tools).
        used_by: [{ kind: 'agent', id: fixtureId(3, 2), name: 'concierge', user_id: ACME.id }],
    }, 40 * DAY),
    connection(6, { name: 'stripe', integration: 'stripe', credential_type: 'stripe_api_key', user_id: null, status: 'connected' }, 40 * DAY),
    connection(7, { name: 'gmail', integration: 'gmail', credential_type: 'gmail_oauth', user_id: ANA.id, status: 'pending', connect_link: openLink(7) }, 4 * DAY),
    // Model providers' connections (agents think with them): your Anthropic key, and Acme's OpenAI still waiting on its link.
    connection(8, {
        name: 'claude', integration: 'anthropic', credential_type: 'agent_anthropic', user_id: null, status: 'connected',
        verification: { reachable: true, samples: [], message: 'Anthropic accepted the key.' },
    }, 2 * DAY),
    connection(9, { name: 'openai', integration: 'openai', credential_type: 'agent_openai', user_id: ACME.id, status: 'pending', connect_link: openLink(9) }, HOUR),
    // GitHub, which repos export through: the account's, connected, and Acme's, still waiting on its link.
    connection(10, { name: 'github', integration: 'github', credential_type: 'github_oauth', user_id: null, status: 'connected', account: 'yourco' }, 9 * DAY),
    connection(11, { name: 'github', integration: 'github', credential_type: 'github_oauth', user_id: ACME.id, status: 'pending', connect_link: openLink(11) }, HOUR),
    // Designed: phone provider accounts whose numbers connect to NoClick.
    ...PHONE_PROVIDER_CONNECTIONS,
];

/** The raw key the lab's create returns (only ever shown in the reveal step). */
export const LAB_RAW_KEY = 'nk_live_lab5ecret0000000000000000000000000000';
export const LAB_SETUP_CODE = 'nc_setup_lab0000000000000000000000000000';
export const LAB_SESSION_TOKEN = 'nk_sess_lab.eyJ1c2VyIjoiYWNtZSJ9.signature';

/** MCP clients a person allowed on the consent page: spending within a cap, pinned to a user, and one revoked; and
 *  NoClick's assistant's own connection, revoked, which its owner restores. */
export const CONNECTED_APPS = [
    {
        object: 'connected_app',
        id: fixtureId(1, 60),
        client: { name: 'Claude', uri: 'https://claude.ai', id: 'c-claude' },
        capabilities: ['read', 'build', 'spend'],
        spend_cap_usd_per_month: 50,
        auto_approve_under_usd: 5,
        spent_usd_this_month: 12.4,
        user_id: null,
        profile: 'default',
        resource: 'https://mcp.noclick.com',
        created_at: ago(9 * DAY),
        last_used_at: ago(3 * MIN),
        revoked_at: null,
        restorable: false,
    },
    {
        object: 'connected_app',
        id: fixtureId(1, 61),
        client: { name: 'Cursor', uri: null, id: 'c-cursor' },
        capabilities: ['read', 'build', 'deploy'],
        spend_cap_usd_per_month: null,
        auto_approve_under_usd: null,
        spent_usd_this_month: 0,
        user_id: ACME.id,
        profile: 'default',
        resource: 'https://mcp.noclick.com',
        created_at: ago(2 * DAY),
        last_used_at: null,
        revoked_at: null,
        restorable: false,
    },
    {
        object: 'connected_app',
        id: fixtureId(1, 62),
        client: { name: 'ChatGPT', uri: 'https://chatgpt.com', id: 'https://chatgpt.com/connector/oauth/abc' },
        capabilities: ['read', 'spend', 'delete'],
        spend_cap_usd_per_month: 20,
        auto_approve_under_usd: null,
        spent_usd_this_month: 0,
        user_id: null,
        profile: 'openai',
        resource: 'https://mcp.noclick.com/openai',
        created_at: ago(20 * DAY),
        last_used_at: ago(6 * DAY),
        revoked_at: ago(DAY),
        restorable: false,
    },
    {
        object: 'connected_app',
        id: fixtureId(1, 63),
        client: { name: 'NoClick (your assistant)', uri: null, id: 'noclick:coordinator' },
        capabilities: ['read', 'build', 'deploy', 'spend', 'delete'],
        spend_cap_usd_per_month: 25,
        auto_approve_under_usd: null,
        spent_usd_this_month: 1.2,
        user_id: null,
        profile: 'default',
        resource: 'https://mcp.noclick.com',
        created_at: ago(30 * DAY),
        last_used_at: ago(2 * DAY),
        revoked_at: ago(HOUR),
        restorable: true,
    },
] as const;

function findUser(id: string) {
    return USERS.find((u) => u.id === id);
}

/** `user_id=` on a filtered read: all, none, or a user's id. */
function userMatches(rowUser: string | null, filter: string | null): boolean {
    if (filter === null || filter === 'all') return true;
    if (filter === 'none') return rowUser === null;
    return filter === rowUser;
}

const body = (r: FixtureRequest) => (r.body ?? {}) as Json;

export const routes: FixtureRoute[] = [
    // ── keys ────────────────────────────────────────────────────────────
    {
        method: 'POST',
        path: '/v1/cli/setup_codes',
        reply: (r) => ok({ object: 'setup_code', code: LAB_SETUP_CODE, key_name: typeof body(r).name === 'string' ? body(r).name : 'Coding agent', expires_at: new Date(FIXTURE_NOW_MS + 30 * 60_000).toISOString() }),
    },
    {
        method: 'POST',
        path: '/v1/keys',
        reply: (r) => {
            const b = body(r);
            if (b.type === 'publishable') return ok(publishableKeyView(b));
            return ok({
                object: 'key',
                id: fixtureId(1, 50),
                kind: 'api',
                type: 'secret',
                name: b.name,
                key_prefix: LAB_RAW_KEY.slice(0, 12),
                scopes: b.scopes,
                spend_cap_usd_per_month: b.spend_cap_usd_per_month ?? null,
                user_id: typeof b.user_id === 'string' ? b.user_id : null,
                created_at: new Date(FIXTURE_NOW_MS).toISOString(),
                last_used_at: null,
                expires_at: b.expires_at ?? null,
                revoked_at: null,
                raw_key: LAB_RAW_KEY,
            });
        },
    },
    {
        method: 'PATCH',
        path: '/v1/keys/:id',
        reply: (r) => {
            const key = [...KEYS, ...PUBLISHABLE_KEYS].find((k) => k.id === r.params.id);
            if (!key) return apiError(404, 'not_found', `No key ${r.params.id}.`);
            if (key.kind === 'console' && 'name' in body(r)) {
                return apiError(400, 'invalid_request', "The console key's name can't change.", 'Set only spend_cap_usd_per_month.');
            }
            return ok({ ...key, ...body(r) });
        },
    },
    {
        method: 'DELETE',
        path: '/v1/keys/:id',
        reply: (r) => {
            const key = KEYS.find((k) => k.id === r.params.id);
            if (!key) return apiError(404, 'not_found', `No key ${r.params.id}.`);
            if (key.kind === 'console') return apiError(409, 'conflict', "The console key can't be revoked; set its cap instead.");
            return ok({ ...key, revoked_at: new Date(FIXTURE_NOW_MS).toISOString() });
        },
    },

    // ── connected apps (MCP grants) ─────────────────────────────────────
    { method: 'GET', path: '/v1/connected_apps', reply: (r) => pageList(r, CONNECTED_APPS) },
    {
        method: 'DELETE',
        path: '/v1/connected_apps/:id',
        reply: (r) => {
            const app = CONNECTED_APPS.find((a) => a.id === r.params.id);
            if (!app) return apiError(404, 'not_found', `No connected app ${r.params.id}.`);
            return ok({ ...app, revoked_at: app.revoked_at ?? new Date(FIXTURE_NOW_MS).toISOString() });
        },
    },
    {
        method: 'POST',
        path: '/v1/connected_apps/:id/restore',
        reply: (r) => {
            const app = CONNECTED_APPS.find((a) => a.id === r.params.id);
            if (!app) return apiError(404, 'not_found', `No connected app ${r.params.id}.`);
            if (app.revoked_at && !app.restorable) {
                return apiError(409, 'conflict', `${app.client.name} is a client you connected, so it isn't restored: connect it again.`);
            }
            return ok({ ...app, revoked_at: null });
        },
    },

    // ── users ───────────────────────────────────────────────────────────
    {
        method: 'PATCH',
        path: '/v1/users/:id',
        reply: (r) => {
            const u = findUser(r.params.id);
            return u ? ok({ ...u, ...body(r) }) : apiError(404, 'not_found', `User ${r.params.id} not found.`);
        },
    },
    {
        method: 'DELETE',
        path: '/v1/users/:id',
        reply: (r) => {
            const u = findUser(r.params.id);
            return u ? ok({ ...u, status: 'deleted' }) : apiError(404, 'not_found', `User ${r.params.id} not found.`);
        },
    },
    {
        method: 'POST',
        path: '/v1/users/:id/suspend',
        reply: (r) => {
            const u = findUser(r.params.id);
            return u ? ok({ ...u, status: 'suspended' }) : apiError(404, 'not_found', `User ${r.params.id} not found.`);
        },
    },
    // Pausing a user's spending, with the account's default when no message is given.
    {
        method: 'POST',
        path: '/v1/users/:id/spending/pause',
        reply: (r) => {
            const u = findUser(r.params.id);
            if (!u) return apiError(404, 'not_found', `User ${r.params.id} not found.`);
            const b = body(r) as { message?: string; action?: { label: string; url: string } };
            const fallback = fixtureAccount(r.set).spending_paused;
            const message = b.message ?? fallback?.message ?? null;
            if (!message) {
                return apiError(400, 'invalid_request', 'A paused user needs a message.', 'Pass message, or set your default under Settings, Paused spending.', { field: 'message' });
            }
            const action = b.action ?? fallback?.action ?? null;
            const since = u.spending.paused ? u.spending.since : new Date(FIXTURE_NOW_MS).toISOString();
            const fill = (text: string) => text.replaceAll('{{user.id}}', u.id);
            return ok({
                ...u,
                spending: {
                    paused: true,
                    message: fill(message),
                    action: action && { label: action.label, url: fill(action.url) },
                    since,
                    held: u.spending.held,
                    paused_by: 'console',
                },
            });
        },
    },
    {
        method: 'POST',
        path: '/v1/users/:id/spending/resume',
        reply: (r) => {
            const u = findUser(r.params.id);
            if (!u) return apiError(404, 'not_found', `User ${r.params.id} not found.`);
            return ok({ ...u, spending: { paused: false, message: null, action: null, since: null, held: 0, paused_by: null } });
        },
    },
    {
        method: 'POST',
        path: '/v1/users/:id/sessions',
        reply: (r) => {
            const u = findUser(r.params.id);
            if (!u) return apiError(404, 'not_found', `User ${r.params.id} not found.`);
            if (u.status === 'suspended') return apiError(403, 'permission_denied', `User ${u.id} is suspended.`, 'Reactivate the user first.');
            const b = body(r);
            const ttl = typeof b.ttl_s === 'number' ? b.ttl_s : 3600;
            return ok({
                object: 'session',
                id: fixtureId(7, 1),
                token: LAB_SESSION_TOKEN,
                user_id: u.id,
                scopes: b.scopes,
                expires_at: new Date(FIXTURE_NOW_MS + ttl * 1000).toISOString(),
            });
        },
    },

    // ── usage by user ───────────────────────────────────────────────────
    {
        method: 'GET',
        path: '/v1/usage',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const groups = r.set === 'populated' && r.query.get('group_by') === 'user' ? USER_USAGE : [];
            return ok({
                object: 'usage',
                period: 'month',
                period_start: '2026-09-01T00:00:00+00:00',
                period_end: '2026-10-01T00:00:00+00:00',
                total_usd: groups.reduce((sum, g) => sum + g.usd, 0),
                group_by: r.query.get('group_by'),
                groups,
            });
        },
    },

    // ── connections ─────────────────────────────────────────────────────
    {
        method: 'GET',
        path: '/v1/connections',
        reply: (r) =>
            pageList(
                r,
                CONNECTIONS.filter(
                    (c) =>
                        userMatches(c.user_id, r.query.get('user_id') ?? r.headers.get('NoClick-User') ?? 'none') &&
                        (!r.query.get('integration') || c.integration === r.query.get('integration'))
                )
            ),
    },
    { method: 'POST', path: '/v1/connections', reply: (r) => created(r, { delivered_via: ['email'] }) },
    {
        method: 'POST',
        path: '/v1/connections/:ref/verify',
        reply: (r) => {
            const c = connectionByRef(r);
            if (!c) return apiError(404, 'not_found', `No connection '${r.params.ref}'.`);
            // A fresh probe returns what it listed (here channels), not the account it signed in as.
            return ok({ ...c, verification: { reachable: true, samples: [{ label: '#ops', value: 'C01' }, { label: '#general', value: 'C02' }], message: 'The provider answered with your channels.' } });
        },
    },
    {
        method: 'POST',
        path: '/v1/connections/:ref/connect_links',
        reply: (r) => {
            const c = connectionByRef(r);
            return c ? connectLink(r, c, body(r).send_to ? { delivered_via: ['email'] } : null) : apiError(404, 'not_found', `No connection '${r.params.ref}'.`);
        },
    },
    {
        // One connection by id or name (Logs reads the one a failure names, to make it a new link).
        method: 'GET',
        path: '/v1/connections/:ref',
        reply: (r) => {
            const c = connectionByRef(r);
            return c ? ok(c) : apiError(404, 'not_found', `No connection '${r.params.ref}'.`);
        },
    },
    {
        method: 'DELETE',
        path: '/v1/connections/:ref',
        reply: (r) => {
            const c = connectionByRef(r);
            return c ? ok({ object: 'connection', id: c.id, name: c.name, deleted: true }) : apiError(404, 'not_found', `No connection '${r.params.ref}'.`);
        },
    },
];

/** A connection by id or, for the acting user, by name. */
function connectionByRef(r: FixtureRequest): ConnectionRow | undefined {
    const acting = r.headers.get('NoClick-User');
    return CONNECTIONS.find((c) => c.id === r.params.ref) ?? CONNECTIONS.find((c) => c.name === r.params.ref && c.user_id === acting);
}

/** The humans service's words when a link's email fails (`humans/service.EMAIL_FAILED`). */
export const EMAIL_NOT_SENT = 'The email could not be sent.';

function linkOperation(r: FixtureRequest) {
    return {
        object: 'operation',
        id: fixtureId(4, 90),
        kind: 'credential.connect',
        status: 'awaiting_human',
        user_id: r.headers.get('NoClick-User'),
        created_at: new Date(FIXTURE_NOW_MS).toISOString(),
        updated_at: new Date(FIXTURE_NOW_MS).toISOString(),
    };
}

function connectLink(r: FixtureRequest, c: ConnectionRow, delivery: Json | null): FixtureReply {
    const link = fixtureId(6, 90);
    return ok({
        object: 'connect_link',
        id: link,
        connection: c.name,
        connection_id: c.id,
        integration: c.integration,
        url: `https://noclick.com/connect/${link}`,
        expires_at: new Date(FIXTURE_NOW_MS + DAY).toISOString(),
        ...(delivery ? { delivery } : {}),
        operation: linkOperation(r),
    });
}

/** `POST /v1/connections`: a pending connection with its open link, and how `send_to` went. */
function created(r: FixtureRequest, delivery: Json): FixtureReply {
    const b = body(r);
    const acting = r.headers.get('NoClick-User');
    if (CONNECTIONS.some((c) => c.name === b.name && c.user_id === acting)) {
        return apiError(409, 'conflict', `A connection named '${String(b.name)}' already exists.`);
    }
    const link = fixtureId(6, 90);
    const row = connection(90, {
        name: String(b.name), integration: String(b.integration), credential_type: `${String(b.integration)}_oauth`, user_id: acting, status: 'pending',
        connect_link: { id: link, url: `https://noclick.com/connect/${link}`, expires_at: new Date(FIXTURE_NOW_MS + DAY).toISOString(), operation_id: fixtureId(4, 90) },
    }, 0);
    return { status: 201, body: { ...row, ...(b.send_to ? { delivery } : {}) } };
}

/** A connection created but its link not emailed (the provider refused the send); tests pass it as a route. */
export const CONNECTION_UNDELIVERED: FixtureRoute = {
    method: 'POST',
    path: '/v1/connections',
    reply: (r) => created(r, { delivered_via: [], undelivered: [{ channel: 'email', reason: EMAIL_NOT_SENT }] }),
};
