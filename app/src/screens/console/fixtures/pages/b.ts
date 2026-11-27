// Fixtures for Operations, Logs and Agents: operations with their events and
// tool calls, the tool-call and API-request logs, agent conversations and the
// agent writes. Lists honour the filters the pages send, so a console filter
// and its fixture answer agree.
import {
    AGENTS,
    LAB_EXTRA_AGENTS,
    LAB_OPERATIONS,
    DAY,
    HOUR,
    KEYS,
    MIN,
    PAGE_ERROR,
    SHOT_TARGETS,
    USERS,
    FIXTURE_NOW_MS,
    apiError,
    fixtureId,
    list,
    ok,
    type FixtureReply,
    type FixtureRequest,
    type FixtureRoute,
} from '../core';
import { CONNECTIONS } from './a';
import { DIGEST } from './i_agents';
import { cancelPortRequest, findPortRequest, portRequests } from './m_numbers';
import { ORCHESTRATION_AGENT_IDS, ORCHESTRATION_CONVERSATIONS, ORCHESTRATION_OPERATIONS, ORCHESTRATION_TRANSCRIPTS } from './n_orchestration';

type Json = Record<string, unknown>;

const [SUPPORT, CONCIERGE] = AGENTS;
const [ACME, USER_42, GLOBEX] = USERS;
const [CONSOLE_KEY, BACKEND_KEY, ANALYTICS_KEY] = KEYS;

const LIVE = ['queued', 'running', 'awaiting_human'];
const TERMINAL = ['succeeded', 'failed', 'canceled', 'expired'];

const at = (ms: number) => new Date(FIXTURE_NOW_MS - ms).toISOString();
const plus = (iso: string, ms: number) => new Date(Date.parse(iso) + ms).toISOString();
const newestFirst = (rows: Json[]) => rows.sort((a, b) => Date.parse(String(b.created_at)) - Date.parse(String(a.created_at)));

function timings(events: { status: string; at: string }[]) {
    if (!events.length) return { wait_ms: null, run_ms: null, held_ms: null };
    let wait = 0;
    let run = 0;
    let held = 0;
    for (let i = 0; i < events.length - 1; i++) {
        const span = Date.parse(events[i + 1].at) - Date.parse(events[i].at);
        if (events[i].status === 'queued') wait += span;
        else if (events[i].status === 'running') run += span;
        else if (LIVE.includes(events[i].status)) held += span;
    }
    const last = events[events.length - 1];
    if (!TERMINAL.includes(last.status)) {
        const span = FIXTURE_NOW_MS - Date.parse(last.at);
        if (last.status === 'queued') wait += span;
        else if (last.status === 'running') run += span;
        else held += span;
    }
    return { wait_ms: wait, run_ms: run, held_ms: held };
}

interface OpSeed {
    n: number;
    kind: string;
    status: string;
    summary: string;
    agent?: { id: string } | null;
    user?: { id: string } | null;
    key?: { id: string };
    events: { status: string; at: string; by?: string }[];
    createdAt?: string;
    input: Json;
    result?: unknown;
    error?: Json | null;
}

/** NoClick's own failures: no agent's settings fix them (the API groups them by the kind of work). */
const NOCLICKS_OWN = new Set(['platform_error', 'upstream_error', 'request_timeout', 'rate_limited']);

/** What a failure's fix acts on, as the API works it out (`operations_store._FIXED_ON`). */
function fixedOn(seed: OpSeed): string {
    const e = seed.error ?? {};
    const of = (key: string) => (typeof e[key] === 'string' ? (e[key] as string) : typeof seed.input[key] === 'string' ? (seed.input[key] as string) : null);
    if (e.type === 'spend_cap_exceeded') return `cap/${e.scope ?? ''}/${e.scope_id ?? ''}`;
    if (e.type === 'spending_paused') return `user/${e.user_id ?? ''}`;
    if (typeof e.connection === 'string') return `connection/${e.connection}`;
    if (e.type === 'payment_required' || e.type === 'plan_required') return 'account';
    if (of('project_id')) return `app/${of('project_id')}`;
    if (of('workflow_id')) return `workflow/${of('workflow_id')}`;
    if (seed.agent && !NOCLICKS_OWN.has(String(e.type))) return `agent/${seed.agent.id}`;
    return `kind/${seed.kind}`;
}

/** The API's `failed_on` (`operations_store.failed_on`). */
function failedOn(fixed: string): Json | null {
    if (fixed.startsWith('kind/')) return null;
    const [head, ...rest] = fixed.split('/');
    if (head === 'cap') return { object: 'cap', scope: rest[0] || null, id: rest.slice(1).join('/') || null };
    return { object: head, id: rest.join('/') || null };
}

/** A failure's cause: one token for every failure of the same type and reason on the same thing. */
function causeOf(seed: OpSeed): string {
    const key = `${seed.error?.type ?? ''}|${seed.error?.reason ?? ''}|${fixedOn(seed)}`;
    const half = (seed0: number) => {
        let h = seed0;
        for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619) >>> 0;
        return h.toString(16).padStart(8, '0');
    };
    return half(2166136261) + half(2654435761);
}

function operation(seed: OpSeed): Json {
    const events = seed.events;
    const created = seed.createdAt ?? events[0].at;
    const last = events[events.length - 1];
    const started = events.find((e) => e.status === 'running')?.at ?? null;
    const failed = seed.status === 'failed';
    return {
        object: 'operation',
        id: fixtureId(4, seed.n),
        kind: seed.kind,
        status: seed.status,
        summary: seed.summary,
        user_id: seed.user?.id ?? null,
        key_id: (seed.key ?? BACKEND_KEY).id,
        agent_id: seed.agent?.id ?? null,
        input: seed.input,
        result: seed.result ?? null,
        error: seed.error ?? null,
        cause: failed ? causeOf(seed) : null,
        failed_on: failed ? failedOn(fixedOn(seed)) : null,
        created_at: created,
        updated_at: last ? last.at : created,
        started_at: started,
        finished_at: last && TERMINAL.includes(last.status) ? last.at : null,
        ...timings(events),
        events,
    };
}

// The timeline's operation: queued, ran, held on an approval for two minutes, ran again, succeeded.
const TIMELINE_START = at(12 * MIN);
const TIMELINE_EVENTS = [
    { status: 'queued', at: TIMELINE_START },
    { status: 'running', at: plus(TIMELINE_START, 120) },
    { status: 'awaiting_human', at: plus(TIMELINE_START, 1_620) },
    { status: 'running', at: plus(TIMELINE_START, 121_620) },
    { status: 'succeeded', at: plus(TIMELINE_START, 124_340) },
];
const PLAIN_START = at(40 * MIN);

/** What three of globex's turns stopped at: its $20 cap (`spend.check`'s refusal, scope `user`). */
const GLOBEX_CAP = {
    type: 'spend_cap_exceeded',
    message: "The user's spend cap of $20 this month is used up ($20.4100 spent).",
    next_step: "Raise the user's spend_cap_usd_per_month (PATCH /v1/users/globex), or wait until it resets on 2026-10-01.",
    scope: 'user',
    scope_id: GLOBEX.id,
    cap: 20,
    spent: 20.41,
    resets_at: '2026-10-01T00:00:00Z',
};

/** What the concierge's turns stopped at: the account's Claude key out of credits at Anthropic (connection 8). */
const CLAUDE_OUT_OF_CREDITS = {
    type: 'payment_required',
    reason: 'provider_out_of_funds',
    message: 'Your Claude account has no API credits.',
    next_step: "Add funds to the anthropic account behind the 'claude' connection, or connect another key.",
    connection: 'claude',
    connection_name: 'claude',
    integration: 'anthropic',
    provider: 'anthropic',
    billing_url: 'https://platform.claude.com/settings/billing',
};

