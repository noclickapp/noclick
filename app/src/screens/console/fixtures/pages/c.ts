// Fixtures for Human requests, Usage, Policy, Brand and Resources (workstream
// C): canned /v1 answers shaped like the backend's views, filtered the way the
// real routes filter, so the lab and the page tests run the real client.
import {
    AGENTS,
    CONSOLE_KEY_ID,
    DAY,
    FIXTURE_NOW_MS,
    FIXTURE_USER,
    HOUR,
    KEYS,
    MIN,
    PAGE_ERROR,
    SHOT_TARGETS,
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
import { broughtNumbers, connectableRoute } from './m_numbers';
import { ACME_WORKSPACE, WORKSPACE_CHANNELS, WORKSPACE_CHANNEL_MESSAGES } from './n_orchestration';

/** What a US local number costs in these fixtures, a month and once when bought. */
const NUMBER_MONTHLY_USD = 1;
const NUMBER_UPFRONT_USD = 1;

const ACME = USERS[0].id;
const USER_42 = USERS[1].id;
const GLOBEX = USERS[2].id;
const SUPPORT_BOT = AGENTS[0].id;
const CONCIERGE = AGENTS[1].id;
const BACKEND_PROD = KEYS[1];

/** Resource ids under this file's kind digit 7: channels 1xx, inboxes 2xx, numbers 3xx, sandboxes 4xx, digest mail 1xxx. */
const rid = (group: number, n: number) => fixtureId(7, group + n);
const later = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString();

/** A list route's `user_id`: omitted = account-level rows, `all`, `none`, or a user's id. */
export function userMatches(query: URLSearchParams, rowUserId: string | null): boolean {
    const filter = query.get('user_id');
    if (filter === 'all') return true;
    if (filter === null || filter === 'none') return rowUserId === null;
    return filter === rowUserId;
}

function csv(query: URLSearchParams, name: string): string[] | null {
    const value = query.get(name);
    return value ? value.split(',').filter(Boolean) : null;
}

function found<T>(row: T | undefined, what: string): FixtureReply {
    return row ? ok(row) : apiError(404, 'not_found', `No such ${what}.`);
}

// ── human requests ─────────────────────────────────────────────────────────

const OWNER = { email: FIXTURE_USER.email, phone: null, name: null };
const USER_TO = (u: (typeof USERS)[number]) => ({ email: u.email, phone: u.phone, name: u.name });

interface HumanRequestRow {
    id: string;
    kind: string;
    status: string;
    user_id: string | null;
    owner_can_answer: boolean;
    [field: string]: unknown;
}

function request(n: number, fields: Partial<HumanRequestRow> & Pick<HumanRequestRow, 'kind' | 'status'>): HumanRequestRow {
    return {
        object: 'human_request',
        id: fixtureId(5, n),
        options: [],
        details: {},
        answer: null,
        answered_at: null,
        answered_by: null,
        delivered_via: ['email', 'web'],
        url: `https://noclick.com/h/${fixtureId(5, n)}`,
        operation_id: fixtureId(4, 100 + n),
        user_id: null,
        approval: null,
        approver: null,
        requested_by: { key_id: BACKEND_PROD.id, key_name: BACKEND_PROD.name },
        owner_can_answer: false,
        expires_at: later(23 * HOUR),
        ...fields,
    };
}

export const HUMAN_REQUESTS = [
    request(1, {
        kind: 'approve',
        status: 'pending',
        to: OWNER,
        message: 'backend-prod wants to run gmail.send_email. Approve it?',
        details: { Action: 'gmail.send_email', Arguments: JSON.stringify({ subject: 'Weekly summary', to: 'ana@acme.com' }, null, 2) },
        approval: { id: fixtureId(6, 1), tool: 'gmail.send_email', user_id: ACME, used_at: null },
        approver: 'owner',
        owner_can_answer: true,
        created_at: ago(12 * MIN),
    }),
    request(8, {
        kind: 'ask',
        status: 'pending',
        to: OWNER,
        message: 'What should the support bot tell customers about the outage?',
        requested_by: { key_id: CONSOLE_KEY_ID, key_name: 'Console' },
        owner_can_answer: true,
        created_at: ago(40 * MIN),
    }),
    request(2, {
        kind: 'approve',
        status: 'pending',
        to: USER_TO(USERS[0]),
        user_id: ACME,
        message: 'backend-prod wants to run slack.send_message. Approve it?',
        details: { Action: 'slack.send_message', Arguments: JSON.stringify({ channel: '#general', text: 'Deploy done' }, null, 2) },
        approval: { id: fixtureId(6, 2), tool: 'slack.send_message', user_id: ACME, used_at: null },
        approver: 'user',
        created_at: ago(2 * HOUR),
    }),
    request(3, {
        kind: 'ask',
        status: 'pending',
        to: USER_TO(USERS[1]),
        user_id: USER_42,
        message: 'Which day works for the onboarding call?',
        options: ['Friday', 'Monday'],
        created_at: ago(5 * HOUR),
    }),
    request(4, {
        kind: 'notify',
        status: 'delivered',
        to: { email: 'finance@acme.test', phone: null, name: null },
        message: 'Your September invoice is ready.',
        created_at: ago(1 * DAY),
        expires_at: ago(1 * DAY - 7 * DAY),
    }),
    request(5, {
        kind: 'approve',
        status: 'answered',
        to: OWNER,
        message: 'backend-prod wants to run stripe.refund_payment. Approve it?',
        details: { Action: 'stripe.refund_payment', Arguments: JSON.stringify({ amount: 4200, charge: 'ch_3Pq' }, null, 2) },
        // Designed: what the approver saw, the operation's label and the agent's conversation and reason.
        approval: {
            id: fixtureId(6, 5),
            tool: 'stripe.refund_payment',
            user_id: GLOBEX,
            used_at: ago(2 * DAY - HOUR),
            label: 'Refund a payment in Stripe',
            agent: { id: SUPPORT_BOT, name: AGENTS[0].name },
            conversation: 'ticket-1841',
            reason: 'The customer was charged twice for order 1841, so I am refunding the second charge.',
        },
        approver: 'owner',
        answer: { approved: true, text: null },
        answered_at: ago(2 * DAY - HOUR),
        answered_by: 'owner',
        created_at: ago(2 * DAY),
    }),
    request(6, {
        kind: 'ask',
        status: 'expired',
        to: { email: 'ops@acme.test', phone: null, name: null },
        message: 'Is the Friday deploy still on?',
        created_at: ago(4 * DAY),
        expires_at: ago(3 * DAY),
    }),
    request(7, {
        kind: 'approve',
        status: 'canceled',
        to: { email: 'cfo@acme.test', phone: null, name: null },
        message: 'Approve the Q4 budget change?',
        created_at: ago(6 * DAY),
    }),
];

function answered(row: HumanRequestRow, body: Record<string, unknown>) {
    const answer = row.kind === 'approve' ? { approved: body.approved === true, text: body.text ?? null } : { choice: body.choice ?? null, text: body.text ?? null };
    return { ...row, status: 'answered', answer, answered_at: new Date(FIXTURE_NOW_MS).toISOString(), answered_by: 'owner', owner_can_answer: false };
}

const humanRoutes: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/humans/requests',
        reply: (r) => {
            const status = csv(r.query, 'status');
            const statusNot = csv(r.query, 'status_not');
            const kind = csv(r.query, 'kind');
            const rows = HUMAN_REQUESTS.filter(
                (h) =>
                    (!status || status.includes(h.status)) &&
                    (!statusNot || !statusNot.includes(h.status)) &&
                    (!kind || kind.includes(h.kind)) &&
                    (r.query.get('answerable') !== 'owner' || (h.owner_can_answer && h.status === 'pending')) &&
                    userMatches(r.query, h.user_id)
            );
            return pageList(r, rows);
        },
    },
    {
        method: 'GET',
        path: '/v1/humans/requests/:id',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : found(HUMAN_REQUESTS.find((h) => h.id === r.params.id), 'human request')),
    },
    {
        method: 'POST',
        path: '/v1/humans/requests/:id/answer',
        reply: (r) => {
            const row = HUMAN_REQUESTS.find((h) => h.id === r.params.id);
            if (!row) return apiError(404, 'not_found', 'No human request with that id.');
            if (row.status !== 'pending') return apiError(409, 'conflict', 'This request was already answered or withdrawn.');
            if (!row.owner_can_answer) {
                return apiError(403, 'permission_denied', 'This request is addressed to someone else.', 'Only the person it was sent to can answer it, through its link.');
            }
            return ok(answered(row, (r.body ?? {}) as Record<string, unknown>));
        },
    },
];

