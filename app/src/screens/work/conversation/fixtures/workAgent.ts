// A fake /v1 for an agent's conversation in Work: the agent and the account's others, each conversation's history,
// settings, commands, requests and live events, a send answered by the turn a test or the preview scripts, Stop,
// queueing, fork and revert, context and usage, its sandbox and files. The real platform client runs
// over it (workFixtureClient), so the conversation is exercised through the SDK as it is in the app.
import { workFixtureClient } from '../../fixtures/client';
import { TURN_FAILED_LINE } from '@/lib/agentThread/messages';
import type { NoClick } from 'noclick';
import { renameRefused } from '../../agents/fixtures/workAgents';
import { machineRoutes, machineStock, type MachineStock } from '../../machine/fixtures/machineStock';

type Json = Record<string, unknown>;

export const AGENT_ID = '5c1e0b8a-6f0e-4b8c-9a71-0c2d4e8f1a01';

export const AGENT: Json = {
    object: 'agent',
    id: AGENT_ID,
    name: 'Wirefern',
    harness: 'claude_code',
    model: 'claude-opus-5-5',
    role: 'Knows the Wirefern code and its customers',
    instructions: 'You look after the Wirefern code.',
    user_id: null,
    status: 'idle',
    origin: 'api',
    budget_usd_per_month: 25,
    machine_id: null,
    docker: false,
    sandbox_size: null,
    app_testing: 'by_itself',
    app_testing_usd_per_hour: 0.44,
};

/** The account's machines, as GET /v1/machines lists them. */
export const MACHINES: Json[] = [{ object: 'machine', id: 'm-box', name: 'wirefern-box', kind: 'noclick', status: 'running', size: 'small', region: 'us-east', cpu: 2, memory_gb: 4, disk_gb: 80, monthly_usd: 31.2, docker: false, app_testing: 'never', agents_enabled: true }];

export const OTHER_AGENTS: Json[] = [
    { object: 'agent', id: 'a-support', name: 'Support', harness: 'sdk', model: 'claude-sonnet-5-5', role: 'Answers customers on noclick.com', user_id: null, status: 'idle', origin: 'api' },
    { object: 'agent', id: 'a-growth', name: 'Growth', harness: 'claude_code', model: 'claude-sonnet-5-5', role: 'Writes the guides and the pricing page', user_id: null, status: 'idle', origin: 'api', former_names: ['Marketing'] },
];

/** One live event, as the conversation's stream sends it (`type` is its SSE event name). */
export type LiveEvent = Json & { type: string };

/** A turn's script: what it streams (given its operation's id), then its reply or its error. `hold` keeps it running
 *  until the test settles it. */
/** A turn's script: its live events, then its reply, a plain error, or (`failure`) its model connection refused, as the
 *  platform fails it: the operation's typed error, a failed reply in history carrying it, and on the stream a failed
 *  message that doesn't. */
export type Turn = (turn: string, body: Json) => { events?: LiveEvent[]; reply?: string; error?: string; failure?: Json; hold?: boolean; toolCalls?: Json[]; refused?: Json };

/** The line a failed turn's reply reads, as the platform's history has it. */
export { TURN_FAILED_LINE };

export const COMMANDS: Json = {
    harness: 'claude_code',
    commands: [
        { name: 'compact', description: 'Clear the conversation history but keep a summary in context', argument_hint: '[instructions]', source: 'harness', aliases: [] },
        { name: 'review', description: 'Review a pull request', argument_hint: '', source: 'harness', aliases: [] },
        { name: 'init', description: 'Write a CLAUDE.md with what it learns about the codebase', argument_hint: '', source: 'harness', aliases: [] },
        { name: 'clear', description: 'Clear conversation history', argument_hint: '', source: 'harness', aliases: ['reset', 'new'] },
        { name: 'cost', description: 'Show the total cost of this session', argument_hint: '', source: 'harness', aliases: [] },
        { name: 'deploy-check', description: 'Check a deploy is safe (from .claude/commands)', argument_hint: '<env>', source: 'custom', aliases: [] },
    ],
    skills: [
        { name: 'code-review', description: 'Review the current diff for correctness bugs' },
        { name: 'dataviz', description: 'Draw a chart that reads as one system' },
    ],
    capabilities: { commands: true, skills: true, compact: true, review: true, steer: true, queue: true },
    not_supported: { goal: 'A goal runs over turns NoClick can’t follow yet.' },
    withheld: ['config', 'mcp', 'permissions'],
    mapped: [
        { name: 'clear', to: 'new' },
        { name: 'cost', to: 'usage' },
        { name: 'model', to: 'model' },
    ],
    as_of: '2026-11-10T09:00:00Z',
    read_from: 'this_conversation',
};

const harness = (name: string, label: string, defaultModel: string, efforts: string[], speeds: string[]): Json => ({
    name, label, version: null, default_model: defaultModel, custom_models: false, model_connection: name === 'sdk' ? 'optional' : 'required',
    integrations: ['anthropic', 'openai', 'openrouter'], streaming: 'tokens', shell: 'built_in', notes: [], efforts, default_effort: efforts[1] ?? null, speeds,
});

