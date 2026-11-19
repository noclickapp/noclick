// Fixtures for the designed agent features and hosted MCP servers: triggers
// (and the `digest` automation, served here beside the core agents), pause,
// memory in its account and user layers, workspace files, share links, test
// runs and the `crm-tools` server. Stateless like the other pages: a write
// answers the row it would leave, and the page keeps what it answers.
import {
    AGENTS,
    DAY,
    FIXTURE_NOW_MS,
    HOUR,
    LAB_EXTRA_AGENTS,
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
import { INBOXES, PHONE_NUMBERS, userMatches } from './c';
import { CONNECTIONS } from './a';
import { BUCKETS, DATABASES } from './d_data';
import { REPOS } from './e_build';
import { SECRETS, VOLUMES } from './k_files';
import { QUEUES } from './l_state';
import { AGENT_LIVE, ORCHESTRATION_AGENTS } from './n_orchestration';

type Json = Record<string, unknown>;

const [SUPPORT, CONCIERGE] = AGENTS;
const [ACME] = USERS;
const now = () => new Date(FIXTURE_NOW_MS).toISOString();
/** Designed-feature ids under kind digit 9, from 7100 up (grants use 9's low numbers). */
const did = (n: number) => fixtureId(9, 7100 + n);

// ── agents ─────────────────────────────────────────────────────────────────

export const DIGEST = {
    object: 'agent',
    id: fixtureId(3, 20),
    name: 'digest',
    instructions: "You summarize yesterday's support tickets for the team.",
    model: 'anthropic/claude-sonnet-4.6',
    harness: 'sdk',
    // Exa's search needs no account, so it needs no connection: it runs on NoClick's key. The send is pinned to
    // ops, who also answers its questions and takes what needs a person, and it files each summary in the
    // uploads bucket (designed).
    tools: [
        'exa.search',
        { tool: 'gmail.send_email', bind: { to: 'ops@yourco.test' } },
        { human: { email: 'ops@yourco.test' }, tools: ['notify', 'ask', 'hand_off'] },
        `bucket:${BUCKETS[0].id}.put`,
    ] as (string | Json)[],
    can_request: [] as string[],
    grants: [] as Json[],
    user_id: null,
    workflow_id: fixtureId(8, 20),
    parent_id: null,
    ttl_s: null,
    expires_at: null,
    budget_usd_per_month: 10,
    created_at: ago(21 * DAY),
    paused: false,
    trigger_kinds: ['cron', 'approval'],
    browser_profile_id: null,
    card_id: null,
    volumes: {},
    secret_ids: [] as string[],
    // It reads the team's day in London and needs no shell for a summary (designed).
    timezone: 'Europe/London',
    shell: false,
    network: null,
    repos: [] as Json[],
};

/** What each agent's triggers make of it: the kinds its row carries. */
const KINDS: Record<string, string[]> = {
    [SUPPORT.id]: ['event', 'email', 'call', 'queue'],
    [CONCIERGE.id]: ['webhook', 'event'],
};

const [DATASETS] = VOLUMES;
const [OPENAI] = SECRETS;
const ANA_ASSISTANT_ID = AGENTS.find((a) => a.name === 'assistant' && a.user_id === USERS[1].id)!.id;

const [BOOKING_DB] = DATABASES;
/** Your account's support mailbox, shared into Acme's concierge. */
const SUPPORT_GMAIL = CONNECTIONS.find((c) => c.user_id === null && c.name === 'gmail')!;

const CODER_ID = AGENTS.find((a) => a.name === 'coder')!.id;
const AGENT_TOOLS_REPO = REPOS.find((r) => r.name === 'agent-tools')!;

/**
 * Designed fields beyond the defaults: concierge reads the bookings and emails your support team; Ana's
 * assistant has a disk and a key; coder works in New York hours on the docs repository (pushing only
 * docs and fix branches) and your agent-tools repo, and its shell reaches only GitHub and the docs host.
 */
const EXTRA: Record<string, Json> = {
    [CONCIERGE.id]: {
        tools: [...CONCIERGE.tools, `database:${BOOKING_DB.id}.query`, `database:${BOOKING_DB.id}.schema`, `connection:${SUPPORT_GMAIL.id}.send_email_message`],
    },
    [ANA_ASSISTANT_ID]: { volumes: { '/data': DATASETS.id }, secret_ids: [OPENAI.id] },
    [CODER_ID]: {
        timezone: 'America/New_York',
        network: ['api.github.com', '*.readthedocs.io'],
        repos: [
            { connection: 'github', repository: 'acme/docs', branch: 'main', push: ['docs/*', 'fix/*'] },
            { repo_id: AGENT_TOOLS_REPO.id, path: 'tools' },
        ],
    },
};

/** The core agents with the designed fields, then the automation, then the coordinator and the agents it spawned (n_orchestration.ts). */
export const LAB_AGENTS: Json[] = [
    ...AGENTS.map((a) => ({
        ...a,
        paused: false,
        trigger_kinds: KINDS[a.id] ?? [],
        browser_profile_id: null,
        card_id: null,
        volumes: {},
        secret_ids: [],
        timezone: null,
        network: null,
        shell: null,
        repos: [],
        ...EXTRA[a.id],
    })),
    DIGEST,
    ...ORCHESTRATION_AGENTS,
].map((a) => ({ ...a, ...AGENT_LIVE[String(a.id)] }));
LAB_EXTRA_AGENTS.push(DIGEST, ...ORCHESTRATION_AGENTS); // b.ts's edit, Try it, delete and card routes find them

const LAST_ACTIVE = (a: Json) => (typeof a.last_active_at === 'string' ? Date.parse(a.last_active_at) : -Infinity);

/** The agents list's designed filters (`parent_id`, `status`, `active_since`, `temporary`, `harness`) and `order`. */
function filteredAgents(r: FixtureRequest): Json[] {
    const q = r.query;
    const since = q.get('active_since');
    const temporary = q.get('temporary');
    const rows = LAB_AGENTS.filter(
        (a) =>
            (!q.get('parent_id') || a.parent_id === q.get('parent_id')) &&
            (!q.get('status') || a.status === q.get('status')) &&
            (!q.get('harness') || a.harness === q.get('harness')) &&
            (!since || LAST_ACTIVE(a) >= Date.parse(since)) &&
            (temporary === null || (a.ttl_s != null) === (temporary === 'true'))
    );
    return q.get('order') === 'last_active' ? [...rows].sort((x, y) => LAST_ACTIVE(y) - LAST_ACTIVE(x)) : rows;
}

const agentOf = (id: string) => LAB_AGENTS.find((a) => a.id === id);

// ── triggers ───────────────────────────────────────────────────────────────

function trigger(n: number, kind: string, spec: Json, fields: Json = {}): Json {
    return {
        object: 'agent_trigger',
        id: did(n),
        kind,
        spec,
        status: 'active',
        url: null,
        next_run: null,
        last_fired_at: null,
        error: null,
        created_at: ago(20 * DAY),
        ...fields,
    };
}

/** Monday 08:00 London (07:00 UTC); the lab's clock reads Saturday afternoon. */
export const DIGEST_NEXT_RUN = '2026-09-28T07:00:00.000Z';

export const TRIGGERS: Record<string, Json[]> = {
    [SUPPORT.id]: [
        trigger(1, 'event', { connection: 'stripe', event: 'invoice.payment_failed', filters: {}, message: 'Email the customer that the payment failed and how to update their card.' }, {
            last_fired_at: ago(2 * HOUR),
        }),
        trigger(2, 'email', { inbox_id: INBOXES[0].id, address: INBOXES[0].address }, { last_fired_at: ago(35 * MIN), created_at: INBOXES[0].created_at }),
        trigger(3, 'call', { phone_number_id: PHONE_NUMBERS[0].id, number: PHONE_NUMBERS[0].number }, { last_fired_at: ago(DAY + 3 * HOUR), created_at: PHONE_NUMBERS[0].created_at }),
        trigger(7, 'queue', { queue: QUEUES[0].name, batch_size: 1, conversation: 'invoice-{invoice}', message: 'Chase this unpaid invoice. Be polite and link the payment page.' }, {
            last_fired_at: ago(4 * MIN),
            created_at: QUEUES[0].created_at,
        }),
    ],
    [CONCIERGE.id]: [
        trigger(4, 'webhook', { name: 'bookings', conversation: 'booking-{booking.id}', message: 'A booking request came in from the website. Confirm the table with the customer.' }, {
            url: 'https://hooks.noclick.app/t/whk_7Hq2mV9xKp4sLcWd',
            last_fired_at: ago(40 * MIN),
            created_at: ago(3 * HOUR),
        }),
        trigger(5, 'event', { connection: 'stripe', event: 'payment_intent.succeeded', filters: {}, message: 'Tell the customer their deposit arrived.' }, {
            status: 'error',
            error: "Acme's stripe connection is still waiting to connect, so its events can't reach the agent.",
            created_at: ago(3 * HOUR),
        }),
    ],
    [DIGEST.id]: [
        trigger(6, 'cron', { cron: '0 8 * * 1-5', tz: 'Europe/London', message: 'Email the overnight summary to ops@yourco.test' }, {
            next_run: DIGEST_NEXT_RUN,
            last_fired_at: '2026-09-25T07:00:00.000Z',
            created_at: DIGEST.created_at,
        }),
        // Your rules hold its send: an answered approval wakes it in that call's conversation.
        trigger(8, 'approval', {}, { last_fired_at: '2026-09-25T07:04:00.000Z', created_at: DIGEST.created_at }),
    ],
};

const DEFINED = ['cron', 'webhook', 'event', 'queue'];

/** Each added trigger gets an id of its own, as the API would give it. */
let added = 0;

function addTrigger(r: FixtureRequest): FixtureReply {
    if (!agentOf(r.params.id)) return apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
    const { kind, ...spec } = (r.body ?? {}) as Json;
    if (!DEFINED.includes(String(kind))) {
        return apiError(400, 'invalid_request', `A trigger's kind is cron, webhook, event or queue, not ${String(kind)}.`, 'Mail and calls wake an agent through its inbox or phone number.');
    }
    if (kind === 'cron' && String(spec.cron ?? '').trim().split(/\s+/).length !== 5) {
        return apiError(400, 'invalid_request', `'${String(spec.cron ?? '')}' is not a five-field cron expression.`, 'Write minute, hour, day of month, month and day of week, like 0 8 * * 1-5.');
    }
    return {
        status: 201,
        body: {
            object: 'agent_trigger',
            id: did(90 + ++added),
            kind,
            spec,
            status: 'active',
            url: kind === 'webhook' ? 'https://hooks.noclick.app/t/whk_N3wR8tLq2Zc6Yp' : null,
            next_run: kind === 'cron' ? new Date(FIXTURE_NOW_MS + DAY).toISOString() : null,
            last_fired_at: null,
            error: null,
            created_at: now(),
        },
    };
}

function removeTrigger(r: FixtureRequest): FixtureReply {
    const row = (TRIGGERS[r.params.id] ?? []).find((t) => t.id === r.params.trigger);
    if (row && !DEFINED.includes(String(row.kind))) {
        if (row.kind === 'approval') return apiError(400, 'invalid_request', 'An approval trigger follows your approval rules.', 'Change the rules that hold its tools.');
        return apiError(400, 'invalid_request', `A ${String(row.kind)} trigger belongs to its ${row.kind === 'email' ? 'inbox' : 'phone number'}.`, 'Change which agent it wakes there.');
    }
    return ok({ object: 'agent_trigger', id: r.params.trigger, deleted: true });
}

// ── memory ─────────────────────────────────────────────────────────────────

interface Entry {
    name: string;
    description: string;
    content: string;
    version: number;
    updated_at: string;
    updated_by: 'agent' | 'api' | 'console';
    user_id: string | null;
}

const entry = (name: string, fields: Omit<Entry, 'name'>): Entry => ({ name, ...fields });

export const MEMORY: Record<string, Entry[]> = {
    [SUPPORT.id]: [
        entry('refunds', {
            description: 'Our refund rules',
            content: 'Refund within 30 days of purchase, to the original card.\nDuplicate charges are refunded at once, without asking.\nNo refunds on gift cards.',
            version: 3,
            updated_at: ago(2 * DAY),
            updated_by: 'agent',
            user_id: null,
        }),
        entry('tone', {
            description: 'How to write to customers',
            content: "Short and warm. Use the customer's first name. Never promise a date the ledger doesn't show.",
            version: 1,
            updated_at: ago(30 * DAY),
            updated_by: 'api',
            user_id: null,
        }),
        entry('escalation', {
            description: 'When to hand a ticket to a person',
            content: 'Hand off anything over $500, any chargeback, and any customer who asks for a person twice.',
            version: 2,
            updated_at: ago(9 * DAY),
            updated_by: 'console',
            user_id: null,
        }),
        entry('billing-contact', {
            description: "Who pays Acme's invoices",
            content: 'Invoices go to ops@acme.test. Dana in finance approves anything over $500.',
            version: 2,
            updated_at: ago(5 * HOUR),
            updated_by: 'agent',
            user_id: ACME.id,
        }),
    ],
    [CONCIERGE.id]: [
        entry('regulars', {
            description: "Acme's regular bookings",
            content: 'Thursday team lunch for 8 at Luca, 12:30. The CEO prefers a window table.',
            version: 4,
            updated_at: ago(90 * MIN),
            updated_by: 'agent',
            user_id: ACME.id,
        }),
    ],
    [DIGEST.id]: [
        entry('format', {
            description: 'How the summary is laid out',
            content: 'Three sections: resolved, waiting on us, waiting on the customer. At most ten lines each.',
            version: 1,
            updated_at: ago(21 * DAY),
            updated_by: 'api',
            user_id: null,
        }),
    ],
};

/** The user a call acts as (its header, your id for them), or null for the account. */
function acting(r: FixtureRequest): string | null {
    return r.headers.get('NoClick-User');
}

/** The layer a memory call acts in: the one `user_id` names (`none`: the account's), the user it acts as, or the agent's own user. */
function layerOf(r: FixtureRequest): string | null {
    const named = r.query.get('user_id');
    if (named) return named === 'none' ? null : named;
    return acting(r) ?? (agentOf(r.params.id)?.user_id as string | null) ?? null;
}

const entryRow = (e: Entry, withContent = true) => ({ object: 'memory_entry', ...e, content: withContent ? e.content : null });

function memoryList(r: FixtureRequest): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    const layer = layerOf(r);
    const rows = r.set === 'populated' ? (MEMORY[r.params.id] ?? []) : [];
    const q = (r.query.get('q') ?? '').toLowerCase().trim();
    if (!q) return list(rows.filter((e) => e.user_id === layer).map((e) => entryRow(e, false)));
    // A search reads what the agent sees in that scope: the user's entries and the account's.
    const words = q.split(/\s+/);
    const hits = rows.filter((e) => (e.user_id === layer || e.user_id === null) && words.some((w) => `${e.name} ${e.description} ${e.content}`.toLowerCase().includes(w)));
    return list(hits.slice(0, Number(r.query.get('limit') ?? 10)).map((e) => entryRow(e)));
}