// ── usage ──────────────────────────────────────────────────────────────────

type Line = { id: string | null; label: string | null; total: number };

const SERIES: Record<string, Line[]> = {
    key: [
        { id: BACKEND_PROD.id, label: 'backend-prod', total: 84.12 },
        { id: fixtureId(1, 4), label: 'ci-runner', total: 36.12 },
        { id: CONSOLE_KEY_ID, label: 'Console', total: 3.21 },
    ],
    user: [
        { id: null, label: null, total: 34.85 },
        { id: ACME, label: 'acme', total: 47.9 },
        { id: GLOBEX, label: 'globex', total: 22.4 },
        { id: USER_42, label: 'user_42', total: 18.3 },
    ],
    agent: [
        { id: null, label: null, total: 80.15 },
        { id: SUPPORT_BOT, label: 'support-bot', total: 31.2 },
        { id: CONCIERGE, label: 'concierge', total: 12.1 },
    ],
    // The designed spend types (apps, databases, ... app email) are lab-only, as their primitives are.
    type: [
        { id: 'model_tokens', label: 'Model tokens', total: 41.35 },
        { id: 'tool_runs', label: 'Tool runs', total: 18.4 },
        { id: 'apps', label: 'Apps', total: 11.3 },
        { id: 'ai', label: 'AI', total: 9.85 },
        { id: 'sandboxes', label: 'Sandboxes', total: 8.1 },
        { id: 'databases', label: 'Databases', total: 7.25 },
        { id: 'browser_minutes', label: 'Browser minutes', total: 6.4 },
        { id: 'storage', label: 'Storage', total: 4.95 },
        { id: 'volumes', label: 'Volumes', total: 1.9 },
        { id: 'phone', label: 'Phone calls', total: 4.35 },
        { id: 'domains', label: 'Domains', total: 3.6 },
        { id: 'emails', label: 'Emails', total: 2.1 },
        { id: 'cards', label: 'Cards', total: 1.5 },
        { id: 'app_email', label: 'App email', total: 1.45 },
        { id: 'queues', label: 'Queues', total: 0.6 },
        { id: 'dicts', label: 'Dicts', total: 0.35 },
    ],
};

const cents = (usd: number) => Math.round(usd * 100) / 100;

/** A line's total spread over the UTC days of [from, min(to, now)), weighted so the bars vary. */
function points(line: Line, from: number, to: number, scale: number) {
    const days: number[] = [];
    for (let t = from; t < Math.min(to, FIXTURE_NOW_MS); t += DAY) days.push(t);
    const weights = days.map((_, i) => 1 + ((i * 7 + (line.label?.length ?? 3)) % 5));
    const sum = weights.reduce((a, b) => a + b, 0) || 1;
    return days.map((t, i) => {
        const usd = cents((line.total * scale * weights[i]) / sum);
        return { t: new Date(t).toISOString(), usd, events: Math.max(1, Math.round(usd * 9)) };
    });
}

function monthStart(ms: number): number {
    const d = new Date(ms);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
}

/** One key's, agent's or user's part of the total, so a filtered read (the Usage drawer) is plausible. */
function filterShare(query: URLSearchParams): number {
    const share = (group: string, id: string | null) => {
        const lines = SERIES[group];
        return (lines.find((l) => l.id === id)?.total ?? 0) / lines.reduce((s, l) => s + l.total, 0);
    };
    if (query.get('key_id')) return share('key', query.get('key_id'));
    if (query.get('agent_id')) return share('agent', query.get('agent_id'));
    const user = query.get('user_id');
    if (!user || user === 'all') return 1;
    return share('user', user === 'none' ? null : user);
}

function usageSeries(r: FixtureRequest): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    const from = r.query.get('from') ? Date.parse(r.query.get('from')!) : monthStart(FIXTURE_NOW_MS);
    const to = r.query.get('to') ? Date.parse(r.query.get('to')!) : Date.UTC(new Date(from).getUTCFullYear(), new Date(from).getUTCMonth() + 1, 1);
    const group = r.query.get('group_by') ?? 'type';
    // This month in full, last month a little less, nothing before.
    const monthsBack = (monthStart(FIXTURE_NOW_MS) - monthStart(from)) / (30 * DAY);
    const scale = (r.set !== 'populated' || monthsBack > 1.5 ? 0 : monthsBack > 0.5 ? 0.8 : 1) * filterShare(r.query);
    const lines = scale ? (SERIES[group] ?? []) : [];
    const series = lines
        .map((line) => {
            const pts = points(line, from, to, scale);
            return {
                id: line.id,
                label: line.label,
                total_usd: cents(pts.reduce((s, p) => s + p.usd, 0)),
                events: pts.reduce((s, p) => s + p.events, 0),
                points: pts,
            };
        })
        .sort((a, b) => b.total_usd - a.total_usd);
    return ok({
        object: 'usage_series',
        interval: 'day',
        from: new Date(from).toISOString(),
        to: new Date(to).toISOString(),
        total_usd: cents(series.reduce((s, l) => s + l.total_usd, 0)),
        series,
    });
}

