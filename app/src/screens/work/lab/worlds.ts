// The made-up account a lab scene runs on, put together from Work's fixtures, each the one its views' tests use: the
// spaces, their channels, people and DMs (fixtures/workApi), five agents caught at different moments with their
// triggers, tools, files and machines and the account's connections, skills, memories and secrets
// (agents/fixtures/workAgents), and an agent's session mid-turn (conversation/fixtures/workAgent). A scene's world
// says which of them its agents come from: what concerns agents is asked of that fixture first, everything else of
// the spaces'. A request goes to the next one only where a fixture has no route for it; then to the few answers the
// lab adds for what the agents' fixture leaves out of a session, and last to the console's fixtures (the account
// itself). One that nothing answers is named in a warning.
import { workFixtureClient } from '../fixtures/client';
import { DEFAULT_BASE_URL, type NoClick } from 'noclick';
import { makeFixtureFetch } from '@/screens/console/fixtures/fixtureFetch';
import { refusedToAccountKey, scopeFor } from '@/screens/console/ownerOnly';
import type { WorkLive } from '@/sdk/live';
import { fakeWork } from '../fixtures/workApi';
import { fakeWork as fakeWorkAgents } from '../agents/fixtures/workAgents';
import { AGENT_ID, catalogRoutes, COMMANDS, fakeWorkAgent, settingsFor } from '../conversation/fixtures/workAgent';
import { busyHistory, busyLive, liveOperation } from '../conversation/fixtures/scenes';
import { ROBLOX_CHANNEL, forAppsRoutes, type AgentForAppsState } from '../fixtures/agentForApps';

/** Where a scene's agents come from: the spaces' own three (`spaces`), five at work (`agents`), one mid-turn
 *  (`session`), or the spaces' with the agent an agents page made in its channel of your own (`agent_for_apps`, waiting on
 *  what it needs; `agent_for_apps_ready`, saying hello). */
export type LabWorld = 'spaces' | 'agents' | 'session' | 'agent_for_apps' | 'agent_for_apps_ready';

export interface Lab {
    client: NoClick;
    /** Answers every request of the scene's views, through any client (a joined space's session's too). */
    fetch: typeof window.fetch;
    live: WorkLive;
}

type Fetch = typeof window.fetch;
type Json = Record<string, unknown>;

/** The calls that concern an account's agents and what they work with: asked of the scene's agent fixture first. */
const AGENT_PATHS = /^\/v1\/(agents|harnesses|connections|integrations|account|secrets|skills|memories|machines|compute|browsers|operations|humans|usage|inboxes)(\/|$)/;

/** A fixture's answer to a call it has no route for (the console's fixtures say "No fixture for"). */
async function unrouted(response: Response): Promise<boolean> {
    if (response.status !== 404) return false;
    const body = (await response.clone().json().catch(() => null)) as { error?: { message?: unknown } } | null;
    return /^No (route|fixture) for /.test(String(body?.error?.message ?? ''));
}

const CONVERSATION_PART = /^\/v1\/agents\/([^/]+)\/conversations\/([^/]+)\/(settings|commands|requests|events)$/;

/** What the agents' fixture leaves out of an agent's session, as its conversation's fixture has it for its one agent:
 *  the session's settings (on the agent's own harness, model and account), its harness's commands, nothing waiting on
 *  you, no browser, a live stream with nothing on it, and its account's plan usage and check. */
function sessionParts(agents: ReturnType<typeof fakeWorkAgents>): Fetch {
    return async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = init?.method ?? 'GET';
        const get = method === 'GET';
        const [, agentId, conversation, part] = (get && CONVERSATION_PART.exec(url.pathname)) || [];
        const listed = (await (await agents.fetch(`${DEFAULT_BASE_URL}/v1/connections`)).json()) as { data: Json[] };
        if (part === 'settings') {
            const agent = agents.agents.find((a) => a.id === agentId);
            const account = listed.data.find((c) => c.name === agent?.model_connection);
            const plan = String(account?.credential_type ?? '').endsWith('_oauth');
            return Response.json(
                settingsFor(decodeURIComponent(conversation), {
                    harness: agent?.harness,
                    model: agent?.model,
                    model_connection: account?.name ?? null,
                    accounts: account ? [{ name: account.name, integration: account.integration, kind: plan ? 'plan' : 'key', usable: true, why: null }] : [],
                })
            );
        }
        if (part === 'commands') return Response.json(COMMANDS);
        if (part === 'requests' || (get && url.pathname === '/v1/browsers')) return Response.json({ object: 'list', data: [], next_cursor: null });
        if (part === 'events') return new Response(new ReadableStream({ start: (stream) => init?.signal?.addEventListener('abort', () => stream.close()) }), { headers: { 'Content-Type': 'text/event-stream' } });
        const account = url.pathname.startsWith('/v1/connections/') ? catalogRoutes(method, url.pathname, listed.data, undefined, () => new Date().toISOString(), url.searchParams) : undefined;
        return account ?? Response.json({ error: { type: 'not_found', message: `No route for ${method} ${url.pathname}` } }, { status: 404 });
    };
}

/** Answers from the first in `order` with a route for the call. */
async function first(order: Fetch[], input: Parameters<Fetch>[0], init: Parameters<Fetch>[1]): Promise<Response> {
    let last: Response | null = null;
    for (const answer of order) {
        last = await answer(input, init);
        if (!(await unrouted(last))) return last;
    }
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
    console.warn(`[work-lab] ${init?.method ?? 'GET'} ${url.pathname}${url.search}: no fixture has a route for it.`);
    return last!;
}