export const OPERATIONS: Json[] = newestFirst([
    operation({
        n: 3,
        kind: 'agent.message',
        status: 'running',
        summary: 'Book a table for four at 8pm on Friday',
        agent: CONCIERGE,
        user: ACME,
        events: [
            { status: 'queued', at: at(21_000) },
            { status: 'running', at: at(20_400) },
        ],
        input: { agent_id: CONCIERGE.id, text: 'Book a table for four at 8pm on Friday', conversation: 'c-friday' },
    }),
    operation({
        n: SHOT_N(SHOT_TARGETS.operationWithTimeline),
        kind: 'agent.message',
        status: 'succeeded',
        summary: 'Send the weekly summary to the team',
        agent: SUPPORT,
        user: ACME,
        events: TIMELINE_EVENTS,
        input: { agent_id: SUPPORT.id, text: 'Send the weekly summary to the team', conversation: 'c-7' },
        result: {
            text: 'Sent the weekly summary to ops@acme.test after your approval.',
            conversation: 'c-7',
            tool_calls: [
                { tool: 'stripe__list_invoices', arguments: { limit: 10 }, result: null, is_error: false, created_at: null },
                { tool: 'gmail__send_email', arguments: { to: 'ops@acme.test', subject: 'Weekly summary' }, result: null, is_error: false, created_at: null },
            ],
            cost_usd: 0.0421,
        },
    }),
    operation({
        n: 4,
        kind: 'human.approve',
        status: 'awaiting_human',
        summary: 'ana@example.com',
        user: USER_42,
        events: [{ status: 'awaiting_human', at: at(2 * HOUR) }],
        input: {
            message: 'Send the weekly summary to your team?',
            options: [],
            details: { to: 'team@example.com', subject: 'Weekly summary' },
            expires_at: new Date(FIXTURE_NOW_MS + 22 * HOUR).toISOString(),
            to: { email: 'ana@example.com' },
        },
    }),
    operation({
        n: 5,
        kind: 'agent.message',
        status: 'failed',
        summary: 'Refund the duplicate charge on invoice 1042',
        agent: SUPPORT,
        user: GLOBEX,
        events: [
            { status: 'queued', at: at(3 * HOUR) },
            { status: 'failed', at: at(3 * HOUR - 80) },
        ],
        input: { agent_id: SUPPORT.id, text: 'Refund the duplicate charge on invoice 1042', conversation: 'c-refund' },
        error: GLOBEX_CAP,
    }),
    operation({
        n: 11,
        kind: 'agent.message',
        status: 'failed',
        summary: 'Refund order 88',
        agent: SUPPORT,
        user: GLOBEX,
        events: [
            { status: 'queued', at: at(2 * HOUR) },
            { status: 'failed', at: at(2 * HOUR - 60) },
        ],
        input: { agent_id: SUPPORT.id, text: 'Refund order 88', conversation: 'c-refund-88' },
        error: GLOBEX_CAP,
    }),
    operation({
        n: 12,
        kind: 'agent.message',
        status: 'failed',
        summary: 'Chase invoice 1051',
        agent: SUPPORT,
        user: GLOBEX,
        events: [
            { status: 'queued', at: at(2 * HOUR + 4 * MIN) },
            { status: 'failed', at: at(2 * HOUR + 4 * MIN - 70) },
        ],
        input: { agent_id: SUPPORT.id, text: 'Chase invoice 1051', conversation: 'c-chase-1051' },
        error: GLOBEX_CAP,
    }),
    operation({
        n: 13,
        kind: 'agent.message',
        status: 'failed',
        summary: 'Find a table for six on Saturday',
        agent: CONCIERGE,
        user: ACME,
        events: [
            { status: 'queued', at: at(5 * HOUR) },
            { status: 'running', at: at(5 * HOUR - 200) },
            { status: 'failed', at: at(5 * HOUR - 2_100) },
        ],
        input: { agent_id: CONCIERGE.id, text: 'Find a table for six on Saturday', conversation: 'c-saturday' },
        error: CLAUDE_OUT_OF_CREDITS,
    }),
    operation({
        n: 14,
        kind: 'agent.message',
        status: 'failed',
        summary: 'Move the 7pm booking to 8pm',
        agent: CONCIERGE,
        user: ACME,
        events: [
            { status: 'queued', at: at(6 * HOUR) },
            { status: 'running', at: at(6 * HOUR - 180) },
            { status: 'failed', at: at(6 * HOUR - 1_900) },
        ],
        input: { agent_id: CONCIERGE.id, text: 'Move the 7pm booking to 8pm', conversation: 'c-move-7pm' },
        error: CLAUDE_OUT_OF_CREDITS,
    }),
    operation({
        n: 15,
        kind: 'agent.message',
        status: 'failed',
        summary: 'Email the refund receipt to it@globex.test',
        agent: SUPPORT,
        user: GLOBEX,
        events: [
            { status: 'queued', at: at(7 * HOUR) },
            { status: 'running', at: at(7 * HOUR - 150) },
            { status: 'failed', at: at(7 * HOUR - 3_400) },
        ],
        input: { agent_id: SUPPORT.id, text: 'Email the refund receipt to it@globex.test', conversation: 'c-receipt' },
        error: {
            type: 'credential_disconnected',
            message: "The 'gmail' connection (Gmail) is disconnected.",
            next_step: 'Reconnect it in the NoClick app (Connections) or with a connect link (POST .../connect_links), which keeps the same account, or remove it in the app.',
            connection: 'gmail',
            integration: 'gmail',
            credential_type: 'gmail_oauth',
        },
    }),
    operation({
        n: SHOT_N(SHOT_TARGETS.operationPlain),
        kind: 'sandbox.exec',
        status: 'succeeded',
        summary: 'python train.py --epochs 3',
        events: [
            { status: 'running', at: PLAIN_START },
            { status: 'succeeded', at: plus(PLAIN_START, 2_720) },
        ],
        input: { sandbox_id: fixtureId(7, 90), command: 'python train.py --epochs 3', timeout_s: 600 },
        result: { exit_code: 0, stdout: 'epoch 3/3 loss=0.041\n', stderr: '' },
    }),
    operation({
        n: 6,
        kind: 'credential.connect',
        status: 'succeeded',
        summary: 'Connect gmail',
        user: USER_42,
        events: [
            { status: 'awaiting_human', at: at(5 * HOUR) },
            { status: 'succeeded', at: at(5 * HOUR - 4 * MIN) },
        ],
        input: { connect_link_id: fixtureId(7, 91), connection: 'gmail', connection_id: fixtureId(7, 92), integration: 'gmail', credential_type: 'GmailOAuth', redirect_url: null },
        result: {
            connection: {
                object: 'connection',
                id: fixtureId(7, 92),
                name: 'gmail',
                integration: 'gmail',
                credential_type: 'GmailOAuth',
                user_id: USER_42.id,
                status: 'connected',
                account: 'ana@example.com',
                verification: { reachable: true, samples: [{ label: 'ana@example.com', value: null }], message: 'Signed in as ana@example.com.' },
                connect_link: null,
                connected_at: at(5 * HOUR - 4 * MIN),
                created_at: at(5 * HOUR),
                updated_at: at(5 * HOUR - 4 * MIN),
            },
        },
    }),
    operation({
        n: 7,
        kind: 'human.ask',
        status: 'expired',
        summary: 'it@globex.test',
        user: GLOBEX,
        events: [
            { status: 'awaiting_human', at: at(2 * DAY) },
            { status: 'expired', at: at(DAY) },
        ],
        input: { message: 'Which workspace should we use?', options: ['Sales', 'Support'], details: {}, to: { email: 'it@globex.test' } },
        error: { type: 'expired', message: 'Nobody answered before the request expired.', next_step: 'Send a new request.' },
    }),
    operation({
        n: 8,
        kind: 'sandbox.exec',
        status: 'failed',
        summary: 'npm run build',
        key: ANALYTICS_KEY,
        events: [
            { status: 'queued', at: at(20 * HOUR) },
            { status: 'running', at: at(20 * HOUR - 300) },
            { status: 'failed', at: at(20 * HOUR - 64_000) },
        ],
        input: { sandbox_id: fixtureId(7, 90), command: 'npm run build', timeout_s: 600 },
        error: { type: 'platform_error', reason: 'interrupted', message: 'NoClick restarted while this was running, so it stopped before it finished.', next_step: 'Start it again if it still needs doing; it may have partly run.' },
    }),
    operation({
        n: 9,
        kind: 'phone.call',
        status: 'canceled',
        summary: 'Call +14155550188',
        agent: SUPPORT,
        key: CONSOLE_KEY,
        events: [
            { status: 'running', at: at(3 * DAY) },
            { status: 'canceled', at: at(3 * DAY - 45_000), by: 'owner' },
        ],
        input: { phone_number_id: fixtureId(7, 93), to: '+14155550188', agent_id: SUPPORT.id },
        error: { type: 'canceled', message: 'The operation was canceled.' },
    }),
    operation({
        n: 10,
        kind: 'human.notify',
        status: 'succeeded',
        summary: 'ops@acme.test',
        user: ACME,
        events: [],
        createdAt: at(9 * DAY),
        input: { message: 'Your export is ready.', options: [], details: {}, to: { email: 'ops@acme.test' } },
        result: { request_id: fixtureId(5, 20), delivered_via: ['email'], undelivered: [] },
    }),
]);

function SHOT_N(id: string): number {
    return Number(id.slice(-12));
}

/** The reply a Try it turn gets (the POST answers with a running operation, the read with this). */
export const TRY_IT_OPERATION_ID = fixtureId(4, 90);
export const TRY_IT_REPLY = 'Your last invoice was $49.00, paid on Sep 1.';

function tryItOperation(): Json {
    const start = at(3_000);
    return operation({
        n: 90,
        kind: 'agent.message',
        status: 'succeeded',
        summary: 'Try it',
        agent: SUPPORT,
        key: CONSOLE_KEY,
        events: [
            { status: 'queued', at: start },
            { status: 'running', at: plus(start, 90) },
            { status: 'succeeded', at: plus(start, 2_400) },
        ],
        input: { agent_id: SUPPORT.id, text: 'hi', conversation: 'c-try' },
        result: {
            text: TRY_IT_REPLY,
            conversation: 'c-try',
            // A reply names tools as stored: the wire form, `integration__operation`.
            tool_calls: [{ tool: 'stripe__list_invoices', arguments: { limit: 1 }, result: null, is_error: false, created_at: null }],
            cost_usd: 0.0031,
        },
    });
}