export const USAGE_LIMITS = {
    period_start: '2026-09-01T00:00:00Z',
    resets_at: '2026-10-01T00:00:00Z',
    keys: [{ id: BACKEND_PROD.id, name: 'backend-prod', cap: 100, spent: 84.14 }],
    users: [
        { id: ACME, cap: 50, spent: 47.9 },
        { id: GLOBEX, cap: 20, spent: 22.4 },
    ],
    agents: [{ id: SUPPORT_BOT, name: 'support-bot', budget: 50, spent: 31.2, subtree_spent: 33.05 }],
};

const EMPTY_LIMITS = { ...USAGE_LIMITS, keys: [], users: [], agents: [] };

const usageRoutes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/usage/series', reply: usageSeries },
    {
        method: 'GET',
        path: '/v1/usage/limits',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : ok(r.set === 'populated' ? USAGE_LIMITS : EMPTY_LIMITS)),
    },
];

// ── policy ─────────────────────────────────────────────────────────────────

/** A pattern, or (designed) a rule with a condition over the call's arguments and who approves it. */
type RuleRow = string | { tool: string; when?: string; approver?: Record<string, unknown> };

interface Rules {
    user_id: string | null;
    allow: RuleRow[];
    deny: RuleRow[];
    require_approval: RuleRow[];
}

/** Refunds over $100 wait for finance (designed: a rule with a condition, set from code). */
export const REFUND_RULE = { tool: 'stripe.refund_payment', when: 'args.amount > 10000', approver: { email: 'finance@acme.com' } };
export const ACCOUNT_POLICY: Rules = { user_id: null, allow: [], deny: ['*.delete_*'], require_approval: ['gmail.send_email', REFUND_RULE] };
export const ACME_POLICY: Rules = { user_id: ACME, allow: [], deny: ['stripe.refund_*'], require_approval: [] };
const NO_RULES = (userId: string | null): Rules => ({ user_id: userId, allow: [], deny: [], require_approval: [] });

function policyView(rules: Rules) {
    return { object: 'policy', ...rules, updated_at: rules.deny.length || rules.allow.length || rules.require_approval.length ? ago(3 * DAY) : null };
}

function savedRules(set: FixtureRequest['set'], userId: string | null): Rules {
    if (set !== 'populated') return NO_RULES(userId);
    if (userId === null) return ACCOUNT_POLICY;
    return userId === ACME ? ACME_POLICY : NO_RULES(userId);
}

function fnmatch(pattern: string, tool: string): boolean {
    if (!pattern.includes('*') && !pattern.includes('.')) return tool === pattern || tool.startsWith(`${pattern}.`);
    const re = new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')}$`);
    return re.test(tool);
}

const COMPARE: Record<string, (a: number, b: number) => boolean> = {
    '>': (a, b) => a > b, '>=': (a, b) => a >= b, '<': (a, b) => a < b, '<=': (a, b) => a <= b, '==': (a, b) => a === b, '!=': (a, b) => a !== b,
};

/**
 * Whether a rule applies to this call. The fixture reads only `args.<field> <op> <number>` of CEL;
 * a `when` it can't judge, or a call without arguments, doesn't match (as the server's does).
 */
function ruleMatches(row: RuleRow, tool: string, args: Record<string, unknown> | undefined): boolean {
    if (typeof row === 'string') return fnmatch(row, tool);
    if (!fnmatch(row.tool, tool)) return false;
    if (!row.when) return true;
    const m = /^args\.(\w+)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)$/.exec(row.when.trim());
    const value = m && args ? args[m[1]] : undefined;
    return typeof value === 'number' && COMPARE[m![2]](value, Number(m![3]));
}

const patternOf = (row: RuleRow) => (typeof row === 'string' ? row : row.tool);

/** `policy/service.explain`: account then user; deny wins, an allow list that misses denies, the first approval asks. */
export function explain(layers: Rules[], tool: string, args?: Record<string, unknown>) {
    let approval: Record<string, unknown> | null = null;
    let allowed: Record<string, unknown> | null = null;
    const found = (verdict: string, row: RuleRow, layer: string) => ({ verdict, matched_pattern: patternOf(row), layer, rule: row });
    for (const policy of layers) {
        const layer = policy.user_id ? 'user' : 'account';
        const deny = policy.deny.find((p) => ruleMatches(p, tool, args));
        if (deny) return found('deny', deny, layer);
        if (policy.allow.length) {
            const allow = policy.allow.find((p) => ruleMatches(p, tool, args));
            if (!allow) return { verdict: 'deny', matched_pattern: null, layer, rule: null };
            allowed = found('allow', allow, layer);
        }
        const ask = policy.require_approval.find((p) => ruleMatches(p, tool, args));
        if (!approval && ask) approval = found('approval', ask, layer);
    }
    return approval ?? allowed ?? { verdict: 'allow', matched_pattern: null, layer: null, rule: null };
}

const normalizeTool = (name: string) => {
    const [integration, ...rest] = name.trim().toLowerCase().split('__');
    return rest.length ? `${integration}.${rest.join('__')}` : integration;
};

const policyRoutes: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/policy',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : ok(policyView(savedRules(r.set, r.query.get('user_id'))))),
    },
    {
        method: 'PUT',
        path: '/v1/policy',
        reply: (r) => {
            const body = (r.body ?? {}) as Partial<Rules>;
            const bad = [...(body.allow ?? []), ...(body.deny ?? []), ...(body.require_approval ?? [])].map(patternOf).find((p) => !/^[a-z0-9_*-]+(\.[a-z0-9_*-]+)*$/.test(p));
            if (bad) return apiError(400, 'invalid_request', `'${bad}' is not a tool pattern.`, "Use dotted tool names with * wildcards, e.g. 'gmail.*', '*.delete_*' or 'search'.");
            return ok({ ...policyView({ ...NO_RULES(body.user_id ?? null), ...body } as Rules), updated_at: new Date(FIXTURE_NOW_MS).toISOString() });
        },
    },
    {
        method: 'GET',
        path: '/v1/policies',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const rows: Record<string, unknown>[] = [policyView(savedRules(r.set, null))];
            if (r.set === 'populated') rows.push(policyView(ACME_POLICY));
            return list(rows);
        },
    },
    {
        method: 'POST',
        path: '/v1/policy/evaluate',
        reply: (r) => {
            const body = (r.body ?? {}) as { tools: string[]; arguments?: Record<string, unknown>; user_id?: string; draft?: { layer: 'account' | 'user' } & Omit<Rules, 'user_id'> };
            const userId = body.user_id ?? null;
            let layers = [savedRules(r.set, null), ...(userId ? [savedRules(r.set, userId)] : [])];
            if (body.draft) {
                const draft: Rules = { ...body.draft, user_id: body.draft.layer === 'user' ? userId : null };
                layers = [...layers.filter((l) => (l.user_id !== null) !== (body.draft!.layer === 'user')), draft].sort(
                    (a, b) => Number(a.user_id !== null) - Number(b.user_id !== null)
                );
            }
            return ok({ object: 'policy_evaluation', user_id: userId, results: body.tools.map((t) => ({ tool: normalizeTool(t), ...explain(layers, normalizeTool(t), body.arguments) })) });
        },
    },
];