function memoryFind(r: FixtureRequest): Entry | undefined {
    const layer = layerOf(r);
    return (MEMORY[r.params.id] ?? []).find((e) => e.name === r.params.name && e.user_id === layer);
}

function staleVersion(e: Entry, version: unknown): FixtureReply | null {
    if (version === undefined || version === null || Number(version) === e.version) return null;
    return apiError(409, 'conflict', `${e.name} is at version ${e.version}; it changed since you read it.`, 'Read it again and apply your change to what is there now.', {
        current_version: e.version,
    });
}

function memorySave(r: FixtureRequest): FixtureReply {
    const body = (r.body ?? {}) as { content?: string; description?: string; version?: number };
    const existing = memoryFind(r);
    if (existing) {
        const stale = staleVersion(existing, body.version);
        if (stale) return stale;
    } else if (!body.description) {
        return apiError(400, 'invalid_request', 'A new entry needs a description.', 'Say in one line what it holds; the agent sees that line every turn.');
    }
    const saved: Entry = {
        name: r.params.name,
        description: body.description ?? existing!.description,
        content: body.content ?? '',
        version: (existing?.version ?? 0) + 1,
        updated_at: now(),
        updated_by: 'console',
        user_id: layerOf(r),
    };
    return ok(entryRow(saved));
}