/** A Try it turn with an agent on a CLI harness: queued, then its sandbox starting, then working, then the reply. */
export const CLI_TRY_OPERATION_ID = fixtureId(4, 91);
export const CLI_TRY_REPLY = 'I fixed 3 broken links in README.md and opened pull request #42.';
const CODER = AGENTS.find((a) => a.name === 'coder')!;
/** Reads of the CLI turn since it was sent: each one moves it a step on. */
let cliTryReads = 0;

function cliTryOperation(): Json {
    const start = at(20_000);
    const phases = [
        { status: 'queued', step: null, at: start },
        { status: 'running', step: 'delivering', at: plus(start, 150) },
        { status: 'running', step: 'working', at: plus(start, 18_400) },
        { status: 'succeeded', step: null, at: plus(start, 19_800) },
    ];
    const reached = phases.slice(0, Math.min(cliTryReads, phases.length - 1) + 1);
    const now = reached[reached.length - 1];
    const done = now.status === 'succeeded';
    return {
        ...operation({
            n: 91,
            kind: 'agent.message',
            status: now.status,
            summary: 'Try it',
            agent: CODER,
            key: CONSOLE_KEY,
            // A step isn't a status: the events record queued, running and the end.
            events: reached.filter((e, i) => i === 0 || e.status !== reached[i - 1].status).map(({ status, at: when }) => ({ status, at: when })),
            input: { agent_id: CODER.id, text: 'Fix the broken links in README.md', conversation: 'docs-1' },
            result: done
                ? {
                      text: CLI_TRY_REPLY,
                      conversation: 'docs-1',
                      // The harness's own steps ride beside the tool calls NoClick ran for it.
                      tool_calls: [
                          { tool: 'Bash', arguments: { command: 'grep -rn "](http" README.md' }, result: null, is_error: false, created_at: null, source: 'harness' },
                          { tool: 'Edit', arguments: { file_path: 'README.md' }, result: null, is_error: false, created_at: null, source: 'harness' },
                          { tool: 'search', arguments: { query: 'noclick docs agents page' }, result: null, is_error: false, created_at: null },
                      ],
                      cost_usd: 0.0183,
                      // Designed: its model calls on the claude connection, at the provider's list price.
                      model_usage: { input_tokens: 48_200, output_tokens: 2_130, cached_tokens: 39_000, usd: 0.0871 },
                  }
                : null,
        }),
        step: now.step,
    };
}

// ── tool calls ─────────────────────────────────────────────────────────────

interface CallSeed {
    n: number;
    tool: string;
    status: 'success' | 'error';
    at: string;
    ms: number;
    agent?: { id: string } | null;
    user?: { id: string } | null;
    conversation?: string | null;
    args: Json;
    result?: string | null;
    error?: string | null;
}

function toolCall(seed: CallSeed): Json {
    const [integration, op] = seed.tool.includes('.') ? seed.tool.split('.') : [seed.tool, null];
    return {
        object: 'tool_call',
        id: fixtureId(6, seed.n),
        tool_name: seed.tool,
        tool_type: seed.tool.includes('.') ? 'node_op' : 'capability',
        operation: op ?? integration,
        status: seed.status,
        error: seed.error ?? null,
        arguments: seed.args,
        result_preview: seed.result ?? null,
        duration_ms: seed.ms,
        credential_id: seed.tool.startsWith('gmail') ? fixtureId(7, 92) : null,
        connection: seed.tool.startsWith('gmail') ? 'gmail' : null,
        user_id: seed.user?.id ?? null,
        agent_id: seed.agent?.id ?? null,
        conversation: seed.conversation ?? null,
        execution_id: seed.agent ? fixtureId(8, 50 + seed.n) : null,
        source: seed.agent ? 'agent' : 'api',
        created_at: seed.at,
    };
}

export const TOOL_CALLS: Json[] = newestFirst([
    toolCall({
        n: 1,
        tool: 'gmail.send_email',
        status: 'success',
        at: plus(TIMELINE_START, 122_100),
        ms: 1_480,
        agent: SUPPORT,
        user: ACME,
        conversation: 'c-7',
        args: { to: 'ops@acme.test', subject: 'Weekly summary', body: 'Revenue is up 4% week over week.' },
        result: '{"id": "18c2f0a9", "threadId": "18c2f0a9"}',
    }),
    toolCall({
        n: 2,
        tool: 'stripe.list_invoices',
        status: 'success',
        at: plus(TIMELINE_START, 400),
        ms: 610,
        agent: SUPPORT,
        user: ACME,
        conversation: 'c-7',
        args: { limit: 10 },
        result: '[{"id": "in_1042", "amount_due": 4900}, …]',
    }),
    toolCall({ n: 3, tool: 'search', status: 'success', at: at(6 * MIN), ms: 812, user: USER_42, args: { query: 'noclick pricing' }, result: '[{"title": "Pricing — NoClick"}]' }),
    toolCall({
        n: 4,
        tool: 'stripe.create_refund',
        status: 'error',
        at: at(3 * HOUR - 40),
        ms: 240,
        agent: SUPPORT,
        user: GLOBEX,
        conversation: 'c-refund',
        args: { charge: 'ch_3Pq', amount: 4900 },
        error: 'Spend cap reached for user globex.',
    }),
    toolCall({ n: 5, tool: 'slack.send_message_to_channel', status: 'success', at: at(4 * HOUR), ms: 390, args: { channel: '#launch', text: 'Deploy finished.' }, result: '{"ok": true}' }),
    toolCall({ n: 6, tool: 'gmail.list_messages', status: 'error', at: at(7 * HOUR), ms: 1_020, user: USER_42, args: { q: 'is:unread' }, error: 'The Gmail credential was revoked by the user.' }),
    toolCall({ n: 7, tool: 'fetch', status: 'success', at: at(30 * HOUR), ms: 2_310, agent: CONCIERGE, user: ACME, conversation: 'c-friday', args: { url: 'https://example.com/menu' }, result: 'Dinner menu…' }),
]);

const OPERATION_TOOL_CALLS: Record<string, string[]> = {
    [SHOT_TARGETS.operationWithTimeline]: [fixtureId(6, 2), fixtureId(6, 1)],
    [fixtureId(4, 5)]: [fixtureId(6, 4)],
};

// ── API requests ───────────────────────────────────────────────────────────

interface RequestSeed {
    n: number;
    actor: 'key' | 'session' | 'owner';
    key?: { id: string } | null;
    user?: { id: string } | null;
    method: string;
    route: string;
    params?: Json;
    status: number;
    error?: string | null;
    ms: number;
    replayed?: boolean;
    operation?: string | null;
    at: string;
}

function apiRequest(seed: RequestSeed): Json {
    return {
        object: 'api_request',
        id: fixtureId(7, seed.n),
        actor: seed.actor,
        key_id: seed.key?.id ?? null,
        user_id: seed.user?.id ?? null,
        session_id: seed.actor === 'session' ? fixtureId(7, 80) : null,
        method: seed.method,
        route: seed.route,
        path_params: seed.params ?? {},
        status: seed.status,
        error_type: seed.error ?? null,
        duration_ms: seed.ms,
        idempotency_replayed: seed.replayed ?? false,
        operation_id: seed.operation ?? null,
        request_id: `req_${String(seed.n).padStart(6, '0')}`,
        created_at: seed.at,
    };
}

export const API_REQUESTS: Json[] = newestFirst([
    apiRequest({
        n: 1,
        actor: 'key',
        key: BACKEND_KEY,
        user: ACME,
        method: 'POST',
        route: '/v1/agents/{agent_id}/messages',
        params: { agent_id: SUPPORT.id },
        status: 202,
        ms: 84,
        operation: SHOT_TARGETS.operationWithTimeline,
        at: TIMELINE_START,
    }),
    apiRequest({
        n: 2,
        actor: 'key',
        key: BACKEND_KEY,
        user: ACME,
        method: 'POST',
        route: '/v1/agents/{agent_id}/messages',
        params: { agent_id: SUPPORT.id },
        status: 202,
        ms: 6,
        replayed: true,
        operation: SHOT_TARGETS.operationWithTimeline,
        at: plus(TIMELINE_START, 900),
    }),
    apiRequest({ n: 3, actor: 'owner', key: CONSOLE_KEY, method: 'PUT', route: '/v1/policy', status: 200, ms: 41, at: at(50 * MIN) }),
    apiRequest({
        n: 4,
        actor: 'key',
        key: BACKEND_KEY,
        user: GLOBEX,
        method: 'POST',
        route: '/v1/connections/{ref}/operations/{operation}/run',
        params: { ref: 'stripe', operation: 'create_refund' },
        status: 402,
        error: 'spend_cap_exceeded',
        ms: 22,
        at: at(3 * HOUR - 30),
    }),
    apiRequest({ n: 5, actor: 'session', key: BACKEND_KEY, user: USER_42, method: 'POST', route: '/v1/humans/requests', status: 403, error: 'policy_denied', ms: 18, at: at(8 * HOUR) }),
    apiRequest({ n: 6, actor: 'owner', key: CONSOLE_KEY, method: 'DELETE', route: '/v1/keys/{key_id}', params: { key_id: CONSOLE_KEY.id }, status: 409, error: 'conflict', ms: 12, at: at(2 * DAY) }),
    apiRequest({ n: 7, actor: 'owner', key: CONSOLE_KEY, method: 'POST', route: '/v1/keys', status: 201, ms: 57, at: at(12 * DAY) }),
    apiRequest({ n: 8, actor: 'key', key: ANALYTICS_KEY, method: 'GET', route: '/v1/usage/series', status: 500, error: 'server_error', ms: 3_012, at: at(13 * DAY) }),
]);