const INTEGRATION_OPERATIONS: Record<string, string[]> = {
    gmail: ['send_email', 'list_messages', 'delete_message'],
    stripe: ['list_invoices', 'refund_payment', 'delete_customer'],
    slack: ['send_message', 'list_channels'],
};

// ── brand ──────────────────────────────────────────────────────────────────

/** `google-oauth` in the Secrets fixtures (k_files.ts), by id so this file needn't import it. */
const GOOGLE_OAUTH_SECRET_ID = fixtureId(7, 112_004);

/** `brand/service.OAUTH_APP_PROVIDERS`, each with the redirect URI its app registers. */
const OAUTH_APP_PROVIDERS = ['asana', 'box', 'clickup', 'gitlab', 'google', 'intercom', 'klaviyo', 'monday', 'pagerduty', 'pipedrive', 'slack', 'webflow', 'zoom'];
const OAUTH_REDIRECT_URLS = Object.fromEntries(OAUTH_APP_PROVIDERS.map((p) => [p, `https://noclick.com/api/auth/${p}/callback`]));

export const CUSTOM_BRAND = {
    object: 'brand',
    name: 'Acme Travel',
    logo_url: null,
    color: '#1a73e8',
    support_url: 'https://acme.test/help',
    email_from_name: 'Acme Travel',
    // Designed: the pages come from the account's own host.
    domain: 'connect.acmebooking.com',
    // Google's consent screen names Acme.
    oauth_apps: { google: GOOGLE_OAUTH_SECRET_ID } as Record<string, string>,
    oauth_redirect_urls: OAUTH_REDIRECT_URLS,
    is_default: false,
    updated_at: ago(10 * DAY),
};

const DEFAULT_BRAND_VIEW = {
    object: 'brand',
    name: 'NoClick',
    logo_url: null,
    color: null,
    support_url: null,
    email_from_name: null,
    oauth_apps: {},
    oauth_redirect_urls: OAUTH_REDIRECT_URLS,
    is_default: true,
    updated_at: null,
};

const HTTPS = /^https:\/\/[^\s/]+/;

/** `brand/service._clean_color`: `#rgb` or `#rrggbb`, stored lower-case as `#rrggbb`; else null. */
export function expandColor(value: string): string | null {
    const v = value.trim().toLowerCase();
    if (/^#[0-9a-f]{6}$/.test(v)) return v;
    return /^#[0-9a-f]{3}$/.test(v) ? `#${[...v.slice(1)].map((c) => c + c).join('')}` : null;
}

function putBrand(r: FixtureRequest): FixtureReply {
    const body = (r.body ?? {}) as Record<string, string | null>;
    const name = (body.name ?? '').trim();
    if (!name) return apiError(400, 'invalid_request', 'name must not be blank.', undefined, { field: 'name' });
    for (const field of ['logo_url', 'support_url']) {
        if (body[field] && !HTTPS.test(body[field]!)) {
            return apiError(400, 'invalid_request', `${field} must be an https URL.`, `Pass a full https:// URL for ${field}, or null.`, { field });
        }
    }
    const color = body.color ? expandColor(body.color) : null;
    if (body.color && !color) return apiError(400, 'invalid_request', 'color must be a hex color like #1a73e8.', undefined, { field: 'color' });
    return ok({ ...DEFAULT_BRAND_VIEW, ...body, color, name, oauth_apps: body.oauth_apps ?? {}, is_default: false, updated_at: new Date(FIXTURE_NOW_MS).toISOString() });
}

/** `PATCH /v1/brand` for the OAuth apps alone: the providers named change, a `null` one is removed. */
function patchBrandApps(r: FixtureRequest): FixtureReply {
    const sent = ((r.body ?? {}) as { oauth_apps?: Record<string, string | null> | null }).oauth_apps;
    const unknown = Object.keys(sent ?? {}).find((p) => !OAUTH_APP_PROVIDERS.includes(p));
    if (unknown) {
        return apiError(400, 'invalid_request', `NoClick can't sign in to ${unknown} with your own OAuth app yet; it can for ${OAUTH_APP_PROVIDERS.join(', ')}.`, undefined, { field: 'oauth_apps' });
    }
    const merged = Object.entries({ ...CUSTOM_BRAND.oauth_apps, ...sent }).filter(([, id]) => id !== null);
    return ok({ ...CUSTOM_BRAND, oauth_apps: sent === null ? {} : Object.fromEntries(merged), updated_at: new Date(FIXTURE_NOW_MS).toISOString() });
}

const brandRoutes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/brand', reply: (r) => (r.set === 'error' ? PAGE_ERROR : ok(r.set === 'populated' ? CUSTOM_BRAND : DEFAULT_BRAND_VIEW)) },
    { method: 'PUT', path: '/v1/brand', reply: putBrand },
    { method: 'PATCH', path: '/v1/brand', reply: patchBrandApps },
    { method: 'DELETE', path: '/v1/brand', reply: () => ok(DEFAULT_BRAND_VIEW) },
];

// ── resources ──────────────────────────────────────────────────────────────

const member = (n: number, fields: Record<string, unknown>) => ({
    object: 'channel_member',
    id: fixtureId(0, n),
    agent_id: null,
    a2a_url: null,
    a2a_header_names: null,
    user_id: null,
    busy: false,
    created_at: ago(3 * DAY),
    ...fields,
});