function memoryDelete(r: FixtureRequest): FixtureReply {
    const existing = memoryFind(r);
    if (!existing) return apiError(404, 'not_found', `No memory entry named '${r.params.name}'.`);
    return staleVersion(existing, r.query.get('version')) ?? ok({ object: 'memory_entry', name: existing.name, deleted: true });
}

// ── workspace files ────────────────────────────────────────────────────────

const file = (path: string, size: number, modified: string) => ({
    path,
    size_bytes: size,
    modified_at: modified,
    url: `https://files.noclick.app/ws/tok_9fQ2xL7v/${encodeURIComponent(path)}`,
});

/** Files per agent and conversation (conversation keys from Page B's CONVERSATIONS). */
export const WORKSPACES: Record<string, Record<string, Json[]>> = {
    [SUPPORT.id]: {
        'c-7': [
            file('weekly-summary.md', 3_284, ago(15 * MIN)),
            file('tickets-week-38.csv', 18_431, ago(16 * MIN)),
            file('charts/volume-by-day.png', 64_120, ago(16 * MIN)),
        ],
        'c-refund': [file('invoice-1042.pdf', 41_902, ago(3 * HOUR))],
    },
};

// ── share links ────────────────────────────────────────────────────────────

const shareRow = (agentId: string, fields: Json = {}) => ({
    object: 'share_link',
    agent_id: agentId,
    url: agentId === SUPPORT.id ? 'https://noclick.com/a/lnk_4Tq8wZr2Hm' : `https://noclick.com/a/lnk_${agentId.slice(-4)}Ne7Qa`,
    enabled: true,
    created_at: agentId === SUPPORT.id ? ago(12 * DAY) : now(),
    rotated_at: null,
    ...fields,
});

