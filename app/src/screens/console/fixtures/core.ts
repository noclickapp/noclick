// Shared fixtures for the lab and the tests: a fixed clock, the account in each
// fixture set, and the objects every page refers to (users, agents, keys).
// Pages add their own endpoints in `pages/*.ts` and import these for consistency.

export type FixtureSet = 'populated' | 'empty' | 'first-run' | 'error';

export const FIXTURE_SETS: readonly FixtureSet[] = ['populated', 'empty', 'first-run', 'error'];

export function parseFixtureSet(value: string | null | undefined): FixtureSet {
    return FIXTURE_SETS.includes(value as FixtureSet) ? (value as FixtureSet) : 'populated';
}

export const FIXTURE_NOW = '2026-09-26T16:20:05.000Z';
export const FIXTURE_NOW_MS = Date.parse(FIXTURE_NOW);

/** An ISO time `ms` before the fixture clock. */
export function ago(ms: number): string {
    return new Date(FIXTURE_NOW_MS - ms).toISOString();
}

export const MIN = 60_000;
export const HOUR = 60 * MIN;
export const DAY = 24 * HOUR;

/** A stable UUID per (kind digit, n): `fixtureId(3, 7)` → `30000000-0000-4000-8000-000000000007`. */
export function fixtureId(kind: number, n: number): string {
    return `${kind}0000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
}

export const FIXTURE_USER = { id: fixtureId(9, 1), email: 'dev@acme.test' };

export interface FixtureRequest {
    set: FixtureSet;
    method: string;
    path: string;
    params: Record<string, string>;
    query: URLSearchParams;
    headers: Headers;
    body: unknown;
}

export interface FixtureReply {
    status?: number;
    body?: unknown;
    /** Bytes or text sent as they are (a file read), instead of `body` as JSON. */
    raw?: string | Uint8Array;
    headers?: Record<string, string>;
}

export interface FixtureRoute {
    method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
    /** `/v1/agents/:id`; `:name` matches one segment. */
    path: string;
    /** A promise holds the answer back (a test's slow read). */
    reply: (request: FixtureRequest) => FixtureReply | Promise<FixtureReply>;
}

export function ok(body: unknown): FixtureReply {
    return { status: 200, body };
}

export function list(data: readonly unknown[], nextCursor: string | null = null): FixtureReply {
    return ok({ object: 'list', data, next_cursor: nextCursor });
}

export function apiError(status: number, type: string, message: string, nextStep?: string, details: Record<string, unknown> = {}): FixtureReply {
    return { status, body: { error: { type, message, ...(nextStep ? { next_step: nextStep } : {}), ...details } } };
}

/** What the `error` set answers for a page's reads. */
export const PAGE_ERROR = apiError(500, 'server_error', 'The platform API failed to answer.', 'Retry in a moment; if it keeps failing, check status.noclick.com.');

/** A page's own list: its rows when populated, an empty list for first-run/empty, the error in the error set. */
export function pageList(request: FixtureRequest, rows: readonly unknown[]): FixtureReply {
    if (request.set === 'error') return PAGE_ERROR;
    return list(request.set === 'populated' ? rows : []);
}

// ── shared objects ─────────────────────────────────────────────────────────

export const CONSOLE_KEY_ID = fixtureId(1, 1);

/** The account's users, each keyed by the developer's own id for them. */
export const USERS = [
    {
        object: 'user',
        id: 'acme',
        name: 'Acme Corp',
        email: 'ops@acme.test',
        phone: '+14155550101',
        phone_verified_at: ago(20 * DAY),
        spend_cap_usd_per_month: 50,
        metadata: { plan: 'team' },
        // Designed: where they are, for the date and time every agent turn starts with.
        timezone: 'America/New_York',
        status: 'active',
        created_at: ago(40 * DAY),
        // Whether they can spend (pause_spending / resume_spending).
        spending: { paused: false, message: null, action: null, since: null, held: 0, paused_by: null },
    },
    {
        object: 'user',
        id: 'user_42',
        name: 'Ana Silva',
        email: 'ana@example.com',
        phone: null,
        phone_verified_at: null,
        spend_cap_usd_per_month: null,
        metadata: {},
        status: 'active',
        created_at: ago(9 * DAY),
        // Paused by your billing when her credits ran out, with two of her messages held.
        spending: {
            paused: true,
            message: "You've used this month's credits.",
            action: { label: 'Top up', url: 'https://acme.test/billing/top-up?user=user_42' },
            since: ago(3 * HOUR),
            held: 2,
            paused_by: 'console',
        },
    },
    {
        object: 'user',
        id: 'globex',
        name: 'Globex',
        email: 'it@globex.test',
        phone: null,
        phone_verified_at: null,
        spend_cap_usd_per_month: 20,
        metadata: {},
        status: 'suspended',
        created_at: ago(60 * DAY),
        spending: { paused: false, message: null, action: null, since: null, held: 0, paused_by: null },
    },
] as const;

/**
 * Operations the designed fixtures start or hold (a card approval, a deploy), readable at
 * `/v1/operations/:id` after b.ts's own. Any operation a route answers with is remembered here.
 */
export const LAB_OPERATIONS = new Map<string, Record<string, unknown>>();

export function rememberOperation<T>(op: T): T {
    const row = op as Record<string, unknown> | null;
    if (row && row.object === 'operation' && typeof row.id === 'string') LAB_OPERATIONS.set(row.id, row);
    return op;
}

/** Agents the designed fixtures add (the `digest` automation), for b.ts's by-id agent routes. */
export const LAB_EXTRA_AGENTS: Record<string, unknown>[] = [];

export const AGENTS = [
    {
        object: 'agent',
        id: fixtureId(3, 1),
        name: 'support-bot',
        instructions: 'You answer billing questions.',
        model: 'anthropic/claude-sonnet-4.6',
        harness: 'sdk',
        tools: ['gmail.send_email', 'search', 'stripe.list_invoices'],
        can_request: [] as string[],
        grants: [] as Record<string, unknown>[],
        user_id: null,
        workflow_id: fixtureId(8, 1),
        parent_id: null,
        ttl_s: null,
        expires_at: null,
        budget_usd_per_month: 50,
        created_at: ago(30 * DAY),
    },
    {
        object: 'agent',
        id: fixtureId(3, 2),
        name: 'concierge',
        instructions: 'You book tables for Acme customers.',
        model: 'openai/gpt-5.1',
        harness: 'sdk',
        tools: ['search'],
        // What Acme's concierge asked its user for at run time: Gmail granted, Stripe still waiting on the link.
        can_request: ['gmail', 'stripe.list_invoices'],
        grants: [
            {
                object: 'agent_grant', id: fixtureId(9, 1), connection: 'gmail', connection_id: fixtureId(6, 1), integration: 'gmail',
                operations: ['send_email'], status: 'active', reason: 'To confirm bookings by email.', conversation: 'booking-17',
                created_at: ago(2 * HOUR), granted_at: ago(2 * HOUR - 5 * 60_000),
            },
            {
                object: 'agent_grant', id: fixtureId(9, 2), connection: 'stripe', connection_id: fixtureId(6, 3), integration: 'stripe',
                operations: ['list_invoices'], status: 'requested', reason: 'To check your deposit.', conversation: 'booking-17',
                created_at: ago(90 * 60_000), granted_at: null,
            },
        ] as Record<string, unknown>[],
        user_id: 'acme',
        workflow_id: fixtureId(8, 2),
        parent_id: null,
        ttl_s: 7200,
        expires_at: new Date(FIXTURE_NOW_MS + 2 * HOUR).toISOString(),
        budget_usd_per_month: null,
        created_at: ago(3 * HOUR),
    },
    // One per-user agent: the same definition for two users, each acting in its own connections.
    ...['acme', 'user_42'].map((userId, i) => ({
        object: 'agent' as const,
        id: fixtureId(3, 10 + i),
        name: 'assistant',
        instructions: 'You help with email and invoices.',
        model: 'anthropic/claude-sonnet-4.6',
        harness: 'sdk',
        tools: ['search', 'gmail'],
        can_request: ['stripe'] as string[],
        grants: [] as Record<string, unknown>[],
        user_id: userId,
        workflow_id: fixtureId(8, 10 + i),
        parent_id: null,
        ttl_s: null,
        expires_at: null,
        budget_usd_per_month: null,
        created_at: ago((5 - i) * DAY),
    })),
    // Coding agents on CLI harnesses: each thinks with a model provider's connection (a.ts), in its own scope.
    {
        object: 'agent',
        id: fixtureId(3, 30),
        name: 'coder',
        instructions: 'You maintain our docs repo. Fix broken links and open a pull request.',
        model: 'sonnet',
        harness: 'claude_code',
        model_connection: 'claude',
        tools: ['search'],
        can_request: [] as string[],
        grants: [] as Record<string, unknown>[],
        user_id: null,
        workflow_id: fixtureId(8, 30),
        parent_id: null,
        ttl_s: null,
        expires_at: null,
        budget_usd_per_month: 20,
        created_at: ago(2 * DAY),
    },
    {
        object: 'agent',
        id: fixtureId(3, 31),
        name: 'reviewer',
        instructions: "You review Acme's pull requests and leave comments.",
        model: 'gpt-5.6-luna',
        harness: 'codex',
        // Acme's own OpenAI connection, still waiting for Acme to paste a key or sign in with ChatGPT.
        model_connection: 'openai',
        tools: [] as string[],
        can_request: [] as string[],
        grants: [] as Record<string, unknown>[],
        user_id: 'acme',
        workflow_id: fixtureId(8, 31),
        parent_id: null,
        ttl_s: null,
        expires_at: null,
        budget_usd_per_month: null,
        created_at: ago(HOUR),
    },
] as const;

const SCOPES = [
    'agents', 'agents:terminal', 'ai', 'approvals:answer', 'brand', 'channels', 'credentials:request', 'credentials:token', 'credentials:use', 'dicts', 'humans', 'inbox', 'mcp_servers', 'operations', 'phone', 'policy', 'queues', 'sandboxes', 'secrets', 'tools', 'usage', 'users',
    // Designed, not built yet.
    'apps', 'browsers', 'cards', 'cards:reveal', 'databases', 'domains', 'domains:buy', 'repos', 'storage', 'volumes',
    'webhooks', 'webhooks:reveal', 'workflows',
];
const FULL_NO_TOKENS = SCOPES.filter((s) => !['credentials:token', 'cards:reveal', 'webhooks:reveal', 'agents:terminal', 'approvals:answer'].includes(s));

export const KEYS = [
    {
        object: 'key',
        id: CONSOLE_KEY_ID,
        kind: 'console',
        type: 'secret',
        name: 'Console',
        key_prefix: 'nk_live_c0n5',
        scopes: ['*'],
        spend_cap_usd_per_month: null,
        user_id: null,
        created_at: ago(30 * DAY),
        last_used_at: ago(2 * MIN),
        expires_at: null,
        revoked_at: null,
        spent_usd_this_month: 3.21,
    },
    {
        object: 'key',
        id: fixtureId(1, 2),
        kind: 'api',
        type: 'secret',
        name: 'backend-prod',
        key_prefix: 'nk_live_ab12',
        scopes: FULL_NO_TOKENS,
        spend_cap_usd_per_month: 100,
        user_id: null,
        created_at: ago(28 * DAY),
        last_used_at: ago(4 * MIN),
        expires_at: null,
        revoked_at: null,
        spent_usd_this_month: 84.14,
    },
    {
        object: 'key',
        id: fixtureId(1, 3),
        kind: 'api',
        type: 'secret',
        name: 'analytics',
        key_prefix: 'nk_live_9f3e',
        scopes: ['usage', 'operations'],
        spend_cap_usd_per_month: null,
        user_id: null,
        created_at: ago(12 * DAY),
        last_used_at: null,
        expires_at: null,
        revoked_at: null,
        spent_usd_this_month: 0,
    },
] as const;

export const META = {
    scopes: SCOPES,
    session_scopes: ['agents', 'credentials:request', 'humans', 'tools'],
    operation_kinds: [
        'agent.message', 'agent.rehearse', 'channel.a2a', 'credential.connect', 'human.approve', 'human.ask', 'human.notify', 'inbox.wait_for', 'phone.call', 'sandbox.exec',
        // Designed, not built yet.
        'browser.act', 'browser.login', 'bucket.export', 'database.branch', 'database.export', 'database.restore', 'deployment.promote',
        'dict.export', 'domain.buy', 'domain.renew', 'project.deploy', 'project.export', 'project.sign_in.enable', 'queue.export', 'repo.export', 'user.export',
        'volume.export', 'workflow.run', 'agent.task', 'agent.ask',
    ],
    operation_statuses: ['queued', 'running', 'awaiting_human', 'succeeded', 'failed', 'canceled', 'expired'],
    error_types: [
        { type: 'approval_required', status: 402 },
        { type: 'needs_connection', status: 424 },
        { type: 'plan_required', status: 402 },
        { type: 'policy_denied', status: 403 },
        { type: 'spend_cap_exceeded', status: 402 },
    ],
    mcp_tools: ['create_user', 'list_operations', 'message_agent', 'run_connection_operation'],
};

const ZERO_COUNTS = {
    keys_active: 0,
    keys_used: 0,
    users_active: 0,
    users_suspended: 0,
    agents: 0,
    operations_total: 0,
    operations_running: 0,
    operations_held: 0,
    operations_failed_24h: 0,
    human_requests_awaiting_you: 0,
    channels_open: 0,
    sandboxes_live: 0,
    inboxes: 0,
    phone_numbers: 0,
    webhooks: 0,
    mcp_servers: 0,
};

/** `/v1/account` per set: first-run has nothing, empty has a key but no activity. Every plan has the platform. */
export function fixtureAccount(set: FixtureSet, tier = 'member') {
    const populated = set === 'populated' || set === 'error';
    return {
        object: 'account',
        id: FIXTURE_USER.id,
        email: FIXTURE_USER.email,
        plan: { tier },
        balance: { remaining_usd: populated ? 41.37 : 20, resets_at: '2026-10-01T00:00:00Z', unlimited: false },
        month: { period_start: '2026-09-01T00:00:00Z', resets_at: '2026-10-01T00:00:00Z', spent_usd: populated ? 123.42 : 0 },
        counts: populated
            ? {
                  keys_active: 2,
                  keys_used: 1,
                  users_active: 2,
                  users_suspended: 1,
                  agents: 7,
                  operations_total: 1204,
                  operations_running: 1,
                  operations_held: 2,
                  operations_failed_24h: 1,
                  human_requests_awaiting_you: 2,
                  channels_open: 3,
                  sandboxes_live: 1,
                  machines: 1,
                  inboxes: 4,
                  phone_numbers: 3,
                  apps: 2,
                  databases: 3,
                  buckets: 2,
                  domains: 3,
                  repos: 3,
                  cards: 3,
                  browser_profiles: 2,
                  mcp_servers: 1,
                  webhooks: 2,
                  volumes: 2,
                  dicts: 2,
                  queues: 2,
                  secrets: 3,
              }
            : { ...ZERO_COUNTS, keys_active: set === 'empty' ? 1 : 0 },
        limits: {
            sandboxes_live_max: 10,
            background_execs_max: 20,
            inboxes_max: 25,
            human_emails_per_day: 200,
            human_emails_used_24h: populated ? 14 : 0,
            inbox_replies_per_day: 500,
            webhooks_max: 16,
        },
        features: { phone_numbers: true },
        default_region: populated ? 'eu' : null,
        // What a paused user is told when pause_spending names no message.
        spending_paused: populated
            ? { message: "You've used this month's credits.", action: { label: 'Top up', url: 'https://acme.test/billing/top-up?user={{user.id}}' } }
            : null,
        console_key_id: CONSOLE_KEY_ID,
        meta: META,
    };
}

/** `/v1/status` per set: the account, and the plan it's on as NoClick names it. On the Free and Member plans a paying
 *  account is a Member, whichever paid tier `/v1/account` stores for it; one still on an older plan is on that plan. */
export function fixtureStatus(set: FixtureSet, plan = 'member') {
    const account = fixtureAccount(set);
    return {
        object: 'status',
        account: { id: account.id, name: null, email: account.email, acting_for: null },
        user_id: null,
        plan: { name: plan, billing: plan === 'enterprise' ? 'contract' : plan === 'free' || plan === 'member' ? 'at_cost' : 'credits' },
        balance: account.balance,
        month: account.month,
        caps: [],
        caller: { key_id: CONSOLE_KEY_ID, cap_usd: null },
        approvals_pending: [],
        failing: { operations: [], connections: [] },
        operations: { running: account.counts.operations_running, held: account.counts.operations_held, recent: [] },
    };
}

/** Objects the palette resolves by id, key prefix or user id. */
function resolveRef(ref: string): { type: string; id: string; user_id: string | null } | null {
    const user = USERS.find((u) => u.id === ref);
    if (user) return { type: 'user', id: user.id, user_id: user.id };
    const agent = AGENTS.find((a) => a.id === ref);
    if (agent) return { type: 'agent', id: agent.id, user_id: agent.user_id };
    const key = KEYS.find((k) => k.id === ref || ref.startsWith(k.key_prefix));
    if (key) return { type: 'key', id: key.id, user_id: null };
    if (ref.startsWith('nk_live_1e6a')) return { type: 'legacy_key', id: fixtureId(1, 9), user_id: null };
    return null;
}

/** Answers `/v1/account` as an account storing `tier` and `/v1/status` as one on `plan`, for tests that pin the plan. */
export function planRoutes(tier: string, plan: string): FixtureRoute[] {
    return [
        { method: 'GET', path: '/v1/account', reply: (r) => ok(fixtureAccount(r.set, tier)) },
        { method: 'GET', path: '/v1/status', reply: (r) => ok(fixtureStatus(r.set, plan)) },
    ];
}

export const CORE_ROUTES: readonly FixtureRoute[] = [
    { method: 'GET', path: '/v1/account', reply: (r) => ok(fixtureAccount(r.set)) },
    { method: 'GET', path: '/v1/status', reply: (r) => ok(fixtureStatus(r.set)) },
    {
        method: 'GET',
        path: '/v1/objects/:ref',
        reply: (r) => {
            const found = r.set === 'populated' ? resolveRef(r.params.ref) : null;
            return found
                ? ok({ object: 'object_ref', ...found })
                : apiError(404, 'not_found', `Nothing in this account is named '${r.params.ref}'.`, "Paste an id, a key prefix (nk_live_…) or a user's id.");
        },
    },
    {
        method: 'GET',
        path: '/v1/users',
        reply: (r) => {
            const q = (r.query.get('q') ?? '').toLowerCase();
            const status = r.query.get('status');
            const limit = Number(r.query.get('limit') ?? 50);
            const rows = USERS.filter(
                (u) => (!status || u.status === status) && (!q || [u.id, u.name, u.email].some((v) => v?.toLowerCase().startsWith(q)))
            ).slice(0, limit);
            return pageList(r, rows);
        },
    },
    {
        method: 'GET',
        path: '/v1/users/:id',
        reply: (r) => {
            const u = USERS.find((x) => x.id === r.params.id);
            return u ? ok(u) : apiError(404, 'not_found', `User ${r.params.id} not found.`);
        },
    },
    { method: 'GET', path: '/v1/agents', reply: (r) => pageList(r, AGENTS) },
    {
        method: 'GET',
        path: '/v1/agents/:id',
        reply: (r) => {
            const a = AGENTS.find((x) => x.id === r.params.id);
            return a ? ok(a) : apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
        },
    },
    {
        method: 'GET',
        path: '/v1/keys',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : list(r.set === 'first-run' ? [KEYS[0]] : r.set === 'populated' ? KEYS : KEYS.slice(0, 2))),
    },
];

/**
 * Objects the screenshot runner opens by URL (scripts/developers/shoot.mjs
 * mirrors these literals). Page fixtures give these ids to the rows they serve.
 */
export const SHOT_TARGETS = {
    /** An agent.message with a held segment and tool calls: the drawer draws the timeline. */
    operationWithTimeline: fixtureId(4, 1),
    /** A two-event operation: the drawer prints "Waited … · ran …". */
    operationPlain: fixtureId(4, 2),
    /** An owner-answerable approval. */
    humanRequest: fixtureId(5, 1),
    /** The agent detail page, shot on every tab. */
    agent: fixtureId(3, 1),
    /** The user detail page, shot on every tab. */
    user: 'acme',
    /** A suspended user's detail page. */
    suspendedUser: 'globex',
} as const;