export const HARNESSES: Json[] = [
    harness('claude_code', 'Claude Code', 'claude-opus-5-5', ['low', 'medium', 'high', 'max'], ['standard', 'fast']),
    harness('codex', 'Codex', 'gpt-5.6', ['minimal', 'low', 'medium', 'high', 'xhigh'], ['standard', 'fast']),
    harness('sdk', 'NoClick agent', 'claude-sonnet-5-5', ['low', 'medium', 'high'], []),
];

const MODELS: Record<string, Json[]> = {
    claude_code: [{ id: 'claude-opus-5-5', label: 'Opus 5.5' }, { id: 'claude-sonnet-5-5', label: 'Sonnet 5.5' }, { id: 'claude-haiku-5-5', label: 'Haiku 5.5' }],
    codex: [{ id: 'gpt-5.6', label: 'GPT-5.6' }],
    sdk: [{ id: 'claude-sonnet-5-5', label: 'Sonnet 5.5' }, { id: 'openrouter/openai/gpt-luna', label: '[openrouter] OpenAI: GPT-6 Luna' }],
};

export const CONNECTIONS: Json[] = [{ object: 'connection', id: 'conn-1', name: 'anthropic-plan', integration: 'anthropic', credential_type: 'agent_claude_code_oauth', connected: true, status: 'connected' }];

const MODEL_PROVIDERS: Json[] = [
    { name: 'anthropic', label: 'Claude', kind: 'model', account_free_operation_count: 0, credential_types: ['agent_anthropic', 'agent_claude_code_oauth'] },
    { name: 'openai', label: 'ChatGPT', kind: 'model', account_free_operation_count: 0, credential_types: ['agent_openai', 'agent_codex_oauth'] },
    { name: 'openrouter', label: 'OpenRouter', kind: 'model', account_free_operation_count: 0, credential_types: ['agent_openrouter'] },
];

/** An OpenRouter key its provider refused, as GET /v1/connections lists it once NoClick marked it. */
export const REFUSED_OPENROUTER: Json = {
    object: 'connection', id: 'conn-or', name: 'openrouter', integration: 'openrouter', credential_type: 'agent_openrouter', status: 'disconnected', origin: 'api', account: null,
    disconnected: { reason: 'refused', message: 'OpenRouter refused this key.', since: '2026-11-10T09:00:00Z', next_step: 'Reconnect it with a connect link.' },
};

export function settingsFor(conversation: string, overrides: Json = {}): Json {
    return {
        object: 'conversation_settings',
        conversation,
        title: null,
        archived: false,
        harness: 'claude_code',
        model: 'claude-opus-5-5',
        effort: 'high',
        efforts: ['low', 'medium', 'high', 'max'],
        speed: 'standard',
        speeds: ['standard', 'fast'],
        model_connection: 'anthropic-plan',
        accounts: [{ name: 'anthropic-plan', integration: 'anthropic', kind: 'plan', usable: true, why: null }],
        overridden: [],
        permission_mode: 'full-access',
        effective_permission_mode: 'full-access',
        permission_modes: ['approval-required', 'auto-accept-edits', 'full-access'],
        not_supported: {},
        forked_from: null,
        ...overrides,
    };
}