// ── agents ─────────────────────────────────────────────────────────────────

export const CONVERSATIONS: Json[] = [
    { object: 'agent_conversation', conversation: 'c-7', agent_id: SUPPORT.id, user_id: ACME.id, title: 'Weekly summary', preview: 'Sent the weekly summary to ops@acme.test after your approval.', turns: 6, cost_usd: 0.1284, last_activity: plus(TIMELINE_START, 124_340) },
    { object: 'agent_conversation', conversation: 'c-refund', agent_id: SUPPORT.id, user_id: GLOBEX.id, title: 'Duplicate charge', preview: 'Refund the duplicate charge on invoice 1042', turns: 1, cost_usd: 0.0019, last_activity: at(3 * HOUR) },
    { object: 'agent_conversation', conversation: 'c-hello', agent_id: SUPPORT.id, user_id: null, title: null, preview: 'hi', turns: 2, cost_usd: null, last_activity: at(4 * DAY) },
    // Designed: a conversation handed to a person, one waiting on its question, and a coding agent's model calls on its own key.
    {
        object: 'agent_conversation', conversation: 'overnight-0924', agent_id: DIGEST.id, user_id: null, title: 'Refund spike overnight',
        preview: "I've handed this to ops: three refunds over $500 need a person.", turns: 3, cost_usd: 0.0214, last_activity: at(2 * DAY + 7 * HOUR),
        status: 'handed_off', handed_off_to: 'ops@yourco.test', model_usage: null,
    },
    {
        object: 'agent_conversation', conversation: 'overnight-0926', agent_id: DIGEST.id, user_id: null, title: 'Overnight summary',
        preview: 'Should the summary include the test tickets from staging?', turns: 1, cost_usd: 0.0088, last_activity: at(9 * HOUR),
        status: 'awaiting_human', handed_off_to: null, model_usage: null,
    },
    {
        object: 'agent_conversation', conversation: 'docs-links', agent_id: CODER.id, user_id: null, title: 'Broken links in the guides',
        preview: 'Opened a pull request fixing 7 links.', turns: 4, cost_usd: 0.0412, last_activity: at(6 * HOUR), status: 'active',
        handed_off_to: null, model_usage: { input_tokens: 184_200, output_tokens: 9_410, cached_tokens: 151_000, usd: 0.3342 },
    },
];

const TRANSCRIPTS: Record<string, { role: string; text: string; created_at: string }[]> = {
    'c-7': [
        { role: 'user', text: 'Send the weekly summary to the team', created_at: TIMELINE_START },
        { role: 'assistant', text: 'Sent the weekly summary to ops@acme.test after your approval.', created_at: plus(TIMELINE_START, 124_340) },
    ],
    'c-refund': [{ role: 'user', text: 'Refund the duplicate charge on invoice 1042', created_at: at(3 * HOUR) }],
    'c-hello': [
        { role: 'user', text: 'hi', created_at: at(4 * DAY) },
        { role: 'assistant', text: 'Hi! I answer billing questions. What can I look up for you?', created_at: at(4 * DAY - 2_000) },
    ],
    'overnight-0924': [
        { role: 'user', text: 'Email the overnight summary to ops@yourco.test', created_at: at(2 * DAY + 9 * HOUR) },
        { role: 'assistant', text: "I've handed this to ops: three refunds over $500 need a person.", created_at: at(2 * DAY + 8 * HOUR) },
        { role: 'person', text: 'Thanks, I have the refunds. Carry on with tomorrow’s summary as usual.', created_at: at(2 * DAY + 7 * HOUR) },
    ],
    'overnight-0926': [
        { role: 'user', text: 'Email the overnight summary to ops@yourco.test', created_at: at(9 * HOUR + 60_000) },
        { role: 'assistant', text: 'Should the summary include the test tickets from staging?', created_at: at(9 * HOUR) },
    ],
    'docs-links': [
        { role: 'user', text: 'Fix the broken links in the guides', created_at: at(6 * HOUR + 300_000) },
        { role: 'assistant', text: 'Opened a pull request fixing 7 links.', created_at: at(6 * HOUR) },
    ],
};

const app = (name: string, label: string, connectWith: string[], credentialTypes: string[], operations: number, accountFree = 0) => ({
    object: 'integration', name, label, kind: 'app', subscription: false, connect_with: connectWith, credential_types: credentialTypes,
    operation_count: operations, account_free_operation_count: accountFree,
});

/** A model provider: an agent's `model_connection`, never a tool. `subscription`: its link also offers the provider's plan. */
const model = (name: string, label: string, credentialTypes: string[], subscription = false) => ({
    object: 'integration', name, label, kind: 'model', subscription, connect_with: ['key'], credential_types: credentialTypes,
    operation_count: 0, account_free_operation_count: 0,
});

/**
 * The catalog, with how a person connects each (`connect_with`: signing in, or pasting a key) and
 * how many operations run with no account, by the integration's name (Exa's four reads), then the
 * model providers agents think with.
 */
export const INTEGRATIONS = [
    app('exa', 'Exa', ['key'], ['exa_api_key'], 6, 4),
    app('gmail', 'Gmail', ['oauth'], ['gmail_oauth'], 3),
    app('slack', 'Slack', ['oauth'], ['slack_oauth'], 2),
    app('stripe', 'Stripe', ['key'], ['stripe_api_key'], 3),
    model('anthropic', 'Anthropic', ['agent_anthropic', 'agent_claude_code_oauth'], true),
    model('openai', 'OpenAI', ['agent_openai', 'agent_codex_oauth'], true),
    model('openrouter', 'OpenRouter', ['agent_openrouter']),
    model('opencode', 'OpenCode Zen', ['agent_opencode']),
];

/** Every model provider, in the backend's order: sdk and the provider/model harnesses run any of them. */
const MODEL_PROVIDERS = [
    'openrouter', 'anthropic', 'openai', 'opencode', 'gemini', 'google', 'cohere', 'mistral',
    'groq', 'together_ai', 'fireworks_ai', 'deepseek', 'cerebras', 'xai', 'replicate', 'deepinfra',
    'huggingface', 'ai21', 'nlp_cloud', 'aleph_alpha', 'nvidia_nim', 'sambanova', 'moonshot', 'dashscope', 'azure',
    'bedrock', 'sagemaker', 'vertex_ai', 'azure_ai', 'predibase', 'volcengine', 'github-models', 'nvidia',
];
const CLI_NOTES = [
    'Replies arrive whole when the turn ends, not token by token.',
    'Runs in its own sandbox with a built-in shell, file edits and web access; a conversation idle for a minute starts cold on its next message (15-40 s), and sandbox time is billed.',
];
const PLAN_FIT = "A Claude or ChatGPT plan suits agents that work for the person whose plan it is, one answering their own business's messages included. Prefer an API key for an agent serving a product's many users, one working for someone other than the plan's holder, or a use the provider's terms for that plan wouldn't cover.";
const CHATGPT_PLAN_NOTES = ['A ChatGPT plan runs the openai/* models ChatGPT lists for its sign-in.', PLAN_FIT];
const harness = (name: string, label: string, version: string | null, defaultModel: string, fields: Json = {}) => ({
    object: 'harness', name, label, version, default_model: defaultModel, custom_models: true, model_connection: 'required',
    integrations: MODEL_PROVIDERS, streaming: 'final', shell: 'built_in', notes: CLI_NOTES, ...fields,
});

/** `GET /v1/harnesses`, as the backend answers it: NoClick's own loop, then the coding agents with their pinned versions. */
export const HARNESSES = [
    harness('sdk', 'NoClick', null, 'openrouter/~openai/gpt-luna-latest', {
        model_connection: 'optional', streaming: 'tokens', shell: 'code_capability', notes: ['Streams its reply; code, search and fetch are tools you list.'],
    }),
    harness('codex', 'Codex', '0.156.1', 'gpt-5.6-luna', {
        integrations: ['openai'],
        notes: [...CLI_NOTES, 'On a ChatGPT API key, codex shows tools only to codex-family models such as gpt-5-codex.', 'A ChatGPT plan runs the models ChatGPT lists for its sign-in.', PLAN_FIT],
    }),
    harness('claude_code', 'Claude Code', '2.1.281', 'sonnet', { integrations: ['anthropic'], notes: [...CLI_NOTES, 'A Claude plan (Sign in with Claude) runs it.', PLAN_FIT] }),
    harness('opencode', 'OpenCode', '1.18.32', 'opencode/big-pickle', { notes: [...CLI_NOTES, ...CHATGPT_PLAN_NOTES] }),
    harness('openclaw', 'OpenClaw', '2026.9.1', 'openrouter/~openai/gpt-luna-latest', { notes: [...CLI_NOTES, ...CHATGPT_PLAN_NOTES] }),
    harness('hermes', 'Hermes Agent', 'v2026.9.24', 'openrouter/~openai/gpt-luna-latest', { notes: [...CLI_NOTES, ...CHATGPT_PLAN_NOTES] }),
];