// ── test runs ──────────────────────────────────────────────────────────────

/** A finished rehearsal; the page never waits on it. */
function rehearsal(r: FixtureRequest): FixtureReply {
    const agent = agentOf(r.params.id);
    if (!agent) return apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
    const body = (r.body ?? {}) as { message?: string; scenario?: string };
    const toolCalls = [
        {
            tool: 'stripe__list_invoices',
            arguments: { customer: 'cus_R2kd8', limit: 5 },
            result: { data: [{ id: 'in_1042', amount_paid: 4900, status: 'paid' }, { id: 'in_1042-dup', amount_paid: 4900, status: 'paid' }] },
        },
        {
            tool: 'gmail__send_email',
            arguments: { to: 'dana@acme.test', subject: 'Your duplicate charge' },
            result: { id: 'msg_sim_71c', status: 'sent' },
        },
    ];
    const reply = 'You were charged twice for invoice 1042. I refunded the duplicate $49.00 to your card and emailed you the receipt; it shows in 5 to 10 days.';
    return {
        status: 201,
        body: {
            object: 'operation',
            id: fixtureId(4, 700),
            kind: 'agent.rehearse',
            status: 'succeeded',
            agent_id: agent.id,
            user_id: agent.user_id ?? null,
            summary: body.message ?? null,
            result: {
                reply,
                tool_calls: toolCalls,
                transcript: [
                    { role: 'user', text: body.message ?? '' },
                    ...toolCalls.map((c) => ({ role: 'tool', tool: c.tool, arguments: c.arguments, result: c.result })),
                    { role: 'assistant', text: reply },
                ],
                scenario: body.scenario ?? null,
                cost_usd: 0.021,
            },
            error: null,
            created_at: now(),
            updated_at: now(),
        },
    };
}