export const CHANNELS = [
    {
        object: 'channel',
        id: rid(100, 1),
        name: 'launch',
        mode: 'mentions',
        status: 'open',
        halt_reason: null,
        max_agent_turns: 50,
        max_mention_hops: 4,
        budget_usd: 10,
        spent_usd: 3.42,
        agent_turns_since_human: 2,
        user_id: ACME,
        // Designed: it sits in Acme's own workspace (n_orchestration.ts).
        workspace_id: ACME_WORKSPACE.id,
        members: [
            member(1, { type: 'agent', name: 'support-bot', agent_id: SUPPORT_BOT }),
            member(2, { type: 'user', name: 'acme', user_id: ACME }),
            member(3, { type: 'a2a', name: 'partner-bot', a2a_url: 'https://agents.partner.test/a2a', a2a_header_names: ['Authorization'] }),
        ],
        created_at: ago(3 * DAY),
    },
    {
        object: 'channel',
        id: rid(100, 2),
        name: 'triage',
        mode: 'all',
        status: 'closed',
        halt_reason: 'budget',
        max_agent_turns: 20,
        max_mention_hops: 2,
        budget_usd: 5,
        spent_usd: 5.08,
        agent_turns_since_human: 20,
        user_id: null,
        members: [member(4, { type: 'agent', name: 'support-bot', agent_id: SUPPORT_BOT }), member(5, { type: 'agent', name: 'concierge', agent_id: CONCIERGE })],
        created_at: ago(9 * DAY),
    },
];

/** Every channel the lab lists: these, and the Launch team workspace's (designed). */
const ALL_CHANNELS: { id: string; user_id: string | null; workspace_id?: unknown }[] = [...CHANNELS, ...(WORKSPACE_CHANNELS as { id: string; user_id: string | null; workspace_id: unknown }[])];

const message = (n: number, channelId: string, author: Record<string, unknown>, text: string, at: string) => ({
    object: 'channel_message',
    id: fixtureId(0, 100 + n),
    channel_id: channelId,
    author,
    text,
    mentions: [],
    created_at: at,
});

export const CHANNEL_MESSAGES = [
    message(1, CHANNELS[0].id, { type: 'user', id: ACME, name: 'acme' }, '@support-bot can we launch Friday?', ago(50 * MIN)),
    message(2, CHANNELS[0].id, { type: 'agent', id: SUPPORT_BOT, name: 'support-bot' }, 'Friday works. I asked partner-bot to confirm the press slot.', ago(49 * MIN)),
    message(3, CHANNELS[0].id, { type: 'a2a', id: null, name: 'partner-bot' }, 'Press slot confirmed for 10:00 PT.', ago(47 * MIN)),
];

/** Designed: a channel's schedule posts its message in the room as the account. */
export const CHANNEL_TRIGGERS = [
    {
        object: 'agent_trigger',
        id: fixtureId(0, 150),
        channel_id: CHANNELS[0].id,
        kind: 'cron',
        spec: { cron: '0 9 * * 1', tz: 'America/New_York', message: "@support-bot post this week's launch checklist." },
        status: 'active',
        url: null,
        next_run: later(2 * DAY),
        last_fired_at: ago(5 * DAY),
        error: null,
        created_at: ago(9 * DAY),
    },
];

/** Designed (an inbox on the user's own domain): a subdomain of Acme's connected `acme.test`, waiting on DNS in the Domains fixtures. */
export const HELP_INBOX_ID = rid(200, 4);

// Designed: `name` and `senders` (whose mail wakes the agent).
export const INBOXES = [
    { object: 'inbox', id: rid(200, 1), name: 'support', senders: 'anyone', address: 'support-acme@in.noclick.app', agent_id: SUPPORT_BOT, user_id: ACME, created_at: ago(14 * DAY) },
    { object: 'inbox', id: rid(200, 2), address: 'signup-7f3a@in.noclick.app', agent_id: null, user_id: null, created_at: ago(2 * DAY) },
    { object: 'inbox', id: rid(200, 3), address: 'digests@in.noclick.app', agent_id: null, user_id: null, created_at: ago(10 * DAY) },
    { object: 'inbox', id: HELP_INBOX_ID, name: 'help', senders: 'users', address: 'help@mail.acme.test', domain: 'mail.acme.test', agent_id: SUPPORT_BOT, user_id: ACME, created_at: ago(1 * DAY) },
];

/** More mail than one page holds (the route pages 50 by default), oldest first: `Digest #120` is the newest. */
export const DIGEST_COUNT = 120;

export const INBOX_MESSAGES = [
    {
        object: 'inbox_message',
        id: fixtureId(0, 201),
        inbox_id: INBOXES[0].id,
        from: 'ana@example.com',
        to: 'support-acme@in.noclick.app',
        subject: 'Refund for order 1182',
        text: 'Hi, I was charged twice for order 1182. Can you refund one of them?',
        html: null,
        attachments: [{ name: 'receipt.pdf', mime_type: 'application/pdf', size_bytes: 48213, url: null, text: 'Order 1182 · $42.00', text_truncated: false, digest_error: null }],
        authenticated: true,
        agent_operation_id: fixtureId(4, 201),
        agent_error: null,
        // Designed: every message of one email thread shares a conversation with the agent.
        conversation: 'thread-refund-1182',
        received_at: ago(3 * HOUR),
    },
    {
        object: 'inbox_message',
        id: fixtureId(0, 202),
        inbox_id: HELP_INBOX_ID,
        from: 'someone@example.net',
        to: 'help@mail.acme.test',
        subject: 'Question about pricing',
        text: 'Hello, what does the team plan cost?',
        html: null,
        attachments: [],
        authenticated: true,
        agent_operation_id: null,
        // Designed: `senders: "users"` keeps mail from anyone else, and says why it woke no one.
        agent_error: "Not from one of your users: this inbox's agent answers only them.",
        conversation: null,
        received_at: ago(5 * HOUR),
    },
    ...Array.from({ length: DIGEST_COUNT }, (_, i) => ({
        object: 'inbox_message',
        id: rid(1000, i),
        inbox_id: INBOXES[2].id,
        from: 'digest@news.example.com',
        to: INBOXES[2].address,
        subject: `Digest #${i + 1}`,
        text: `Issue ${i + 1}.`,
        html: null,
        attachments: [],
        authenticated: true,
        agent_operation_id: null,
        agent_error: null,
        received_at: ago((DIGEST_COUNT - i) * HOUR),
    })),
];

/** What the support inbox sent: its reply on the refund thread, as a thread's messages show it. */
export const INBOX_SENT = [
    {
        object: 'inbox_message',
        id: fixtureId(0, 203),
        inbox_id: INBOXES[0].id,
        direction: 'outbound',
        from: INBOXES[0].address,
        to: 'ana@example.com',
        subject: 'Re: Refund for order 1182',
        text: 'Hi Ana, sorry about that. One of the two charges is refunded: it shows on your card in 3 to 5 days.',
        html: null,
        attachments: [],
        authenticated: false,
        agent_operation_id: null,
        agent_error: null,
        conversation: 'thread-refund-1182',
        received_at: ago(2 * HOUR),
    },
];

type MailRow = { id: string; inbox_id: string; subject: string; text: string; from: string; to: string; received_at: string; conversation?: string | null; direction?: string };