/** An OpenRouter-listed harness's models, as openclaw and hermes list them. */
const OPENROUTER_MODELS: [string, string][] = [
    ['openrouter/~openai/gpt-luna-latest', '[OpenRouter] OpenAI: GPT Luna Latest - 1M ctx'],
    ['openrouter/openai/gpt-6.1-sol-pro', '[OpenRouter] OpenAI: GPT-6.1 Sol Pro - 1M ctx'],
    ['openrouter/openai/gpt-6.1-sol-pro:batch', '[OpenRouter] OpenAI: GPT-6.1 Sol Pro (batch) - 1M ctx'],
    ['openrouter/openai/gpt-6.1-sol', '[OpenRouter] OpenAI: GPT-6.1 Sol - 1M ctx'],
    ['openrouter/openai/gpt-6.1-sol:batch', '[OpenRouter] OpenAI: GPT-6.1 Sol (batch) - 1M ctx'],
    ['openrouter/anthropic/claude-sonnet-5.5', '[OpenRouter] Anthropic: Claude Sonnet 5.5 - 1M ctx'],
    ['openrouter/anthropic/claude-sonnet-5.5:batch', '[OpenRouter] Anthropic: Claude Sonnet 5.5 (batch) - 1M ctx'],
    ['openrouter/perceptron/perceptron-mk1.5', '[OpenRouter] Perceptron: Perceptron Mk1.5'],
    ['openrouter/fireworks/ember-1', '[OpenRouter] Fireworks: Ember-1 - 1M ctx'],
    ['openrouter/z-ai/glm-5.3-prime', '[OpenRouter] Z.ai: GLM 5.3 Prime - 1M ctx'],
    ['openrouter/qwen/qwen3.8-max-prime', '[OpenRouter] Qwen: Qwen3.8 Max Prime - 1M ctx'],
    ['openrouter/stealth/space-bunny-alpha', '[OpenRouter] Space Bunny Alpha - 1M ctx'],
    ['openrouter/aion-labs/aion-3.5-mini', '[OpenRouter] AionLabs: Aion 3.5 Mini - 262K ctx'],
    ['openrouter/aion-labs/aion-3.5', '[OpenRouter] AionLabs: Aion 3.5 - 262K ctx'],
    ['openrouter/upstage/solar-mini4', '[OpenRouter] Upstage: Solar Mini 4 - 524K ctx'],
    ['openrouter/cohere/command-a-plus', '[OpenRouter] Cohere: Command A+ - 192K ctx'],
    ['openrouter/openai/gpt-6-luna-pro', '[OpenRouter] OpenAI: GPT-6 Luna Pro - 1M ctx'],
    ['openrouter/openai/gpt-6-luna-pro:batch', '[OpenRouter] OpenAI: GPT-6 Luna Pro (batch) - 1M ctx'],
    ['openrouter/openai/gpt-6-luna', '[OpenRouter] OpenAI: GPT-6 Luna - 1M ctx'],
    ['openrouter/openai/gpt-6-luna:batch', '[OpenRouter] OpenAI: GPT-6 Luna (batch) - 1M ctx'],
    ['openrouter/anthropic/claude-fable-5.1', '[OpenRouter] Anthropic: Claude Fable 5.1 - 1M ctx'],
    ['openrouter/anthropic/claude-fable-5.1:batch', '[OpenRouter] Anthropic: Claude Fable 5.1 (batch) - 1M ctx'],
    ['openrouter/anthropic/claude-opus-5', '[OpenRouter] Anthropic: Claude Opus 5 - 1M ctx'],
];