// ── MCP servers ────────────────────────────────────────────────────────────

export const MCP_SERVERS = [
    {
        object: 'mcp_server',
        id: did(201),
        name: 'crm-tools',
        url: 'https://mcp.noclick.app/s/mcs_Vb82kQ4nXe7LsPw',
        tools: ['hubspot', 'search'],
        tool_count: 38,
        user_id: ACME.id,
        created_at: ago(12 * DAY),
        last_client_at: ago(6 * MIN),
    },
];

export const MCP_CLIENTS: Record<string, Json[]> = {
    [MCP_SERVERS[0].id]: [
        { object: 'mcp_client', name: 'Claude', version: '1.8.3', first_seen_at: ago(11 * DAY), last_seen_at: ago(6 * MIN), tool_count: 38 },
        // Listed its tools before search was added; clients list again when a session starts.
        { object: 'mcp_client', name: 'cursor', version: '1.6.2', first_seen_at: ago(3 * DAY), last_seen_at: ago(2 * DAY), tool_count: 31 },
    ],
};

/** Tools a ref serves in the lab: a connection's operations, or one. */
const toolCountOf = (tools: unknown) => (Array.isArray(tools) ? tools.reduce<number>((n, t) => n + (String(t).includes('.') || ['search', 'fetch'].includes(String(t)) ? 1 : 37), 0) : 0);