/** An inbox's mail as threads, the most recently active first: a message's conversation names its thread, else it's one of its own. */
function inboxThreads(inboxId: string) {
    const threads = new Map<string, MailRow[]>();
    for (const m of [...INBOX_MESSAGES, ...INBOX_SENT] as MailRow[]) {
        if (m.inbox_id !== inboxId) continue;
        const key = m.conversation ?? m.id;
        threads.set(key, [...(threads.get(key) ?? []), m]);
    }
    return [...threads.values()]
        .map((mail) => {
            const messages = [...mail].sort((a, b) => a.received_at.localeCompare(b.received_at));
            const last = messages[messages.length - 1];
            const sent = last.direction === 'outbound';
            return {
                object: 'inbox_thread',
                id: messages[0].id,
                inbox_id: inboxId,
                conversation: messages[0].conversation ?? null,
                subject: messages[0].subject,
                correspondent: sent ? last.to : last.from,
                message_count: messages.length,
                last_direction: sent ? 'outbound' : 'inbound',
                snippet: last.text.slice(0, 160),
                last_at: last.received_at,
                messages,
            };
        })
        .sort((a, b) => b.last_at.localeCompare(a.last_at));
}

// Designed: a number's name, recording, and what its answering agent may do on a call; where
// it came from (m_numbers.ts holds the numbers brought from elsewhere).
export const PHONE_NUMBERS = [
    {
        object: 'phone_number',
        id: rid(300, 1),
        name: 'front-desk',
        number: '+14155550142',
        source: 'bought',
        connection: null,
        user_id: ACME,
        agent_id: SUPPORT_BOT,
        transfer_to: '+14155550199',
        texts: false,
        callers: 'anyone',
        record_calls: true,
        monthly_usd: 1.44,
        created_at: ago(20 * DAY),
    },
];

export const PHONE_CALLS = [
    {
        object: 'phone_call',
        id: fixtureId(0, 301),
        phone_number_id: PHONE_NUMBERS[0].id,
        direction: 'outbound',
        from: '+14155550142',
        to: '+14155550100',
        goal: "Confirm Friday's 3pm booking.",
        agent_id: SUPPORT_BOT,
        operation_id: fixtureId(4, 301),
        status: 'completed',
        call_sid: 'CA0001',
        seconds: 94,
        cost_usd: 0.47,
        error: null,
        transcript: [
            { role: 'assistant', text: "Hi, I'm calling from Acme to confirm Friday at 3pm.", at: 1.2 },
            { role: 'user', text: 'Yes, that still works.', at: 6.8 },
        ],
        created_at: ago(6 * HOUR),
        ended_at: ago(6 * HOUR - 94_000),
        recording_url: 'https://files.noclick.app/rec/CA0001.mp3?sig=fixture',
    },
    // Designed: calls it answered are listed too, with who called.
    {
        object: 'phone_call',
        id: fixtureId(0, 302),
        phone_number_id: PHONE_NUMBERS[0].id,
        direction: 'inbound',
        from: '+14155550177',
        to: '+14155550142',
        goal: null,
        agent_id: SUPPORT_BOT,
        operation_id: fixtureId(4, 302),
        status: 'completed',
        call_sid: 'CA0002',
        seconds: 61,
        cost_usd: 0.31,
        error: null,
        transcript: [
            { role: 'user', text: 'Hi, can I move my Friday booking?', at: 0.9 },
            { role: 'assistant', text: 'Sure. Monday at 10 is free; shall I book it?', at: 4.1 },
        ],
        user_id: ACME,
        recording_url: 'https://files.noclick.app/rec/CA0002.mp3?sig=fixture',
        created_at: ago(2 * HOUR),
        ended_at: ago(2 * HOUR - 61_000),
    },
];

export const SANDBOXES = [
    {
        object: 'sandbox',
        id: rid(400, 1),
        status: 'running',
        image: 'python',
        cpu: 1,
        memory_mb: 2048,
        network: false,
        timeout_s: 3600,
        region: 'eu',
        user_id: ACME,
        end_reason: null,
        created_at: ago(20 * MIN),
        expires_at: later(40 * MIN),
        terminated_at: null,
    },
    {
        object: 'sandbox',
        id: rid(400, 2),
        status: 'terminated',
        image: 'node',
        cpu: 0.5,
        memory_mb: 1024,
        network: ['registry.npmjs.org', '*.github.com'],
        timeout_s: 600,
        region: null,
        user_id: null,
        end_reason: 'timeout',
        created_at: ago(1 * DAY),
        expires_at: ago(1 * DAY - 10 * MIN),
        terminated_at: ago(1 * DAY - 10 * MIN),
    },
];

/** `sandbox.exec` operations for the first sandbox (and one for another sandbox, which the drawer must skip). */
export const EXEC_OPERATIONS = [
    { id: fixtureId(4, 311), sandboxId: SANDBOXES[0].id, command: 'python -c "print(2 + 2)"', status: 'succeeded', at: ago(15 * MIN), result: { stdout: '4\n', stderr: '', exit_code: 0 } },
    { id: fixtureId(4, 312), sandboxId: rid(400, 9), command: 'ls /workspace', status: 'succeeded', at: ago(14 * MIN), result: { stdout: '', stderr: '', exit_code: 0 } },
];

function execView(op: (typeof EXEC_OPERATIONS)[number], withInput: boolean) {
    return {
        object: 'operation',
        id: op.id,
        kind: 'sandbox.exec',
        status: op.status,
        summary: op.command,
        user_id: ACME,
        key_id: CONSOLE_KEY_ID,
        agent_id: null,
        ...(withInput ? { input: { sandbox_id: op.sandboxId, command: op.command } } : {}),
        result: op.result,
        error: null,
        created_at: op.at,
        updated_at: op.at,
        events: [],
    };
}

/** The bought number and the ones brought from elsewhere (designed). */
function phoneNumbers(r: FixtureRequest): { id: string; user_id: string | null; source: string }[] {
    return [...PHONE_NUMBERS, ...broughtNumbers(r.set)];
}

function listed<T extends { user_id: string | null }>(r: FixtureRequest, rows: readonly T[]): FixtureReply {
    return pageList(r, rows.filter((row) => userMatches(r.query, row.user_id)));
}