/** `GET /v1/harnesses/{name}/models`: a slice of each real list, in its order (the default first). */
const HARNESS_MODELS: Record<string, [string, string][]> = {
    sdk: [
        ['openrouter/~openai/gpt-luna-latest', '[openrouter] OpenAI: GPT Luna Latest'],
        ['openrouter/openai/gpt-6.1-sol-pro', '[openrouter] OpenAI: GPT-6.1 Sol Pro'],
        ['openrouter/openai/gpt-6.1-sol-pro:batch', '[openrouter] OpenAI: GPT-6.1 Sol Pro (batch)'],
        ['openrouter/openai/gpt-6.1-sol', '[openrouter] OpenAI: GPT-6.1 Sol'],
        ['openrouter/openai/gpt-6.1-sol:batch', '[openrouter] OpenAI: GPT-6.1 Sol (batch)'],
        ['openrouter/anthropic/claude-sonnet-5.5', '[openrouter] Anthropic: Claude Sonnet 5.5'],
        ['openrouter/anthropic/claude-sonnet-5.5:batch', '[openrouter] Anthropic: Claude Sonnet 5.5 (batch)'],
        ['openrouter/typesafe/jev-router', '[openrouter] TypeSafe: Jev Router'],
        ['openrouter/perceptron/perceptron-mk1.5', '[openrouter] Perceptron: Perceptron Mk1.5'],
        ['openrouter/fireworks/ember-1', '[openrouter] Fireworks: Ember-1'],
        ['openrouter/z-ai/glm-5.3-prime', '[openrouter] Z.ai: GLM 5.3 Prime'],
        ['openrouter/qwen/qwen3.8-max-prime', '[openrouter] Qwen: Qwen3.8 Max Prime'],
        ['openrouter/stealth/space-bunny-alpha', '[openrouter] Space Bunny Alpha · Free'],
        ['openrouter/aion-labs/aion-3.5-mini', '[openrouter] AionLabs: Aion 3.5 Mini'],
        ['openrouter/aion-labs/aion-3.5', '[openrouter] AionLabs: Aion 3.5'],
        ['openrouter/upstage/solar-mini4', '[openrouter] Upstage: Solar Mini 4'],
        ['openrouter/cohere/command-a-plus', '[openrouter] Cohere: Command A+'],
        ['openrouter/openai/gpt-6-luna-pro', '[openrouter] OpenAI: GPT-6 Luna Pro'],
        ['openrouter/openai/gpt-6-luna-pro:batch', '[openrouter] OpenAI: GPT-6 Luna Pro (batch)'],
        ['openrouter/openai/gpt-6-luna', '[openrouter] OpenAI: GPT-6 Luna'],
        ['openrouter/openai/gpt-6-luna:batch', '[openrouter] OpenAI: GPT-6 Luna (batch)'],
        ['openrouter/openai/gpt-6-sol-pro', '[openrouter] OpenAI: GPT-6 Sol Pro'],
        ['openrouter/openai/gpt-6-sol-pro:batch', '[openrouter] OpenAI: GPT-6 Sol Pro (batch)'],
        ['openrouter/openai/gpt-6-sol', '[openrouter] OpenAI: GPT-6 Sol'],
        ['openrouter/openai/gpt-6-sol:batch', '[openrouter] OpenAI: GPT-6 Sol (batch)'],
        ['openrouter/anthropic/claude-opus-5.5', '[openrouter] Anthropic: Claude Opus 5.5'],
        ['openrouter/anthropic/claude-opus-5.5:batch', '[openrouter] Anthropic: Claude Opus 5.5 (batch)'],
        ['openrouter/xiaomi/mimo-v2.6-pro-ultraspeed', '[openrouter] Xiaomi: MiMo-V2.6-Pro-UltraSpeed'],
        ['openrouter/xiaomi/mimo-v2.6-flash', '[openrouter] Xiaomi: MiMo-V2.6-Flash'],
        ['openrouter/xiaomi/mimo-v2.6-pro', '[openrouter] Xiaomi: MiMo-V2.6-Pro'],
        ['openrouter/x-ai/grok-4.7', '[openrouter] SpaceXAI: Grok 4.7'],
        ['openrouter/qwen/qwen3.8-omni-flash', '[openrouter] Qwen: Qwen3.8 Omni Flash'],
        ['openrouter/prism-ml/ternary-bonsai-2-27b', '[openrouter] PrismML: Ternary Bonsai 2 27B'],
        ['openrouter/z-ai/glm-5.3-flashx', '[openrouter] Z.ai: GLM 5.3 FlashX'],
        ['openrouter/unbiased/pareto', '[openrouter] Pareto'],
        ['openrouter/~deepseek/deepseek-pro-latest', '[openrouter] DeepSeek: DeepSeek Pro Latest'],
        ['openrouter/~deepseek/deepseek-flash-latest', '[openrouter] DeepSeek: DeepSeek Flash Latest'],
        ['openrouter/inference-net/schematron-v2-turbo', '[openrouter] Inference.net: Schematron V2 Turbo'],
        ['openrouter/inference-net/schematron-v2-small', '[openrouter] Inference.net: Schematron V2 Small'],
        ['openrouter/~openai/gpt-astra-latest', '[openrouter] OpenAI: GPT Astra Latest'],
        ['openrouter/~openai/gpt-sol-latest', '[openrouter] OpenAI: GPT Sol Latest'],
        ['openrouter/~openai/gpt-terra-latest', '[openrouter] OpenAI: GPT Terra Latest'],
        ['openrouter/sakana/fugu-ultra-v2', '[openrouter] Sakana: Fugu Ultra v2'],
        ['openrouter/sakana/fugu-max', '[openrouter] Sakana: Fugu Max'],
        ['openrouter/inclusionai/ling-3.0-flash-vl', '[openrouter] inclusionAI: Ling 3.0 Flash VL'],
        ['openrouter/deepseek/deepseek-v4.1-flash', '[openrouter] DeepSeek: DeepSeek V4.1 Flash'],
        ['openrouter/deepseek/deepseek-v4.1-flash:batch', '[openrouter] DeepSeek: DeepSeek V4.1 Flash (batch)'],
        ['openrouter/inception/mercury-2.5', '[openrouter] Inception: Mercury 2.5'],
        ['openrouter/nex-agi/nex-n2.5-mini', '[openrouter] Nex AGI: Nex-N2.5-Mini'],
        ['openrouter/nex-agi/nex-n2.5-pro', '[openrouter] Nex AGI: Nex-N2.5-Pro'],
        ['openrouter/openai/gpt-6-astra', '[openrouter] OpenAI: GPT-6 Astra'],
        ['openrouter/openai/gpt-6-astra:batch', '[openrouter] OpenAI: GPT-6 Astra (batch)'],
        ['openrouter/openai/gpt-6-astra-pro', '[openrouter] OpenAI: GPT-6 Astra Pro'],
        ['openrouter/openai/gpt-6-astra-pro:batch', '[openrouter] OpenAI: GPT-6 Astra Pro (batch)'],
        ['openrouter/inclusionai/ling-3.0-flash-sante:free', '[openrouter] inclusionAI: Ling 3.0 Flash Sante (free) · Free'],
        ['openrouter/qwen/qwen3.8-max-0902', '[openrouter] Qwen: Qwen3.8 Max (0902)'],
        ['openrouter/meta/muse-spark-1.3-contributor', '[openrouter] Meta: Muse Spark 1.3 Contributor'],
        ['openrouter/meta/muse-spark-1.3', '[openrouter] Meta: Muse Spark 1.3'],
        ['openrouter/google/gemini-3.8-flash', '[openrouter] Google: Gemini 3.8 Flash'],
        ['openrouter/google/gemini-3.8-flash:batch', '[openrouter] Google: Gemini 3.8 Flash (batch)'],
    ],
    codex: [
        ['gpt-5.6-luna', 'gpt-5.6-luna'],
        ['gpt-6-astra', 'gpt-6-astra'],
        ['gpt-6-sol', 'gpt-6-sol'],
        ['gpt-6-luna', 'gpt-6-luna'],
        ['gpt-5.6-sol', 'gpt-5.6-sol'],
        ['gpt-5.6-terra', 'gpt-5.6-terra'],
        ['gpt-5.5', 'gpt-5.5'],
        ['gpt-5-codex', 'gpt-5-codex'],
    ],
    claude_code: [
        ['sonnet', 'sonnet (claude-sonnet-5)'],
        ['fable', 'fable (claude-fable-5-1)'],
        ['opus', 'opus (claude-opus-5-5)'],
        ['haiku', 'haiku (claude-haiku-4-5)'],
    ],
    opencode: [
        ['opencode/ling-3.0-flash-fin-free', '[OpenCode Zen] Ling 3.0 Flash Fin Free - Free - 262K context'],
        ['opencode/muse-spark-1.2-contributor-free', '[OpenCode Zen] Muse Spark 1.2 Free - Free - 1M context'],
        ['opencode/longcat-2.5-preview-free', '[OpenCode Zen] LongCat 2.5 Preview Free - Free - 1M context'],
        ['opencode/space-bunny-free', '[OpenCode Zen] Space Bunny Free - Free - 1M context'],
        ['opencode/mimo-v2.6-flash-free', '[OpenCode Zen] MiMo-V2.6-Flash Free - Free - 200K context'],
        ['opencode/nemotron-3-ultra-free', '[OpenCode Zen] Nemotron 3 Ultra Free - Free - 1M context'],
        ['opencode/mimo-v2.5-free', '[OpenCode Zen] MiMo V2.5 Free - Free - 200K context'],
        ['opencode/nemotron-3.5-lightning-free', '[OpenCode Zen] Nemotron 3.5 Lightning Free - Free - 262K context'],
        ['opencode/big-pickle', '[OpenCode Zen] Big Pickle - Free - 200K context'],
        ['opencode/muse-spark-1.3-contributor-free', '[OpenCode Zen] Muse Spark 1.3 Free - Free - 1M context'],
        ['mistral/labs-devstral-small-2512', '[Mistral] Devstral Small 2 - Free - 256K context'],
        ['openrouter/stealth/space-bunny-alpha', '[OpenRouter] Space Bunny Alpha - Free - 1M context'],
        ['openrouter/poolside/laguna-s-2.1:free', '[OpenRouter] Laguna S 2.1 (free) - Free - 262K context'],
        ['openrouter/poolside/laguna-xs-2.1:free', '[OpenRouter] Laguna XS 2.1 (free) - Free - 262K context'],
        ['openrouter/cohere/north-mini-code:free', '[OpenRouter] North Mini Code (free) - Free - 256K context'],
        ['openrouter/thinkingmachines/inkling-small:free', '[OpenRouter] Inkling Small (free) - Free - 1M context'],
        ['openrouter/thinkingmachines/inkling:free', '[OpenRouter] Inkling (free) - Free - 1M context'],
        ['openrouter/openrouter/free', '[OpenRouter] Free Models Router - Free - 200K context'],
        ['openrouter/liquid/lfm-2.5-2.6b:free', '[OpenRouter] LFM2.5-2.6B (free) - Free'],
        ['opencode/claude-haiku-4-5', '[OpenCode Zen] Claude Haiku 4.5 - 200K context'],
        ['opencode/claude-opus-4-5', '[OpenCode Zen] Claude Opus 4.5 - 200K context'],
        ['opencode/claude-sonnet-4-5', '[OpenCode Zen] Claude Sonnet 4.5 - 1M context'],
        ['opencode/claude-opus-5-5', '[OpenCode Zen] Claude Opus 5.5 - 1M context'],
        ['opencode/claude-fable-5-1', '[OpenCode Zen] Claude Fable 5.1 - 1M context'],
    ],
    openclaw: OPENROUTER_MODELS,
    hermes: OPENROUTER_MODELS,
};

/** A page of a harness's models matching `q` (id or label, any case); the cursor is the id the last page ended on. */
function harnessModels(r: FixtureRequest): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    const rows = HARNESS_MODELS[r.params.name];
    if (!rows) {
        const supported = HARNESSES.map((h) => h.name);
        return apiError(404, 'not_found', `Harness '${r.params.name}' is not one NoClick runs.`, `Use one of: ${supported.join(', ')}; GET /v1/harnesses describes each.`, {
            field: 'harness',
            supported,
        });
    }
    const found = matching(rows, r.query.get('q')?.trim() ?? null, ([id, label]) => [id, label]);
    const cursor = r.query.get('cursor');
    const index = cursor ? found.findIndex(([id]) => id === cursor) : -1;
    if (cursor && index < 0) return apiError(400, 'invalid_request', 'Unknown cursor.', 'Pass next_cursor from the previous page.');
    const start = index + 1;
    const limit = Number(r.query.get('limit') ?? 50);
    const page = found.slice(start, start + limit);
    return list(
        page.map(([id, label]) => ({ object: 'harness_model', id, label })),
        start + limit < found.length ? page[page.length - 1][0] : null
    );
}

/** Each integration's operations: what each does, and whether it needs an account (Exa's reads run on NoClick's key without one). */
const INTEGRATION_OPERATIONS: Record<string, { name: string; description: string; needs_account?: false }[]> = {
    exa: [
        { name: 'search', description: 'Search the web and return the best-matching pages.', needs_account: false },
        { name: 'get_contents', description: 'Read the text of pages by URL.', needs_account: false },
        { name: 'answer', description: 'Answer a question from the web, with its sources.', needs_account: false },
        { name: 'find_similar', description: 'Find pages like a given URL.', needs_account: false },
        { name: 'create_monitor', description: 'Watch a search and deliver what is new on a schedule.' },
        { name: 'list_monitors', description: 'List your monitors.' },
    ],
    gmail: [
        { name: 'send_email', description: 'Send an email from the connected mailbox.' },
        { name: 'list_messages', description: 'List messages in the mailbox, newest first.' },
        { name: 'delete_message', description: 'Delete a message.' },
    ],
    slack: [
        { name: 'send_message_to_channel', description: 'Post a message to a channel.' },
        { name: 'list_channels', description: 'List the channels the account can see.' },
    ],
    stripe: [
        { name: 'list_invoices', description: 'List invoices, newest first.' },
        { name: 'create_refund', description: 'Refund a charge, in full or in part.' },
        { name: 'delete_customer', description: 'Delete a customer.' },
    ],
    // A model provider has no operations: an agent thinks with it.
    anthropic: [],
    openai: [],
    openrouter: [],
    opencode: [],
};

/** An operation as the catalog returns it (`connect/service._operations`). */
function operationView(op: (typeof INTEGRATION_OPERATIONS)[string][number]): Json {
    return { name: op.name, description: op.description, parameters: {}, read_only: !/send|create|delete/.test(op.name), scopes: [], needs_account: op.needs_account ?? true };
}