const serverOf = (id: string) => MCP_SERVERS.find((s) => s.id === id);

function serverReply(r: FixtureRequest, change: (s: Json) => Json): FixtureReply {
    const server = serverOf(r.params.id);
    return server ? ok(change(server)) : apiError(404, 'not_found', `MCP server ${r.params.id} not found.`);
}

/** Where each agent stands, as `GET /v1/agents/states` reads it: one working, the rest idle since they last ran. */
function agentState(a: Json): Json {
    const working = a.id === SUPPORT.id;
    return {
        agent_id: a.id,
        name: a.name,
        harness: a.harness,
        state: working ? 'working' : 'idle',
        conversation: working ? 'main' : null,
        now: working ? { tool: 'gmail__send_email', kind: 'tool', line: 'Sends the refund confirmation', since: ago(2 * MIN) } : null,
        waiting: { asks: 0, held_calls: 0, requests: 0, total: 0 },
        turn_started_at: working ? ago(3 * MIN) : null,
        last_active_at: a.last_active_at ?? null,
        failed: null,
        waking: null,
    };
}

export const routes: readonly FixtureRoute[] = [
    // Agents: the core rows plus the designed fields, and the automation.
    { method: 'GET', path: '/v1/agents', reply: (r) => pageList(r, filteredAgents(r)) },
    // Before `/v1/agents/:id`, which would take `states` for an agent's id.
    {
        method: 'GET',
        path: '/v1/agents/states',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : ok({ object: 'list', data: r.set === 'populated' ? LAB_AGENTS.map(agentState) : [], read_at: now() })),
    },
    {
        method: 'GET',
        path: '/v1/agents/:id',
        reply: (r) => {
            const agent = agentOf(r.params.id);
            return agent && (agent.id !== DIGEST.id || r.set === 'populated') ? ok(agent) : apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
        },
    },
    {
        method: 'GET',
        path: '/v1/agents/:id/triggers',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : list(r.set === 'populated' ? (TRIGGERS[r.params.id] ?? []) : [])),
    },
    { method: 'POST', path: '/v1/agents/:id/triggers', reply: addTrigger },
    { method: 'DELETE', path: '/v1/agents/:id/triggers/:trigger', reply: removeTrigger },
    ...(['pause', 'resume'] as const).map(
        (verb): FixtureRoute => ({
            method: 'POST',
            path: `/v1/agents/:id/${verb}`,
            reply: (r) => {
                const agent = agentOf(r.params.id);
                return agent ? ok({ ...agent, paused: verb === 'pause' }) : apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
            },
        })
    ),
    { method: 'GET', path: '/v1/agents/:id/memory', reply: memoryList },
    {
        method: 'GET',
        path: '/v1/agents/:id/memory/:name',
        reply: (r) => {
            const found = memoryFind(r);
            return found ? ok(entryRow(found)) : apiError(404, 'not_found', `No memory entry named '${r.params.name}'.`);
        },
    },
    { method: 'PUT', path: '/v1/agents/:id/memory/:name', reply: memorySave },
    { method: 'DELETE', path: '/v1/agents/:id/memory/:name', reply: memoryDelete },
    {
        method: 'GET',
        path: '/v1/agents/:id/workspace',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const files = r.set === 'populated' ? (WORKSPACES[r.params.id]?.[r.query.get('conversation') ?? ''] ?? []) : [];
            return list(files);
        },
    },
    {
        method: 'GET',
        path: '/v1/agents/:id/workspace/url',
        reply: (r) => ok({ url: file(r.query.get('path') ?? '', 0, now()).url, expires_at: new Date(FIXTURE_NOW_MS + HOUR).toISOString() }),
    },
    {
        method: 'GET',
        path: '/v1/agents/:id/share',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            return r.set === 'populated' && r.params.id === SUPPORT.id
                ? ok(shareRow(SUPPORT.id))
                : apiError(404, 'not_found', 'This agent has no share link.', 'Turn one on with agent.share().');
        },
    },
    { method: 'POST', path: '/v1/agents/:id/share', reply: (r) => (agentOf(r.params.id) ? ok(shareRow(r.params.id)) : apiError(404, 'not_found', 'No such agent.')) },
    { method: 'PATCH', path: '/v1/agents/:id/share', reply: (r) => ok(shareRow(r.params.id, { enabled: (r.body as { enabled?: boolean })?.enabled ?? true })) },
    {
        method: 'POST',
        path: '/v1/agents/:id/share/rotate',
        reply: (r) => ok(shareRow(r.params.id, { url: `https://noclick.com/a/lnk_R0t8dKw5Ys`, rotated_at: now() })),
    },
    { method: 'POST', path: '/v1/agents/:id/rehearsals', reply: rehearsal },
    {
        method: 'POST',
        path: '/v1/agents/:id/conversations/:conversation/hand_back',
        reply: (r) => (agentOf(r.params.id) ? { status: 204 } : apiError(404, 'not_found', `Agent ${r.params.id} not found.`)),
    },
    // Hosted MCP servers.
    {
        method: 'GET',
        path: '/v1/mcp_servers',
        reply: (r) => {
            // A filtered read names its users; otherwise it sees the user it acts as (or the account's own).
            const scoped = r.query.has('user_id') ? MCP_SERVERS.filter((s) => userMatches(r.query, s.user_id)) : MCP_SERVERS.filter((s) => s.user_id === acting(r));
            const name = r.query.get('name');
            return pageList(r, scoped.filter((s) => !name || s.name === name));
        },
    },
    {
        method: 'POST',
        path: '/v1/mcp_servers',
        reply: (r) => {
            const body = (r.body ?? {}) as { name?: string; tools?: string[] };
            return {
                status: 201,
                body: {
                    ...MCP_SERVERS[0],
                    id: did(290),
                    name: body.name,
                    tools: body.tools ?? [],
                    tool_count: toolCountOf(body.tools),
                    url: 'https://mcp.noclick.app/s/mcs_N3wS9rVq2Lk8Ty',
                    created_at: now(),
                    last_client_at: null,
                },
            };
        },
    },
    { method: 'GET', path: '/v1/mcp_servers/:id', reply: (r) => serverReply(r, (s) => s) },
    {
        method: 'PATCH',
        path: '/v1/mcp_servers/:id',
        reply: (r) => serverReply(r, (s) => {
            const body = (r.body ?? {}) as Json;
            return { ...s, ...body, ...(body.tools ? { tool_count: toolCountOf(body.tools) } : {}) };
        }),
    },
    { method: 'DELETE', path: '/v1/mcp_servers/:id', reply: (r) => serverReply(r, (s) => ({ object: 'mcp_server', id: s.id, deleted: true })) },
    { method: 'POST', path: '/v1/mcp_servers/:id/rotate', reply: (r) => serverReply(r, (s) => ({ ...s, url: 'https://mcp.noclick.app/s/mcs_R0tQ4cXn8Bv2Hd' })) },
    {
        method: 'GET',
        path: '/v1/mcp_servers/:id/clients',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : serverOf(r.params.id) ? list(r.set === 'populated' ? (MCP_CLIENTS[r.params.id] ?? []) : []) : apiError(404, 'not_found', `MCP server ${r.params.id} not found.`)),
    },
];