const resourceRoutes: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/channels',
        reply: (r) => {
            // Designed: a workspace's channels (`workspace_id`), here beside the ones in none.
            const workspace = r.query.get('workspace_id');
            return listed(r, ALL_CHANNELS.filter((c) => !workspace || c.workspace_id === workspace));
        },
    },
    { method: 'GET', path: '/v1/channels/:id', reply: (r) => found(ALL_CHANNELS.find((c) => c.id === r.params.id), 'channel') },
    {
        method: 'GET',
        path: '/v1/channels/:id/messages',
        reply: (r) => {
            const rows = [...CHANNEL_MESSAGES, ...WORKSPACE_CHANNEL_MESSAGES].filter((m) => m.channel_id === r.params.id);
            const after = r.query.get('after');
            const at = after ? rows.findIndex((m) => m.id === after) : -1;
            return list(rows.slice(at + 1));
        },
    },
    {
        method: 'POST',
        path: '/v1/channels/:id/messages',
        reply: (r) =>
            ok(message(99, r.params.id, { type: 'account', id: null, name: 'You' }, String((r.body as { text?: string })?.text ?? ''), new Date(FIXTURE_NOW_MS).toISOString())),
    },
    {
        method: 'GET',
        path: '/v1/channels/:id/triggers',
        reply: (r) => list(CHANNEL_TRIGGERS.filter((t) => t.channel_id === r.params.id)),
    },
    { method: 'POST', path: '/v1/channels/:id/close', reply: (r) => found(ALL_CHANNELS.map((c) => ({ ...c, status: 'closed', halt_reason: 'closed' })).find((c) => c.id === r.params.id), 'channel') },
    {
        method: 'POST',
        path: '/v1/channels',
        reply: (r) => {
            const body = r.body as { name: string; workspace_id?: string };
            return ok({ ...CHANNELS[0], id: rid(100, 9), name: body.name, user_id: r.headers.get('NoClick-User'), workspace_id: body.workspace_id ?? null, members: [], spent_usd: 0, created_at: new Date(FIXTURE_NOW_MS).toISOString() });
        },
    },

    { method: 'GET', path: '/v1/inboxes', reply: (r) => listed(r, INBOXES) },
    { method: 'GET', path: '/v1/inboxes/:id', reply: (r) => found(INBOXES.find((i) => i.id === r.params.id), 'inbox') },
    {
        method: 'GET',
        path: '/v1/inboxes/:id/messages',
        reply: (r) => {
            // As the route: oldest first, after `after`, `limit` (default 50, at most 200) at a time.
            const rows = INBOX_MESSAGES.filter((m) => m.inbox_id === r.params.id);
            const after = r.query.get('after');
            const start = after ? rows.findIndex((m) => m.id === after) + 1 : 0;
            return list(rows.slice(start, start + Math.min(Number(r.query.get('limit') ?? 50), 200)));
        },
    },
    { method: 'GET', path: '/v1/inboxes/:id/messages/:mid', reply: (r) => found(INBOX_MESSAGES.find((m) => m.id === r.params.mid), 'message') },
    // A listing leaves each thread's messages out, as the route does.
    { method: 'GET', path: '/v1/inboxes/:id/threads', reply: (r) => list(inboxThreads(r.params.id).map((thread) => ({ ...thread, messages: undefined }))) },
    { method: 'GET', path: '/v1/inboxes/:id/threads/:tid', reply: (r) => found(inboxThreads(r.params.id).find((t) => t.id === r.params.tid), 'thread') },
    {
        // New mail from an inbox on the account's domain: queued until it goes, as the route answers it.
        method: 'POST',
        path: '/v1/inboxes/:id/messages',
        reply: (r) => {
            const body = (r.body ?? {}) as { to?: string; subject?: string; text?: string; thread_id?: string };
            const inbox = INBOXES.find((i) => i.id === r.params.id);
            const id = fixtureId(0, 298);
            return ok({
                object: 'inbox_message', id, inbox_id: r.params.id, direction: 'outbound', conversation: `inbox:${r.params.id}:${body.thread_id ?? id}`,
                from: inbox?.address ?? null, to: body.to ?? null, subject: body.subject ?? null, text: body.text ?? null, html: null, attachments: [],
                status: 'sending', delivery_status: null, delivery_error: null, received_at: new Date(FIXTURE_NOW_MS).toISOString(),
            });
        },
    },
    {
        method: 'POST',
        path: '/v1/inboxes/:id/messages/:mid/reply',
        reply: (r) =>
            ok({ object: 'inbox_reply', id: fixtureId(0, 299), inbox_id: r.params.id, message_id: r.params.mid, text: (r.body as { text: string }).text, status: 'sent', delivery_status: 'queued', created_at: new Date(FIXTURE_NOW_MS).toISOString() }),
    },
    { method: 'DELETE', path: '/v1/inboxes/:id', reply: (r) => ok({ id: r.params.id, deleted: true }) },
    {
        method: 'POST',
        path: '/v1/inboxes',
        reply: (r) => {
            const body = (r.body ?? {}) as { local_part?: string; agent_id?: string };
            return ok({ object: 'inbox', id: rid(200, 9), address: `${body.local_part ?? 'inbox-9c1e'}@in.noclick.app`, agent_id: body.agent_id ?? null, user_id: r.headers.get('NoClick-User'), created_at: new Date(FIXTURE_NOW_MS).toISOString() });
        },
    },

    { method: 'GET', path: '/v1/phone_numbers', reply: (r) => listed(r, phoneNumbers(r)) },
    {
        method: 'GET',
        path: '/v1/phone_numbers/available',
        reply: (r) => {
            const area = r.query.get('area_code') ?? '415';
            return list(
                [1, 2, 3].map((n) => ({
                    object: 'available_phone_number', number: `+1${area}555017${n}`, country: 'US', type: 'local',
                    monthly_usd: NUMBER_MONTHLY_USD, upfront_usd: NUMBER_UPFRONT_USD, locality: 'San Francisco', region: 'CA',
                    capabilities: ['voice', 'SMS'],
                    requirements: { needs: 'none', items: [] }, texting: 'registration',
                }))
            );
        },
    },
    {
        method: 'GET',
        path: '/v1/phone_numbers/coverage',
        reply: () =>
            list([
                { object: 'phone_number_coverage', country: 'US', types: ['local', 'toll_free'], texting_types: ['local'] },
                { object: 'phone_number_coverage', country: 'GB', types: ['local', 'mobile'], texting_types: ['mobile'] },
            ]),
    },
    {
        method: 'GET',
        path: '/v1/phone_numbers/places',
        reply: () => list(['415', '628'].map((value) => ({ object: 'phone_number_place', kind: 'area_code', value, region: 'CA' }))),
    },
    connectableRoute,
    { method: 'GET', path: '/v1/phone_numbers/:id', reply: (r) => found(phoneNumbers(r).find((p) => p.id === r.params.id), 'phone number') },
    {
        method: 'PATCH',
        path: '/v1/phone_numbers/:id',
        reply: (r) => found(phoneNumbers(r).map((p) => ({ ...p, ...(r.body as object) })).find((p) => p.id === r.params.id), 'phone number'),
    },
    {
        method: 'GET',
        path: '/v1/phone_numbers/:id/calls',
        reply: (r) => {
            const direction = r.query.get('direction');
            const rows = PHONE_CALLS.filter((c) => c.phone_number_id === r.params.id && (!direction || c.direction === direction));
            return list([...rows].sort((a, b) => b.created_at.localeCompare(a.created_at)));
        },
    },
    {
        method: 'POST',
        path: '/v1/phone_numbers',
        reply: (r) => {
            const body = (r.body ?? {}) as { number: string; max_monthly_usd: number; max_upfront_usd?: number };
            if (body.max_monthly_usd < NUMBER_MONTHLY_USD) return apiError(402, 'price_exceeded', `This number costs $${NUMBER_MONTHLY_USD.toFixed(2)} a month, more than max_monthly_usd.`, `Raise max_monthly_usd to at least ${NUMBER_MONTHLY_USD}.`);
            if ((body.max_upfront_usd ?? 0) < NUMBER_UPFRONT_USD) return apiError(402, 'price_exceeded', `This number costs $${NUMBER_UPFRONT_USD.toFixed(2)} once, more than max_upfront_usd.`, `Raise max_upfront_usd to at least ${NUMBER_UPFRONT_USD}.`);
            return ok({ ...PHONE_NUMBERS[0], id: rid(300, 9), number: body.number, agent_id: null, user_id: r.headers.get('NoClick-User'), created_at: new Date(FIXTURE_NOW_MS).toISOString() });
        },
    },
    {
        method: 'POST',
        path: '/v1/phone_numbers/:id/answer',
        // The whole answering setup: an option left out goes back to its default.
        reply: (r) => {
            const body = r.body as { agent_id: string; transfer_to?: string; texts?: boolean; callers?: string };
            const setup = { agent_id: body.agent_id, transfer_to: body.transfer_to ?? null, texts: body.texts ?? false, callers: body.callers ?? 'anyone' };
            return found(phoneNumbers(r).map((p) => ({ ...p, ...setup })).find((p) => p.id === r.params.id), 'phone number');
        },
    },
    {
        method: 'POST',
        path: '/v1/phone_numbers/:id/calls',
        reply: (r) => ({
            status: 202,
            body: { object: 'operation', id: fixtureId(4, 399), kind: 'phone.call', status: 'queued', summary: (r.body as { to: string }).to, user_id: ACME, created_at: new Date(FIXTURE_NOW_MS).toISOString(), updated_at: new Date(FIXTURE_NOW_MS).toISOString(), events: [] },
        }),
    },
    {
        method: 'DELETE',
        path: '/v1/phone_numbers/:id',
        reply: (r) =>
            phoneNumbers(r).find((p) => p.id === r.params.id)?.source === 'connected'
                ? apiError(409, 'conflict', "A connected number is your phone provider's, so NoClick can't release it.", 'Disconnect it to hand it back to your provider account.')
                : ok({ id: r.params.id, deleted: true }),
    },

    {
        method: 'GET',
        path: '/v1/sandboxes',
        reply: (r) => {
            const status = r.query.get('status');
            return listed(r, SANDBOXES.filter((s) => !status || (status === 'live' ? s.status !== 'terminated' && s.status !== 'failed' : s.status === status)));
        },
    },
    { method: 'GET', path: '/v1/sandboxes/:id', reply: (r) => found(SANDBOXES.find((s) => s.id === r.params.id), 'sandbox') },
    {
        method: 'POST',
        path: '/v1/sandboxes/:id/exec',
        reply: (r) => {
            const command = String((r.body as { command?: string })?.command ?? '');
            return ok({ object: 'exec_result', stdout: command.includes('fail') ? '' : `ran: ${command}\n`, stderr: command.includes('fail') ? 'boom\n' : '', exit_code: command.includes('fail') ? 1 : 0 });
        },
    },
    { method: 'GET', path: '/v1/sandboxes/:id/files', reply: (r) => ({ status: 200, raw: `contents of ${r.query.get('path')}` }) },
    {
        method: 'DELETE',
        path: '/v1/sandboxes/:id',
        reply: (r) => found(SANDBOXES.map((s) => ({ ...s, status: 'terminated', end_reason: 'deleted', terminated_at: new Date(FIXTURE_NOW_MS).toISOString() })).find((s) => s.id === r.params.id), 'sandbox'),
    },
];