export interface FakeWorkAgent {
    client: NoClick;
    /** The fake's own fetch, which `client` runs over: another client (a lab putting fixtures together) can too. */
    fetch: typeof window.fetch;
    requests: { method: string; path: string; query: URLSearchParams; body: unknown }[];
    /** Each conversation's stored messages, as history returns them. */
    histories: Map<string, Json[]>;
    /** What each conversation's harness asks, by id. */
    asks: Map<string, Json>;
    operations: Map<string, Json>;
    settings: Map<string, Json>;
    /** Send events to every open stream of `conversation` ("main" when left out); the stream keeps all but messages
     *  for a watch that replays. */
    emit: (events: LiveEvent[], conversation?: string) => void;
    /** End every open stream, as a dropped connection does. */
    drop: () => void;
    /** Settle an operation and answer whoever waits on it. */
    settle: (id: string, status: string, extra?: Json) => void;
    /** Finish a held turn: its reply lands in the history and the stream, its operation succeeds. */
    reply: (operationId: string, text: string, extra?: Json, conversation?: string) => void;
    watching: () => number;
    /** The account's connections as GET /v1/connections lists them (change one to reconnect it in place). */
    connections: Json[];
    /** The agent's MCP servers, as added and taken away. */
    toolServers: Json[];
    /** Each conversation's triggered turns, newest first, as GET .../conversations/{c}/activity reads them (change
     *  them as a turn moves). */
    activity: Map<string, Json[]>;
    /** The requests a person answers (a held call's approval), by id, as GET /v1/humans/requests/{id} reads them. */
    humanRequests: Map<string, Json>;
    /** The account's machines (a bought one joins them), and what a new one can be; a test may run a host out. */
    machines: Json[];
    stock: MachineStock;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const notFound = (message: string) => json({ error: { type: 'not_found', message } }, 404);
const TERMINAL = new Set(['succeeded', 'failed', 'canceled', 'expired']);

const STATE_RANK: Record<string, number> = { ok: 0, near: 1, used_up: 2 };

/** A plan connection's reading as GET /v1/connections/{ref}/usage answers it, from the windows the fixture gives it
 *  (`windows`, the API's shape): with `model`, the windows that name no model and those whose model the id names; the
 *  worst state, and the tightest window (the used-up one that resets last, else the most used). A connection that
 *  isn't a plan is refused as the API refuses it. */
function planUsage(connection: Json, model: string | null): Response {
    if (!connection.plan) return json({ error: { type: 'invalid_request', message: 'This connection isn’t a Claude or ChatGPT plan.', next_step: 'Read usage on a plan’s connection.' } }, 400);
    const all = (connection.windows as Json[] | undefined) ?? [];
    const windows = model ? all.filter((w) => !(w.models as string[]).length || (w.models as string[]).some((m) => model.toLowerCase().includes(m.toLowerCase()))) : all;
    const out = windows.filter((w) => w.state === 'used_up').sort((a, b) => String(b.resets_at).localeCompare(String(a.resets_at)));
    const tightest = out[0] ?? [...windows].sort((a, b) => (b.used as number) - (a.used as number))[0] ?? null;
    const state = !connection.windows ? 'unknown' : windows.reduce((worst, w) => (STATE_RANK[w.state as string] > STATE_RANK[worst] ? (w.state as string) : worst), 'ok');
    return json({
        object: 'plan_usage', connection: connection.id, plan: connection.plan, state, windows, tightest,
        available_at: state === 'used_up' ? (tightest?.resets_at ?? null) : null, next_steps: [{ kind: 'connect', label: 'Connect another', until: null, connection: null, pays: null }],
        as_of: connection.windows ? '2026-11-17T09:00:00Z' : null, source: connection.windows ? 'provider' : null,
    });
}

/** The socket every live view a fixture mints opens (an nc test's `fakeViewerSockets` answers it). */
export const LIVE_VIEW_SOCKET = 'wss://api.noclick.test/v1/browsers/live_views/attach';
/** What each token a fixture minted opens, as the socket's binding says: a thumbnail, or a view that drives. */
export const LIVE_VIEW_TOKENS = new Map<string, { thumb: boolean; control: boolean }>();
let liveViewTokens = 0;

/** A browser's live view, as POST /v1/browsers/{id}/live_view and .../live_control answer it: a token for the socket,
 *  and for driving it, only once the browser is taken over. Undefined for any other request. */
export function liveViewRoutes(method: string, path: string, browsers: Json[], body: unknown): Response | undefined {
    const asked = method === 'POST' ? path.match(/^\/v1\/browsers\/([^/]+)\/(live_view|live_control)$/) : null;
    if (!asked) return undefined;
    const browser = browsers.find((b) => b.id === asked[1]);
    if (!browser) return notFound('No such browser.');
    const control = asked[2] === 'live_control';
    if (control && !browser.held) return json({ error: { type: 'conflict', message: 'The browser isn’t taken over: take it over before you drive it.' } }, 409);
    const thumb = !control && (body as Json | null)?.thumb === true;
    const token = `view-token-${++liveViewTokens}`;
    LIVE_VIEW_TOKENS.set(token, { thumb, control });
    return json({ object: 'browser_live_view', browser_id: browser.id, control, thumb, url: LIVE_VIEW_SOCKET, token, token_expires_at: new Date(Date.now() + 120_000).toISOString() });
}

/** What Work's pickers read beside an agent, as /v1 answers them: the harnesses and their models, the account's
 *  connections (each checked as `checks` says; `ok` when left out) and model providers, and its machines. Undefined
 *  for any other request. */
export function catalogRoutes(method: string, path: string, connections: Json[], checks: Record<string, Json> | undefined, at: () => string, query?: URLSearchParams): Response | undefined {
    if (method === 'GET' && path === '/v1/harnesses') return json({ object: 'list', data: HARNESSES });
    const models = path.match(/^\/v1\/harnesses\/([^/]+)\/models$/);
    if (method === 'GET' && models) return json({ object: 'list', data: MODELS[models[1]] ?? [] });
    if (method === 'GET' && path === '/v1/connections') return json({ object: 'list', data: connections, next_cursor: null });
    const reading = path.match(/^\/v1\/connections\/([^/]+)\/usage$/);
    if (method === 'GET' && reading) {
        const ref = decodeURIComponent(reading[1]);
        const found = connections.find((c) => c.name === ref || c.id === ref);
        if (!found) return notFound(`No connection ${ref}.`);
        return planUsage(found, query?.get('model') ?? null);
    }
    const connection = path.match(/^\/v1\/connections\/([^/]+)(\/verify)?$/);
    if (connection) {
        const ref = decodeURIComponent(connection[1]);
        const found = connections.find((c) => c.name === ref || c.id === ref);
        if (!found) return notFound(`No connection ${ref}.`);
        if (method === 'GET' && !connection[2]) return json(found);
        if (method === 'POST' && connection[2]) {
            if (checks?.[ref]?.fail) return json({ error: { type: 'invalid_request', message: 'The check didn’t run.' } }, 400);
            const check = { verdict: 'ok', reason: null, message: 'Accepted.', next_step: null, checked_at: at(), cached: false, ...checks?.[ref] };
            if (check.verdict === 'refused') Object.assign(found, { status: 'disconnected', disconnected: { reason: check.reason === 'signed_out' ? 'signed_out' : 'refused', message: check.message, since: at(), next_step: check.next_step } });
            return json({ ...found, check });
        }
    }
    if (method === 'GET' && path === '/v1/integrations') return json({ object: 'list', data: MODEL_PROVIDERS });
    // Where it can run: one always-on machine of NoClick's, agents on machines enabled.
    if (method === 'GET' && path === '/v1/machines') return json({ object: 'list', data: MACHINES, agents_enabled: true, next_cursor: null });
    if (method === 'GET' && path === '/v1/machines/sizes') return json({ object: 'list', data: machineStock('one', []).sizes(new URLSearchParams('include_dominated=true')) });
    const machine = path.match(/^\/v1\/machines\/([^/]+)$/);
    if (machine && method === 'GET') return json(MACHINES.find((m) => m.id === machine[1]) ?? {});
    return undefined;
}

export function fakeWorkAgent(
    options: {
        agent?: Json;
        histories?: Record<string, Json[]>;
        asks?: Json[];
        operations?: Json[];
        turn?: Turn;
        at?: () => string;
        settings?: Record<string, Json>;
        context?: Json;
        usage?: Json;
        sandbox?: Json;
        files?: Json[];
        conversations?: Json[];
        /** The session everyone talking to it shares (`main` when left out); a clear or a resume moves it. */
        session?: string;
        /** The channels it's in, as GET /v1/channels?agent_id= lists them. */
        channels?: Json[];
        /** The account's connections (its Claude plan, connected, when left out). */
        connections?: Json[];
        /** What POST /v1/connections/{ref}/verify answers for a ref (`ok` when left out); `refused` marks it, and
         *  `fail` makes the check itself fail. */
        checks?: Record<string, Json>;
        /** Where each agent stands, as GET /v1/agents/states lists them. */
        states?: Json[];
        /** What each agent it started has cost on its task, its one session (`task`), as its usage says. */
        taskCosts?: Record<string, number>;
        /** Each harness subagent's task by its call id, which a message to it is kept for. */
        subagentTitles?: Record<string, string>;
        /** Its triggers, as GET /v1/agents/{id}/triggers lists them (none when left out). */
        triggers?: Json[];
        /** Its MCP servers, as GET /v1/agents/{id}/tool_servers lists them (none when left out). */
        toolServers?: Json[];
        /** The URLs whose servers ask their client to sign in: adding one takes a credential. */
        signsIn?: string[];
        /** The account's browsers, as GET /v1/browsers lists them (newest first; filtered by agent and conversation). */
        browsers?: Json[];
        /** Each conversation's triggered turns, newest first (agents.activity items). */
        activity?: Record<string, Json[]>;
        /** Requests a person answers, as GET /v1/humans/requests/{id} reads them. */
        humanRequests?: Json[];
        /** What a WhatsApp connection keeps of each chat id (`{name, avatar_url}`), by the connection's ref. */
        chatProfiles?: Record<string, Record<string, Json>>;
        /** A PATCH of the agent the platform refuses: its error response, else undefined to make it. */
        refuseUpdate?: (body: Json) => Response | undefined;
        /** Which hosts sell machines: Hetzner in Europe and DigitalOcean everywhere (the default), or DigitalOcean alone. */
        machineHosts?: 'two' | 'one';
    } = {}
): FakeWorkAgent {
    const at = options.at ?? (() => new Date().toISOString());
    const agent: Json = { ...AGENT, ...options.agent };
    const histories = new Map<string, Json[]>(Object.entries(options.histories ?? { main: [] }).map(([k, v]) => [k, [...v]]));
    const asks = new Map<string, Json>((options.asks ?? []).map((a) => [String(a.id), a]));
    const operations = new Map<string, Json>((options.operations ?? []).map((op) => [String(op.id), op]));
    const settings = new Map<string, Json>(Object.entries(options.settings ?? {}));
    const extraConversations = [...(options.conversations ?? [])];
    const connections: Json[] = (options.connections ?? CONNECTIONS).map((c) => ({ ...c }));
    const toolServers: Json[] = (options.toolServers ?? []).map((s) => ({ ...s }));
    const activity = new Map<string, Json[]>(Object.entries(options.activity ?? {}));
    const humanRequests = new Map<string, Json>((options.humanRequests ?? []).map((r) => [String(r.id), { ...r }]));
    const machines: Json[] = MACHINES.map((m) => ({ ...m }));
    const stock = machineStock(options.machineHosts ?? 'two');
    const waiting = new Map<string, (() => void)[]>();
    const streams = new Map<ReadableStreamDefaultController<Uint8Array>, string>();
    const requests: FakeWorkAgent['requests'] = [];
    const encoder = new TextEncoder();
    let made = 0;
    let messageIds = 0;
    let active = options.session ?? 'main';
    const historyOf = (c: string) => {
        if (!histories.has(c)) histories.set(c, []);
        return histories.get(c)!;
    };
    const settingsOf = (c: string) => {
        if (!settings.has(c)) settings.set(c, settingsFor(c));
        return settings.get(c)!;
    };

    const frame = ({ type, ...data }: LiveEvent) => encoder.encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    // The moments each conversation's stream keeps (every event but a message, which the conversation keeps): what a
    // watch with `replay` hears first.
    const streamed = new Map<string, LiveEvent[]>();
    const emit = (events: LiveEvent[], conversation = 'main') => {
        for (const event of events) {
            if (event.type !== 'message') streamed.set(conversation, [...(streamed.get(conversation) ?? []), event]);
            for (const [stream, c] of streams) if (c === conversation) stream.enqueue(frame(event));
        }
    };
    const settle = (id: string, status: string, extra: Json = {}) => {
        const op: Json = { ...operations.get(id), status, updated_at: at(), ...extra };
        operations.set(id, op);
        // A turn's settle tells its conversation's watchers it ended, with its reply's words (the platform's turn_end).
        if (op.kind === 'agent.message' && typeof op.conversation === 'string' && TERMINAL.has(status)) {
            const text = (op.result as Json | undefined)?.text;
            emit([{ type: 'turn_end', status, ...(typeof text === 'string' ? { text } : {}), operation_id: id }], op.conversation);
        }
        for (const wake of waiting.get(id) ?? []) wake();
        waiting.delete(id);
    };
    const reply = (operationId: string, text: string, extra: Json = {}, conversation = 'main') => {
        const message = { id: `m${++messageIds}`, role: 'assistant', text, created_at: at(), operation_id: operationId, ...extra };
        historyOf(conversation).push(message);
        emit([{ type: 'message', ...message }], conversation);
        settle(operationId, 'succeeded', { result: { text, conversation, tool_calls: extra.tool_calls ?? [], operation_id: operationId } });
    };

    const conversationView = (c: string): Json => {
        const h = historyOf(c);
        const last = h[h.length - 1];
        const s = settingsOf(c);
        return { object: 'conversation', conversation: c, title: s.title ?? null, preview: last?.text ?? null, turns: h.filter((m) => m.role === 'assistant').length, last_activity: last?.created_at ?? at(), archived: s.archived === true, status: 'active', people: [], active: c === active };
    };
    // The note a clear or a resume leaves where the session picks up, as sessions._point writes it.
    const moveTo = (c: string, how: 'cleared' | 'resumed') => {
        active = c;
        historyOf(c).push({ id: `m${++messageIds}`, role: 'note', text: how === 'cleared' ? 'The account’s owner started a new session here.' : 'The account’s owner resumed this session here.', data: { session: how, by: { type: 'account', id: null, name: 'owner' } }, created_at: at() });
    };
    const busy = () => [...operations.values()].some((o) => o.kind === 'agent.message' && o.status === 'running');
    const working = () => json({ error: { type: 'conflict', message: 'It is working on a turn now.' } }, 409);

    const routes = async (method: string, path: string, query: URLSearchParams, body: unknown, signal?: AbortSignal | null): Promise<Response> => {
        const base = `/v1/agents/${AGENT_ID}`;
        if (method === 'GET' && path === '/v1/agents') return json({ object: 'list', data: [agent, ...OTHER_AGENTS], next_cursor: null });
        if (method === 'GET' && path === '/v1/agents/states') return json({ object: 'list', data: options.states ?? [], read_at: at() });
        if (method === 'GET' && path === '/v1/channels') return json({ object: 'list', data: options.channels ?? [], next_cursor: null });
        if (method === 'GET' && path === '/v1/browsers') {
            const shown = (options.browsers ?? []).filter((b) => (!query.get('agent_id') || b.agent_id === query.get('agent_id')) && (!query.get('conversation') || b.conversation === query.get('conversation')));
            return json({ object: 'list', data: shown.slice(0, Number(query.get('limit') ?? 50)), next_cursor: null });
        }
        const viewed = liveViewRoutes(method, path, options.browsers ?? [], body);
        if (viewed) return viewed;
        // An agent it started, as GET /v1/agents/{id} reads it.
        const started = path.match(/^\/v1\/agents\/([^/]+)$/);
        if (started && method === 'GET' && started[1] in (options.taskCosts ?? {})) return json({ object: 'agent', id: started[1], name: started[1], harness: 'opencode', model: 'openai/gpt-5.6', user_id: null, status: 'idle', origin: 'api' });
        const sessionOf = path.match(/^\/v1\/agents\/([^/]+)\/conversations$/);
        if (sessionOf && method === 'GET' && sessionOf[1] in (options.taskCosts ?? {})) return json({ object: 'list', data: [{ object: 'conversation', conversation: 'task', active: true, people: [] }], next_cursor: null });
        const task = path.match(/^\/v1\/agents\/([^/]+)\/conversations\/task\/usage$/);
        if (task && method === 'GET' && task[1] !== AGENT_ID) {
            if (!(task[1] in (options.taskCosts ?? {}))) return notFound('No such conversation.');
            return json({ object: 'conversation_usage', agent_id: task[1], conversation: 'task', cost_usd: options.taskCosts![task[1]], model_usage: null, turns: 1, pays_with: 'noclick', plan_limits: [] });
        }
        // A request a person answers: an approval takes `approved`, as the owner's answer does.
        const asked = path.match(/^\/v1\/humans\/requests\/([^/]+)(\/answer)?$/);
        if (asked) {
            const found = humanRequests.get(decodeURIComponent(asked[1]));
            if (!found) return notFound('No human request with that id.');
            if (method === 'GET' && !asked[2]) return json(found);
            if (method === 'POST' && asked[2]) {
                if (found.status !== 'pending') return json({ error: { type: 'conflict', message: 'This request was already answered.' } }, 409);
                const { approved, note } = body as Json;
                Object.assign(found, { status: 'answered', answer: { approved, text: note ?? null, note: note ?? null } });
                return json(found);
            }
        }
        const profiles = path.match(/^\/v1\/connections\/([^/]+)\/chat_profiles$/);
        if (profiles && method === 'GET') {
            const kept = options.chatProfiles?.[decodeURIComponent(profiles[1])] ?? {};
            return json({ object: 'list', next_cursor: null, data: query.getAll('jid').map((jid) => ({ object: 'chat_profile', jid, name: null, avatar_url: null, ...kept[jid] })) });
        }
        const machineCall = machineRoutes({ machines, stock, id: () => `m-new-${++made}`, now: at }, method, path, query, (body ?? {}) as Json);
        if (machineCall) return machineCall;
        if (method === 'GET' && path === '/v1/machines') return json({ object: 'list', data: machines, agents_enabled: true, next_cursor: null });
        const machine = path.match(/^\/v1\/machines\/([^/]+)$/);
        if (machine && method === 'GET') return json(machines.find((m) => m.id === machine[1]) ?? {});
        const catalog = catalogRoutes(method, path, connections, options.checks, at, query);
        if (catalog) return catalog;
        const op = path.match(/^\/v1\/operations\/([^/]+)(\/wait|\/cancel)?$/);
        if (op) {
            const [, id, tail] = op;
            if (!operations.has(id)) return notFound(`No operation ${id}.`);
            if (tail === '/cancel' && method === 'POST') {
                settle(id, 'canceled');
                return json(operations.get(id));
            }
            if (tail === '/wait' && !TERMINAL.has(String(operations.get(id)!.status))) {
                await new Promise<void>((resolve) => {
                    waiting.set(id, [...(waiting.get(id) ?? []), resolve]);
                    signal?.addEventListener('abort', () => resolve());
                });
            }
            return json(operations.get(id));
        }
        if (!path.startsWith(base)) return notFound(`No route for ${method} ${path}`);
        const rest = path.slice(base.length);
        if (method === 'GET' && rest === '') return json(agent);
        if (method === 'PATCH' && rest === '') {
            const changes = body as Json;
            const refused = renameRefused([agent, ...OTHER_AGENTS], agent, changes) ?? options.refuseUpdate?.(changes);
            if (refused) return refused;
            Object.assign(agent, changes);
            // An agent is one session: its conversations run on its harness, model and account.
            if (['harness', 'model', 'model_connection'].some((k) => k in changes))
                for (const [c, s] of settings) settings.set(c, { ...s, harness: agent.harness, model: agent.model, model_connection: agent.model_connection ?? null });
            return json(agent);
        }
        if (method === 'GET' && rest === '/triggers') return json({ object: 'list', data: options.triggers ?? [], next_cursor: null });
        if (method === 'GET' && rest === '/tool_servers') return json({ object: 'list', data: toolServers, next_cursor: null });
        if (method === 'POST' && rest === '/tool_servers') {
            const b = body as Json;
            const url = String(b.url);
            if (options.signsIn?.includes(url) && !b.credential_id && !b.headers)
                return json({ error: { type: 'invalid_request', message: `${url} asks its client to sign in, and nothing was signed in to it.`, reason: 'needs_sign_in' } }, 400);
            const name = String(b.name ?? new URL(url).hostname.split('.').find((p) => !['mcp', 'api'].includes(p)));
            const server = { object: 'agent_tool_server', id: `mcp_${name}`, name, url, transport: b.transport ?? 'http', signed_in: !!b.credential_id, headers: Object.keys((b.headers as Json | undefined) ?? {}) };
            toolServers.push(server);
            return json(server, 201);
        }
        const server = rest.match(/^\/tool_servers\/([^/]+)$/);
        if (server && method === 'DELETE') {
            const at = toolServers.findIndex((s) => s.id === decodeURIComponent(server[1]));
            if (at < 0) return notFound(`No MCP server ${server[1]}.`);
            const [gone] = toolServers.splice(at, 1);
            return json({ ...gone, deleted: true });
        }
        if (method === 'GET' && rest === '/wakeups') return json({ object: 'list', data: [], next_cursor: null });
        if (method === 'POST' && rest === '/attachments') {
            const name = query.get('name') ?? 'file';
            return json({ object: 'attachment', id: `att-${++made}`, name, mime_type: query.get('mime_type') ?? 'application/octet-stream', size_bytes: 12, url: `https://files.test/${name}`, kind: 'file' }, 201);
        }
        if (method === 'GET' && rest === '/conversations') {
            const keys = new Set([...histories.keys(), ...settings.keys()]);
            return json({ object: 'list', data: [...extraConversations, ...[...keys].map(conversationView)], next_cursor: null });
        }
        if (method === 'POST' && rest === '/conversations') {
            if (busy()) return working();
            const key = String((body as Json).conversation ?? `c${++made}`);
            settings.set(key, settingsFor(key, { title: (body as Json).title ?? null }));
            moveTo(key, 'cleared');
            return json(conversationView(key), 201);
        }
        if (method === 'POST' && rest === '/messages') {
            const sent = body as Json;
            const c = String(sent.conversation ?? active);
            const id = `op-turn-${++made}`;
            // Turned down before any turn starts (the account ran out): the platform's 402, as its error says it.
            const refusal = options.turn?.(id, sent).refused;
            if (refusal) return json({ error: { type: 'payment_required', ...refusal } }, 402);
            const running = [...operations.values()].some((o) => o.kind === 'agent.message' && o.conversation === c && o.status === 'running');
            const queued = running && sent.delivery === 'queue';
            const operation = { object: 'operation', id, kind: 'agent.message', status: queued ? 'queued' : 'running', conversation: c, created_at: at(), updated_at: at() };
            operations.set(id, operation);
            if (queued) return json(operation, 202);
            const command = sent.command as Json | undefined;
            const text = command ? `/${command.name}${command.arguments ? ` ${command.arguments}` : ''}` : String(sent.text ?? '');
            const files = ((sent.attachments as string[] | undefined) ?? []).map((f) => ({ id: f, name: f, mime_type: 'application/pdf', url: `https://files.test/${f}`, kind: 'file' }));
            const user = { id: `m${++messageIds}`, role: 'user', text, created_at: at(), operation_id: id, author: { type: 'account', id: null, name: 'Rowan Hale' }, ...(command ? { command } : {}), ...(files.length ? { files } : {}) };
            historyOf(c).push(user);
            const script = options.turn?.(id, sent) ?? { reply: 'Done.' };
            setTimeout(() => {
                emit([{ type: 'message', ...user }], c);
                emit(script.events ?? [], c);
                if (script.hold) return;
                if (script.error) {
                    settle(id, 'failed', { error: { type: 'internal', message: script.error } });
                    return;
                }
                if (script.failure) {
                    // The platform marks a connection it refused, so every read shows it disconnected; one out of
                    // credit stays connected.
                    const refused = script.failure.reason === 'provider_out_of_funds' ? undefined : connections.find((x) => x.name === script.failure!.connection);
                    if (refused) Object.assign(refused, { status: 'disconnected', disconnected: { reason: script.failure.reason === 'signed_out' ? 'signed_out' : 'refused', message: `${refused.integration === 'openrouter' ? 'OpenRouter' : refused.integration} refused this key.`, since: at(), next_step: script.failure.next_step } });
                    const failed = { id: `m${++messageIds}`, role: 'assistant', text: TURN_FAILED_LINE, created_at: at(), operation_id: id, failed: true };
                    historyOf(c).push({ ...failed, failure: script.failure });
                    emit([{ type: 'message', ...failed }], c);
                    settle(id, 'failed', { error: script.failure });
                    return;
                }
                reply(id, script.reply ?? '', script.toolCalls ? { tool_calls: script.toolCalls } : {}, c);
            }, 0);
            return json(operation, 202);
        }
        const conv = rest.match(/^\/conversations\/([^/]+)(\/.*)?$/);
        if (!conv) return notFound(`No route for ${method} ${path}`);
        const c = decodeURIComponent(conv[1]);
        const tail = conv[2] ?? '';
        if (method === 'GET' && tail === '') return json({ object: 'conversation', id: c, agent_id: AGENT_ID, session: histories.has(c) ? c : active, messages: historyOf(c), next_cursor: null });
        if (method === 'POST' && tail === '/resume') {
            if (!histories.has(c)) return notFound(`No session ${c}.`);
            if (c !== active && busy()) return working();
            if (c !== active) moveTo(c, 'resumed');
            return json(conversationView(c));
        }
        if (method === 'PATCH' && tail === '') {
            const patch = body as Json;
            const s = settingsOf(c);
            const wire: Json = {};
            for (const [k, v] of Object.entries(patch)) wire[k === 'permissionMode' ? 'permission_mode' : k === 'modelConnection' ? 'model_connection' : k] = v;
            settings.set(c, { ...s, ...wire, ...(wire.permission_mode ? { effective_permission_mode: wire.permission_mode } : {}) });
            return json(settings.get(c));
        }
        // A message for one of its harness's subagents: it joins the turn under way (its agent.ask), and the thread
        // keeps it as yours, for that subagent; with no turn under way, its own turn.
        const toSubagent = tail.match(/^\/subagents\/([^/]+)\/messages$/);
        if (toSubagent && method === 'POST') {
            const callId = decodeURIComponent(toSubagent[1]);
            const live = [...operations.values()].find((o) => o.kind === 'agent.message' && o.conversation === c && o.status === 'running');
            const id = `op-${live ? 'ask' : 'turn'}-${++made}`;
            const operation = { object: 'operation', id, kind: live ? 'agent.ask' : 'agent.message', status: 'running', conversation: c, created_at: at(), updated_at: at() };
            operations.set(id, operation);
            const user = { id: `m${++messageIds}`, role: 'user', text: String((body as Json).text ?? ''), created_at: at(), operation_id: live ? live.id : id, author: { type: 'account', id: null, name: 'Rowan Hale' }, subagent: { id: callId, title: options.subagentTitles?.[callId] ?? 'A subagent' } };
            historyOf(c).push(user);
            setTimeout(() => emit([{ type: 'message', ...user }], c), 0);
            return json(operation, 202);
        }
        // A line in the thread that starts no turn (agent.note): kept, and said on its stream.
        if (method === 'POST' && tail === '/notes') {
            const note = { id: `m${++messageIds}`, role: 'note', text: String((body as Json).text ?? ''), data: (body as Json).data ?? null, created_at: at() };
            historyOf(c).push(note);
            setTimeout(() => emit([{ type: 'message', ...note }], c), 0);
            return json({ object: 'note', added: true, ...note }, 201);
        }
                if (method === 'GET' && tail === '/activity') return json({ object: 'list', data: (activity.get(c) ?? []).slice(0, Number(query.get('limit') ?? 50)) });
        if (method === 'GET' && tail === '/settings') return json(settingsOf(c));
        if (method === 'GET' && tail === '/commands') return json(COMMANDS);
        if (method === 'GET' && tail === '/context') return json({ object: 'conversation_context', used_tokens: 148_000, window_tokens: 200_000, percent: 74, model: 'claude-opus-5-5', auto_compacts_at: 0.8, as_of: at(), source: 'harness', ...options.context });
        if (method === 'GET' && tail === '/usage')
            return json({ object: 'conversation_usage', cost_usd: 0.42, model_usage: { input_tokens: 182_000, output_tokens: 9_400, cached_tokens: 120_000, usd: 0.42 }, turns: 3, pays_with: 'plan', plan_limits: [{ label: 'This session', used_percent: 38, resets_at: '2026-11-10T15:00:00Z' }], ...options.usage });
        if (method === 'GET' && tail === '/requests') {
            const status = query.get('status');
            return json({ object: 'list', data: [...asks.values()].filter((a) => !status || a.status === status) });
        }
        const answer = tail.match(/^\/requests\/([^/]+)$/);
        if (answer && method === 'POST') {
            const id = decodeURIComponent(answer[1]);
            const ask = asks.get(id);
            if (!ask) return notFound(`No request ${id}.`);
            const answered = { ...ask, status: 'answered', answer: { ...(body as Json), by: 'person' } };
            asks.set(id, answered);
            emit([{ type: 'request', request: answered, operation_id: ask.operation_id }], c);
            return json(answered);
        }
        if (method === 'POST' && tail === '/revert') {
            const { message, files } = body as Json;
            const h = historyOf(c);
            const at = h.findIndex((m) => m.id === message);
            const text = String(h[at]?.text ?? '');
            const dropped = h.slice(at).filter((m) => m.role === 'assistant').length;
            histories.set(c, h.slice(0, at));
            return json({ object: 'conversation_revert', conversation: c, message, text, dropped_turns: dropped, files: { restored: files ? ['app/retries/worker.py'] : [], kept: files ? [] : ['app/retries/worker.py'], not_restored: [], commands_not_undone: 0 }, files_applied: files ? 'next_turn' : null, agent_reads: 'native' });
        }
        if (method === 'GET' && tail === '/sandbox') return json({ agent_id: AGENT_ID, conversation: c, harness: 'claude_code', place: 'sandbox', status: 'running', started_at: new Date(Date.now() - 4 * 60_000).toISOString(), cpu: 4, memory_mb: 8192, ...options.sandbox });
        if (method === 'GET' && tail === '/sandbox/files') return json({ object: 'list', data: options.files ?? [], next_cursor: null, source: 'sandbox' });
        if (method === 'GET' && tail === '/events') {
            let mine: ReadableStreamDefaultController<Uint8Array>;
            const stream = new ReadableStream<Uint8Array>({
                start: (controller) => {
                    mine = controller;
                    if (query.get('replay') === '1') for (const event of streamed.get(c) ?? []) controller.enqueue(frame(event));
                    streams.set(controller, c);
                },
                cancel: () => {
                    streams.delete(mine);
                },
            });
            signal?.addEventListener('abort', () => {
                if (streams.delete(mine)) mine.close();
            });
            return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
        }
        return notFound(`No route for ${method} ${path}`);
    };

    const fetch: typeof window.fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = (init?.method ?? 'GET').toUpperCase();
        const raw = init?.body;
        const body = typeof raw === 'string' ? JSON.parse(raw) : raw;
        requests.push({ method, path: url.pathname, query: url.searchParams, body });
        return routes(method, url.pathname, url.searchParams, body, init?.signal);
    };

    return {
        client: workFixtureClient(fetch),
        fetch,
        requests,
        histories,
        asks,
        operations,
        settings,
        emit,
        drop: () => {
            for (const stream of streams.keys()) stream.close();
            streams.clear();
        },
        settle,
        reply,
        connections,
        toolServers,
        activity,
        humanRequests,
        machines,
        stock,
        watching: () => streams.size,
    };
}