/** What a run answers, where the lab has something to show; anything else answers `{ok: true}`. */
const RUN_RESULTS: Record<string, Json> = {
    'exa.search': { results: [{ title: 'Invoice automation for small businesses', url: 'https://example.com/invoice-automation' }] },
};

/**
 * `POST /v1/run`, resolving `ref` as the API does: a connection of that name where the call acts
 * (the `NoClick-User` user, else the account) runs it; else the integration of that name runs an
 * operation that needs no account on NoClick's key, with `connection: null`.
 */
function runByRef(r: FixtureRequest): FixtureReply {
    const ref = String((r.body as Json | null)?.ref ?? '').trim();
    const dot = ref.indexOf('.');
    if (dot < 1 || dot === ref.length - 1) {
        return apiError(400, 'invalid_request', `'${ref}' names no single operation.`, "Name one operation as 'name.operation', e.g. 'exa.search'.", { field: 'ref' });
    }
    const name = ref.slice(0, dot);
    const operation = ref.slice(dot + 1);
    const acting = r.headers.get('NoClick-User');
    const whose = acting ? 'this user' : 'the account';
    const connection = CONNECTIONS.find((c) => c.name === name && c.user_id === acting);
    const integration = connection?.integration ?? name;
    const info = INTEGRATIONS.find((i) => i.name === integration);
    if (!info) {
        return apiError(
            404,
            'not_found',
            `'${ref}': ${whose} has no connection named '${name}'.`,
            "Name a connection (GET /v1/connections; a user's need its NoClick-User header), or an integration from GET /v1/integrations for its operations that need no account.",
            { connection: name }
        );
    }
    const op = INTEGRATION_OPERATIONS[integration].find((o) => o.name === operation);
    if (!op) return apiError(404, 'not_found', `'${ref}': ${integration} has no operation '${operation}'.`, `List its operations with GET /v1/integrations/${integration}/operations.`);
    const accountFree = op.needs_account === false;
    if (!connection && !accountFree) {
        return apiError(
            400,
            'invalid_request',
            `'${ref}': ${integration}.${operation} needs a connected ${info.label} account, and ${whose} has no connection named '${name}'.`,
            `Create a connection named '${name}' (POST /v1/connections with integration '${name}') holding the account; the same ref then runs in it.`,
            { connection: name, integration }
        );
    }
    // A disconnected connection never falls back to NoClick's key; a pending one runs only what needs no account.
    if (connection?.status === 'disconnected') {
        return apiError(424, 'credential_disconnected', `The '${name}' connection (${integration}) is disconnected.`, 'Create a connect link for the connection and have the user reconnect.', {
            connection: name,
            integration,
        });
    }
    if (connection?.status === 'pending' && !accountFree) {
        return apiError(424, 'needs_connection', `The '${name}' connection has no ${integration} account connected yet.`, 'Send the user connect_url; retry once the connect operation succeeds.', {
            connection: name,
            integration,
            credential_type: connection.credential_type,
            connect_url: connection.connect_link?.url ?? null,
            operation_id: connection.connect_link?.operation_id ?? null,
        });
    }
    return ok({ object: 'operation_result', ref, integration, operation, connection: connection?.name ?? null, result: RUN_RESULTS[ref] ?? { ok: true } });
}

/** `?q=` over some rows' fields, case-insensitive; no query matches all. */
const matching = <T>(rows: readonly T[], query: string | null, fields: (row: T) => (string | null)[]) =>
    query ? rows.filter((row) => fields(row).some((f) => f?.toLowerCase().includes(query.toLowerCase()))) : [...rows];

// ── filters ────────────────────────────────────────────────────────────────

const csv = (value: string | null) => (value ? value.split(',').filter(Boolean) : null);

/** `all` / `none` / a user's id against a row's user. */
function userMatches(filter: string | null, userId: unknown): boolean {
    if (!filter || filter === 'all') return true;
    if (filter === 'none') return userId == null;
    return filter === userId;
}

function keyMatches(filter: string | null, keyId: unknown): boolean {
    if (!filter) return true;
    const key = KEYS.find((k) => k.id === filter || filter.startsWith(k.key_prefix) || k.key_prefix.startsWith(filter));
    return !!key && key.id === keyId;
}

function after(filter: string | null, iso: unknown): boolean {
    return !filter || Date.parse(String(iso)) > Date.parse(filter);
}

function before(filter: string | null, iso: unknown): boolean {
    return !filter || Date.parse(String(iso)) < Date.parse(filter);
}

function operationRows(r: FixtureRequest): Json[] {
    const q = r.query;
    const statuses = csv(q.get('status'))?.flatMap((s) => (s === 'live' ? LIVE : [s]));
    const notStatuses = csv(q.get('status_not'));
    const kinds = csv(q.get('kind'));
    // Designed port requests (m_numbers.ts) and a coordinator's work (n_orchestration.ts) answer reads of their own kind or agent.
    const orchestration =
        ORCHESTRATION_AGENT_IDS.has(q.get('agent_id') ?? '') || kinds?.some((k) => k === 'agent.task' || k === 'agent.ask') ? ORCHESTRATION_OPERATIONS : [];
    const rows = [...(kinds?.includes('phone.port_in') ? [...OPERATIONS, ...portRequests(r.set)] : OPERATIONS), ...orchestration];
    return rows.filter(
        (o) =>
            (!statuses || statuses.includes(String(o.status))) &&
            (!notStatuses || !notStatuses.includes(String(o.status))) &&
            (!kinds || kinds.includes(String(o.kind))) &&
            (!q.get('agent_id') || o.agent_id === q.get('agent_id')) &&
            userMatches(q.get('user_id'), o.user_id) &&
            keyMatches(q.get('key_id'), o.key_id) &&
            after(q.get('created_after'), o.created_at) &&
            before(q.get('created_before'), o.created_at) &&
            after(q.get('updated_after'), o.updated_at) &&
            (!q.get('cause') || (o.status === 'failed' && o.cause === q.get('cause')))
    );
}

/** `GET /v1/operations/failures`: the failed rows the list's filters keep, one entry per cause, the latest first. */
function failures(r: FixtureRequest): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    const rows = r.set === 'populated' ? operationRows(r).filter((o) => o.status === 'failed') : [];
    const causes = new Map<string, Json[]>();
    for (const o of rows) causes.set(String(o.cause), [...(causes.get(String(o.cause)) ?? []), o]);
    const distinct = (ops: Json[], key: string) => [...new Set(ops.map((o) => o[key]).filter((v) => v != null))] as string[];
    const data = [...causes.entries()].map(([cause, ops]) => {
        const times = ops.map((o) => String(o.created_at)).sort();
        const agents = distinct(ops, 'agent_id');
        const users = distinct(ops, 'user_id');
        const keys = distinct(ops, 'key_id');
        return {
            object: 'operation_failure',
            cause,
            count: ops.length,
            first_at: times[0],
            last_at: times[times.length - 1],
            failed_on: ops[0].failed_on,
            error: ops[0].error,
            operation_id: ops[0].id,
            kinds: distinct(ops, 'kind').sort(),
            agent_ids: agents,
            agent_count: agents.length,
            user_ids: users,
            user_count: users.length,
            key_ids: keys,
            key_count: keys.length,
        };
    });
    const limit = Number(r.query.get('limit') ?? 50);
    return ok({ object: 'operation_failures', data: data.slice(0, limit), total: rows.length, has_more: data.length > limit });
}

/** `gmail.*` or an exact name, over the dotted form. */
function toolMatches(pattern: string | null, name: unknown): boolean {
    if (!pattern) return true;
    const re = new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')}$`);
    return re.test(String(name));
}

function toolCallRows(r: FixtureRequest): Json[] {
    const q = r.query;
    return TOOL_CALLS.filter(
        (c) =>
            toolMatches(q.get('tool'), c.tool_name) &&
            (!q.get('status') || c.status === q.get('status')) &&
            (!q.get('source') || c.source === q.get('source')) &&
            (!q.get('agent_id') || c.agent_id === q.get('agent_id')) &&
            userMatches(q.get('user_id'), c.user_id) &&
            after(q.get('since'), c.created_at) &&
            before(q.get('until'), c.created_at)
    );
}

function statusMatches(filter: string | null, code: unknown): boolean {
    if (!filter) return true;
    const n = Number(code);
    return /^[1-5]xx$/.test(filter) ? Math.floor(n / 100) === Number(filter[0]) : n === Number(filter);
}

function requestRows(r: FixtureRequest): Json[] {
    const q = r.query;
    return API_REQUESTS.filter(
        (x) =>
            (!q.get('method') || x.method === q.get('method')) &&
            statusMatches(q.get('status'), x.status) &&
            (!q.get('error_type') || x.error_type === q.get('error_type')) &&
            keyMatches(q.get('key_id'), x.key_id) &&
            (!q.get('route') || String(x.route).startsWith(String(q.get('route')))) &&
            userMatches(q.get('user_id'), x.user_id) &&
            after(q.get('since'), x.created_at) &&
            before(q.get('until'), x.created_at)
    );
}