/**
 * The sandbox drawer's exec history. Page B's fixtures own /v1/operations in the
 * lab, so these are passed to the harness by the tests that need them.
 */
export const EXEC_ROUTES: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/operations',
        reply: (r) => pageList(r, r.query.get('kind') === 'sandbox.exec' ? EXEC_OPERATIONS.map((op) => execView(op, false)) : []),
    },
    {
        method: 'GET',
        path: '/v1/operations/:id',
        reply: (r) => {
            const op = EXEC_OPERATIONS.find((o) => o.id === r.params.id);
            return op ? ok(execView(op, true)) : apiError(404, 'not_found', 'No such operation.');
        },
    },
];

/**
 * Cap edits and the integration catalog. Pages A and B serve these paths in the
 * lab (their fixtures match first); tests here pass these so they don't depend
 * on another page's canned data.
 */
export const SHARED_WRITE_ROUTES: FixtureRoute[] = [
    {
        method: 'PATCH',
        path: '/v1/keys/:id',
        reply: (r) => {
            const key = KEYS.find((k) => k.id === r.params.id);
            return key ? ok({ ...key, ...(r.body as object) }) : apiError(404, 'not_found', 'No such key.');
        },
    },
    {
        method: 'PATCH',
        path: '/v1/users/:id',
        reply: (r) => {
            const user = USERS.find((u) => u.id === r.params.id);
            return user ? ok({ ...user, ...(r.body as object) }) : apiError(404, 'not_found', 'No such user.');
        },
    },
    {
        method: 'PATCH',
        path: '/v1/agents/:id',
        reply: (r) => {
            // As `agents/service._owned`: a write sees account agents and those of the user it acts in.
            const acting = r.headers.get('NoClick-User');
            const agent = AGENTS.find((a) => a.id === r.params.id && (a.user_id === null || a.user_id === acting));
            return agent ? ok({ ...agent, ...(r.body as object) }) : apiError(404, 'not_found', 'No such agent.');
        },
    },
    {
        method: 'GET',
        path: '/v1/integrations/:name/operations',
        reply: (r) => {
            const operations = INTEGRATION_OPERATIONS[r.params.name];
            if (!operations) return apiError(404, 'not_found', `There is no integration named '${r.params.name}'.`);
            return list(operations.map((name) => ({ name, description: null, parameters: {}, read_only: null, scopes: [], needs_account: true })));
        },
    },
];

export const routes: FixtureRoute[] = [...humanRoutes, ...usageRoutes, ...policyRoutes, ...brandRoutes, ...resourceRoutes];

export { SHOT_TARGETS };