/** The `session` world's agent: mid-turn on the fix it found this morning (a subagent of its harness's went through
 *  the migrations for it), its edits and its test run streaming. */
function agentMidTurn() {
    const history = busyHistory();
    const finding = history.find((m) => m.id === 'm4')!;
    finding.tool_calls = [
        ...(finding.tool_calls as Json[]),
        { id: 'sub-1', source: 'harness', kind: 'tool', tool: 'Task', arguments: { description: 'Find what changed max_attempts since Friday' }, result: 'Migration 0042 set max_attempts to 1 for every dashboard connection.', created_at: finding.created_at },
        { id: 'sub-1a', parent: 'sub-1', source: 'harness', kind: 'search', tool: 'search', query: 'max_attempts', created_at: finding.created_at },
        { id: 'sub-1b', parent: 'sub-1', source: 'harness', kind: 'read', tool: 'read', path: 'migrations/0042_connection_defaults.py', created_at: finding.created_at },
    ];
    const now = new Date().toISOString();
    const idle = { now: null, waiting: { asks: 0, held_calls: 0, requests: 0, total: 0 }, turn_started_at: null, last_active_at: now, failed: null, waking: null, noclick: false, conversation: null };
    const fake = fakeWorkAgent({
        histories: { main: history },
        operations: [liveOperation()],
        states: [
            { ...idle, agent_id: AGENT_ID, name: 'Wirefern', harness: 'claude_code', state: 'working', conversation: 'main', turn_started_at: now, now: { tool: 'shell', kind: 'command', line: 'pytest tests/ -k retries -q', since: now } },
            { ...idle, agent_id: 'a-support', name: 'Support', harness: 'sdk', state: 'idle' },
            { ...idle, agent_id: 'a-growth', name: 'Growth', harness: 'claude_code', state: 'idle' },
        ],
    });
    fake.emit(busyLive());
    return fake;
}

/** The agent an agents page made, over the spaces': its channel among yours (in no space), it, the account's
 *  connections and the harnesses as forAppsRoutes answers them. */
function forAppsLayer(state: AgentForAppsState, spaces: Fetch): Fetch {
    const routes = forAppsRoutes(state);
    return async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = init?.method ?? 'GET';
        if (method === 'GET' && url.pathname === '/v1/channels' && !url.searchParams.get('workspace_id') && !url.searchParams.get('agent_id')) {
            const base = (await (await spaces(input, init)).json()) as { data: Json[] };
            return Response.json({ object: 'list', data: [...base.data, ROBLOX_CHANNEL], next_cursor: null });
        }
        return routes(method, url.pathname, url.searchParams) ?? Response.json({ error: { type: 'not_found', message: `No route for ${method} ${url.pathname}` } }, { status: 404 });
    };
}

/** Told of each call the scene's views make, and handed its answer as it comes: a test's record of what Work called. */
export type Observe = (method: string, path: string, answered: Promise<Response>) => void;

/** What the API answers a key for an operation only the account's signed-in owner may make. */
const refusedToKey = (method: string, path: string) => {
    const scope = scopeFor(method, path);
    const message = scope ? `This key hasn’t the ${scope} scope, which ${method} ${path} needs.` : `A key can't call ${method} ${path}: only the account's owner, signed in, can.`;
    return Response.json({ error: { type: 'permission_denied', message } }, { status: 403 });
};

/** The made-up account for a scene, answered as the API answers its signed-in owner, or (`key`) one of its keys: the
 *  operations only the owner may make are refused (screens/console/ownerOnly.ts), as the API refuses them. */
export function labWorld(world: LabWorld, actsAs: 'owner' | 'key' = 'owner', observe?: Observe): Lab {
    const spaces = fakeWork();
    const agents = fakeWorkAgents({ coordinator: true, now: Date.now() });
    const session = world === 'session' ? agentMidTurn() : null;
    const parts = sessionParts(agents);
    const account = makeFixtureFetch({ set: 'populated', actsAs });
    const appState: AgentForAppsState | null = world === 'agent_for_apps' ? 'waiting' : world === 'agent_for_apps_ready' ? 'ready' : null;
    const owner: Fetch | null = world === 'agents' ? agents.fetch : (session?.fetch ?? null);
    const answer: Fetch = (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        // An agent's channels are the agent fixture's; a space's are the spaces'.
        const ownsIt = owner && (AGENT_PATHS.test(url.pathname) || (url.pathname === '/v1/channels' && url.searchParams.has('agent_id')));
        const method = init?.method ?? 'GET';
        if (actsAs === 'key' && refusedToAccountKey(method, url.pathname)) return Promise.resolve(refusedToKey(method, url.pathname));
        const fixtures = ownsIt ? [owner, spaces.fetch, agents.fetch] : [spaces.fetch, ...(owner ? [owner] : []), agents.fetch];
        return first([...(appState ? [forAppsLayer(appState, spaces.fetch)] : []), ...new Set(fixtures), parts, account], input, init);
    };
    const fetch: Fetch = (input, init) => {
        const answered = answer(input, init);
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        observe?.(init?.method ?? 'GET', url.pathname, answered);
        return answered;
    };
    return {
        client: workFixtureClient(fetch),
        fetch,
        live: spaces.live,
    };
}