/** A cursor page over filtered rows: the cursor is the next row's offset. */
function paged(r: FixtureRequest, rows: readonly Json[]): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    if (r.set !== 'populated') return list([]);
    const offset = Number(r.query.get('cursor') ?? 0);
    const limit = Number(r.query.get('limit') ?? 50);
    const page = rows.slice(offset, offset + limit);
    return list(page, offset + limit < rows.length ? String(offset + limit) : null);
}

function summarize(r: FixtureRequest, rows: readonly Json[]): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    const shown = r.set === 'populated' ? rows : [];
    const byStatus = Object.fromEntries([...LIVE, ...TERMINAL].map((s) => [s, shown.filter((o) => o.status === s).length]));
    return ok({ total: shown.length, by_status: byStatus });
}

function findOperation(id: string): Json | undefined {
    if (id === CLI_TRY_OPERATION_ID) {
        cliTryReads += 1;
        return cliTryOperation();
    }
    return id === TRY_IT_OPERATION_ID ? tryItOperation() : (OPERATIONS.find((o) => o.id === id) ?? findPortRequest(id) ?? LAB_OPERATIONS.get(id));
}

function detail(r: FixtureRequest, row: Json | undefined, what: string): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    return row ? ok(row) : apiError(404, 'not_found', `No ${what} with id ${r.params.id}.`);
}

function agentById(id: string) {
    return AGENTS.find((a) => a.id === id) ?? (LAB_EXTRA_AGENTS.find((a) => a.id === id) as (typeof AGENTS)[number] | undefined);
}

export const routes: readonly FixtureRoute[] = [
    { method: 'GET', path: '/v1/operations', reply: (r) => paged(r, operationRows(r)) },
    { method: 'GET', path: '/v1/operations/summary', reply: (r) => summarize(r, operationRows(r)) },
    { method: 'GET', path: '/v1/operations/failures', reply: failures },
    { method: 'GET', path: '/v1/operations/:id', reply: (r) => detail(r, findOperation(r.params.id), 'operation') },
    // The long-poll answers at once here: the fixture's operations don't move.
    { method: 'GET', path: '/v1/operations/:id/wait', reply: (r) => detail(r, findOperation(r.params.id), 'operation') },
    {
        method: 'GET',
        path: '/v1/operations/:id/tool_calls',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const ids = OPERATION_TOOL_CALLS[r.params.id] ?? [];
            return list(ids.map((id) => TOOL_CALLS.find((c) => c.id === id)!));
        },
    },
    {
        method: 'POST',
        path: '/v1/operations/:id/cancel',
        reply: (r) => {
            const port = cancelPortRequest(r.params.id);
            if (port) return port;
            const op = findOperation(r.params.id);
            if (!op) return apiError(404, 'not_found', `No operation with id ${r.params.id}.`);
            if (TERMINAL.includes(String(op.status))) {
                return apiError(409, 'conflict', `The operation already ${op.status}.`, 'Nothing to cancel; read its result with GET /v1/operations/{id}.');
            }
            const events = [...(op.events as Json[]), { status: 'canceled', at: new Date(FIXTURE_NOW_MS).toISOString(), by: 'owner' }];
            return ok({ ...op, status: 'canceled', events, error: { type: 'canceled', message: 'The operation was canceled.' } });
        },
    },
    { method: 'GET', path: '/v1/tool_calls', reply: (r) => paged(r, toolCallRows(r)) },
    {
        method: 'GET',
        path: '/v1/tool_calls/summary',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const rows = r.set === 'populated' ? toolCallRows(r) : [];
            const errors = rows.filter((c) => c.status === 'error').length;
            return ok({ total: rows.length, success: rows.length - errors, error: errors });
        },
    },
    { method: 'GET', path: '/v1/requests', reply: (r) => paged(r, requestRows(r)) },
    {
        method: 'POST',
        path: '/v1/agents',
        reply: (r) => {
            const body = (r.body ?? {}) as Json;
            const userId = r.headers.get('NoClick-User');
            const clash = AGENTS.find((a) => a.name === body.name && a.user_id === userId);
            if (clash) {
                return apiError(409, 'conflict', `An agent named '${String(body.name)}' already exists.`, 'Pick another name, or use the existing agent.', {
                    existing_id: clash.id,
                });
            }
            return {
                status: 201,
                body: {
                    object: 'agent',
                    id: fixtureId(3, 50),
                    name: body.name,
                    instructions: body.instructions,
                    model: body.model ?? 'openrouter/~openai/gpt-luna-latest',
                    harness: body.harness ?? 'sdk',
                    tools: body.tools ?? [],
                    user_id: userId,
                    workflow_id: fixtureId(8, 50),
                    parent_id: null,
                    ttl_s: null,
                    expires_at: null,
                    budget_usd_per_month: body.budget_usd_per_month ?? null,
                    created_at: new Date(FIXTURE_NOW_MS).toISOString(),
                },
            };
        },
    },
    {
        method: 'PATCH',
        path: '/v1/agents/:id',
        reply: (r) => {
            const agent = agentById(r.params.id);
            return agent ? ok({ ...agent, ...((r.body ?? {}) as Json) }) : apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
        },
    },
    {
        method: 'DELETE',
        path: '/v1/agents/:id',
        reply: (r) => (agentById(r.params.id) ? ok({ object: 'agent', id: r.params.id, deleted: true }) : apiError(404, 'not_found', `Agent ${r.params.id} not found.`)),
    },
    {
        method: 'DELETE',
        path: '/v1/agents/:id/grants/:grant',
        reply: (r) => {
            const agent = agentById(r.params.id);
            const grant = agent?.grants.find((g) => g.id === r.params.grant);
            return grant ? ok({ object: 'agent_grant', id: r.params.grant, revoked: true }) : apiError(404, 'not_found', 'No such grant on this agent.');
        },
    },
    {
        method: 'POST',
        path: '/v1/agents/:id/messages',
        reply: (r) => {
            const agent = agentById(r.params.id);
            if (!agent) return apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
            if (agent.harness !== 'sdk') {
                cliTryReads = 0;
                return { status: 202, body: cliTryOperation() };
            }
            const op = tryItOperation();
            return { status: 202, body: { ...op, status: 'running', result: null, events: (op.events as Json[]).slice(0, 2) } };
        },
    },
    {
        method: 'GET',
        path: '/v1/agents/:id/conversations',
        reply: (r) => {
            const rows = [...CONVERSATIONS, ...ORCHESTRATION_CONVERSATIONS].filter((c) => c.agent_id === r.params.id && userMatches(r.query.get('user_id'), c.user_id));
            return paged(r, rows);
        },
    },
    {
        method: 'GET',
        path: '/v1/agents/:id/conversations/:conversation',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            if (!agentById(r.params.id)) return apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
            // A conversation nobody has written in yet reads as empty, as the API answers it, in the agent's one session.
            const messages = ORCHESTRATION_TRANSCRIPTS[`${r.params.id}/${r.params.conversation}`] ?? TRANSCRIPTS[r.params.conversation] ?? [];
            return ok({ object: 'conversation', id: r.params.conversation, agent_id: r.params.id, session: 'main', messages });
        },
    },
    {
        method: 'GET',
        path: '/v1/agents/:id/a2a/card',
        reply: (r) => {
            const agent = agentById(r.params.id);
            if (!agent) return apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
            return ok({ protocolVersion: '0.3.0', name: agent.name, url: `https://api.noclick.com/v1/agents/${agent.id}/a2a`, skills: [] });
        },
    },
    {
        method: 'GET',
        path: '/v1/integrations',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const kind = r.query.get('kind');
            return list(matching(INTEGRATIONS, r.query.get('q'), (i) => [i.name, i.label]).filter((i) => !kind || i.kind === kind));
        },
    },
    { method: 'GET', path: '/v1/harnesses', reply: (r) => (r.set === 'error' ? PAGE_ERROR : list(HARNESSES)) },
    { method: 'GET', path: '/v1/harnesses/:name/models', reply: harnessModels },
    {
        method: 'GET',
        path: '/v1/integrations/:name',
        reply: (r) => {
            const found = INTEGRATIONS.find((i) => i.name === r.params.name);
            if (!found) return apiError(404, 'not_found', `No integration named '${r.params.name}'.`);
            return ok({ ...found, operations: INTEGRATION_OPERATIONS[found.name].map(operationView), lookup_fields: [] });
        },
    },
    {
        method: 'GET',
        path: '/v1/integrations/:name/operations',
        reply: (r) => {
            const operations = INTEGRATION_OPERATIONS[r.params.name];
            if (!operations) return apiError(404, 'not_found', `No integration named '${r.params.name}'.`);
            return list(matching(operations, r.query.get('q'), (op) => [op.name, op.description]).map(operationView));
        },
    },
    { method: 'POST', path: '/v1/run', reply: runByRef },
    {
        method: 'GET',
        path: '/v1/integrations/:name/operations/:op',
        reply: (r) => {
            const operations = INTEGRATION_OPERATIONS[r.params.name];
            if (!operations) return apiError(404, 'not_found', `No integration named '${r.params.name}'.`);
            const op = operations.find((o) => o.name === r.params.op);
            return op ? ok(operationView(op)) : apiError(404, 'not_found', `'${r.params.name}' has no operation '${r.params.op}'.`);
        },
    },
];
