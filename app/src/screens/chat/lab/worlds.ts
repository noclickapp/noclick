// The made-up account a Chat lab scene runs on: the chat's fake /v1 (fixtures/coordinatorAgent) holding the scene's
// conversation, with the reads its views make answered from the fixtures their tests use: Work's catalog for the
// switchers under the box (fixtures/coordinatorSwitchers), what's at work beside the chat in eight moments
// (fixtures/atWorkScenarios), the agent team's agents and channel (fixtures/agentTeamThread), the account's automations
// and accounts the "+" menu lists, NoClick's lines and inbox the Connect menu reads. Answered as the API answers the
// account's signed-in owner, or (`key`) one of its keys: what only the owner may do is refused, as the API refuses it.
// A request nothing answers is named in a warning.
import { AGENT_ID, fakeCoordinatorAgent, type ExtraRoutes, type LiveEvent } from '../fixtures/coordinatorAgent';
import { AT_WORK_SCENARIOS, atWorkRoutes, type ScenarioId } from '../fixtures/atWorkScenarios';
import { ANTHROPIC_KEY, SWITCHING_AGENT, switcherRoutes } from '../fixtures/coordinatorSwitchers';
import { teamRead } from '../fixtures/agentTeamThread';
import { forAppsNote, forAppsRoutes, type AgentForAppsState } from '@/screens/work/fixtures/agentForApps';
import { settingsFor } from '@/screens/work/conversation/fixtures/workAgent';
import { makeFixtureFetch } from '@/screens/console/fixtures/fixtureFetch';
import { refusedToAccountKey, scopeFor } from '@/screens/console/ownerOnly';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import type { NoClick } from 'noclick';
import { createWorkLive, type WorkLive } from '@/sdk/live';

type Json = Record<string, unknown>;

/** What a scene's account holds. */
export interface ChatWorld {
    /** The conversation as history reads it back, and what its stream already keeps (a turn maybe still at work). */
    history?: Json[];
    streamed?: LiveEvent[];
    operations?: Json[];
    memories?: Json[];
    files?: Json[];
    /** What's at work beside the chat. */
    beside?: ScenarioId;
    /** The agents and channel the agent team's cards read. */
    team?: boolean;
    /** An agent an agents page made, its note in the thread: waiting on what it needs, or ready. */
    agentForApps?: AgentForAppsState;
    /** The account has no NoClick (its lookup finds none). */
    missing?: boolean;
    /** Reading which session it's in never answers (`hangs`), or is refused (`refused`). */
    session?: 'hangs' | 'refused';
    /** What /v1 answers a scene's card reads (a workflow's graph, an approval), by path. */
    reads?: Record<string, unknown>;
}

export interface ChatLabWorld {
    client: NoClick;
    /** Answers every request of the scene's views, through any client. */
    fetch: typeof window.fetch;
    live: WorkLive;
}

/** Told of each call the scene's views make, and handed its answer as it comes: a test's record of what the chat
 *  called. */
export type Observe = (method: string, path: string, answered: Promise<Response>) => void;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const SESSIONS = `/v1/agents/${encodeURIComponent('agent:coordinator')}/conversations`;

/** NoClick's own numbers and address, and a phone of the owner's not linked yet: what the Connect menu reads. */
export const REACH = { phone: '+14155550142', imessage: '+14155550199', email: 'maya@noclick.test', email_paused: false, email_from_anyone: false };

/** The Connect menu's reads of them on the API: NoClick's lines, and its inbox (its mail waking NoClick). */
const OWNER_REACH = { object: 'owner_reach', lines: [{ app: 'whatsapp', number: REACH.phone }, { app: 'imessage', number: REACH.imessage }], phone_linked: false };
const INBOX = { object: 'inbox', id: 'inb_noclick', name: 'coordinator', address: REACH.email, agent_id: AGENT_ID, senders: 'owner', conversation: 'owner', user_id: null, created_at: '2026-10-02T09:00:00Z' };

/** The account's own automations, as GET /v1/workflows lists them (nothing in them yet, so no marks). */
const WORKFLOWS = [
    { id: 'wf-orders', name: 'Bakery orders', description: 'Answers order texts and books pickups.', created_at: '2026-10-02T09:00:00Z', updated_at: '2026-11-11T16:20:00Z', folder_id: null },
    { id: 'wf-digest', name: 'Morning brief', description: 'A WhatsApp brief at 8.', created_at: '2026-09-14T09:00:00Z', updated_at: '2026-11-09T08:00:00Z', folder_id: null },
    { id: 'wf-support', name: 'Support inbox', description: 'Answers the support inbox.', created_at: '2026-08-21T09:00:00Z', updated_at: '2026-10-30T12:00:00Z', folder_id: null },
];
/** Its accounts connected in the app. */
export const CREDENTIALS = [
    { id: 'cred-gmail', name: 'Gmail', credential_type: 'gmail_oauth', created_at: '2026-10-01T09:00:00Z', metadata: { email: 'maya@morrowbakery.test' } },
    { id: 'cred-slack', name: 'Slack', credential_type: 'slack_oauth', created_at: '2026-09-20T09:00:00Z', metadata: { team_name: 'Morrow Bakery' } },
    { id: 'cred-sheets', name: 'Google Sheets', credential_type: 'google_sheets_oauth', created_at: '2026-09-02T09:00:00Z', metadata: { email: 'maya@morrowbakery.test' } },
    { id: 'cred-github', name: 'GitHub', credential_type: 'github_oauth', created_at: '2026-08-14T09:00:00Z', metadata: { login: 'morrowbakery' } },
    { id: 'cred-notion', name: 'Notion', credential_type: 'notion_oauth', created_at: '2026-07-30T09:00:00Z', metadata: { workspace_name: 'Morrow Bakery' } },
];

/** Those accounts as GET /v1/connections lists them, its account named as it reaches it, beside the Anthropic key the
 *  switchers run on: every account the "+" menu can point at. */
const CONNECTIONS = [
    ...CREDENTIALS.map((c): Json => ({
        object: 'connection',
        id: `credential:${c.id}`,
        name: c.name,
        integration: c.credential_type.replace(/_oauth$/, ''),
        credential_type: c.credential_type,
        status: 'connected',
        connected: true,
        origin: 'app',
        access: 'owner',
        account: c.metadata.login ?? c.metadata.email ?? null,
        created_at: c.created_at,
        connected_at: c.created_at,
    })),
    ANTHROPIC_KEY,
];

const EMPTY = { object: 'list', data: [], next_cursor: null };
const OWNER = `/v1/agents/${AGENT_ID}/conversations/owner`;

/** What the page reads of NoClick's session beyond its conversation, as the API answers for NoClick on its own runtime:
 *  its settings (the agent's own harness, model and account), no sandbox, no browser, no loops; and, with nothing at
 *  work beside the chat, no coding agents and nothing held for the owner. */
function session(agent: () => Json): ExtraRoutes {
    return (method, path) => {
        if (method !== 'GET') return undefined;
        if (path === `${OWNER}/settings`) {
            const { harness, model, effort, model_connection } = agent();
            return json(settingsFor('owner', { harness, model, effort, model_connection, accounts: [] }));
        }
        if (path === `${OWNER}/sandbox`) return json({ error: { type: 'not_found', message: 'This conversation has no sandbox.' } }, 404);
        if (path === '/v1/browsers' || path === `/v1/agents/${AGENT_ID}/wakeups` || path === '/v1/approvals') return json(EMPTY);
        if (path === '/v1/agents/coding') return json({ object: 'list', data: [], read_at: new Date().toISOString() });
        if (path === '/v1/workflows') return json({ object: 'list', data: WORKFLOWS.map((w) => ({ object: 'workflow', ...w, step_types: [] })), next_cursor: null });
        if (path === '/v1/humans/owner/reach') return json(OWNER_REACH);
        if (path === '/v1/inboxes') return json({ object: 'list', data: [INBOX], next_cursor: null });
        return undefined;
    };
}

const HELPER_PART = /^\/v1\/agents\/([^/]+)\/conversations\/([^/]+)\/(settings|requests|commands)$/;
const LIVE = /^\/v1\/projects\/([^/]+)\/live$/;

/** What a helper's session beside the chat reads that its scenario leaves out, as the API answers an agent on a coding
 *  harness: its settings (the harness and model the coding listing names), nothing asked of anyone, its harness's
 *  commands none; and an app nobody is editing live has no live session. */
function helpers(world: ChatWorld): ExtraRoutes {
    const coding = (world.beside ? AT_WORK_SCENARIOS[world.beside].coding : []) as { agent_id?: string; harness?: string; model?: string }[];
    return (method, path) => {
        if (method !== 'GET') return undefined;
        const live = LIVE.exec(path);
        if (live) return json({ object: 'live', project_id: live[1], session: null });
        const [, agentId, conversation, part] = HELPER_PART.exec(path) ?? [];
        if (!part) return undefined;
        const coder = coding.find((c) => c.agent_id === agentId);
        if (part === 'settings') return json(settingsFor(decodeURIComponent(conversation), { harness: coder?.harness ?? 'claude_code', model: coder?.model ?? null, model_connection: null, accounts: [] }));
        if (part === 'requests') return json({ object: 'list', data: [] });
        return json({ harness: coder?.harness ?? 'claude_code', commands: [] });
    };
}

/** The account's fixtures in order, the first with an answer answering; a route none of them has is warned of. */
function routesOf(world: ChatWorld, agent: () => Json): ExtraRoutes {
    const scenario = world.beside ? AT_WORK_SCENARIOS[world.beside] : null;
    const order: ExtraRoutes[] = [
        (method, path) => {
            if (method !== 'GET' || path !== SESSIONS) return undefined;
            if (world.session === 'hangs') return new Promise<Response>(() => undefined);
            if (world.session === 'refused') return json({ error: { type: 'permission_denied', message: 'This key can’t read that conversation.' } }, 403);
            return undefined;
        },
        (method, path) => (method === 'GET' && world.reads && path in world.reads ? json(world.reads[path]) : undefined),
        ...(scenario ? [atWorkRoutes(scenario)] : []),
        ...(world.agentForApps ? [forAppsRoutes(world.agentForApps) satisfies ExtraRoutes] : []),
        ...(world.team
            ? [
                  ((method, path) => {
                      if (method !== 'GET') return undefined;
                      const read = teamRead(path);
                      return read === undefined ? undefined : json(read);
                  }) satisfies ExtraRoutes,
              ]
            : []),
        switcherRoutes({ agent, connections: CONNECTIONS }),
        session(agent),
        helpers(world),
    ];
    return (...request) => {
        for (const route of order) {
            const answer = route(...request);
            if (answer) return answer;
        }
        return undefined;
    };
}

/** What the API answers a key for an operation only the account's signed-in owner may make. */
const refusedToKey = (method: string, path: string) => {
    const scope = scopeFor(method, path);
    const message = scope ? `This key hasn’t the ${scope} scope, which ${method} ${path} needs.` : `A key can't call ${method} ${path}: only the account's owner, signed in, can.`;
    return Response.json({ error: { type: 'permission_denied', message } }, { status: 403 });
};

/** A fixture's answer to a call it has no route for (the console's fixtures say "No fixture for"). */
async function unrouted(response: Response): Promise<boolean> {
    if (response.status !== 404) return false;
    const body = (await response.clone().json().catch(() => null)) as { error?: { message?: unknown } } | null;
    return /^No (route|fixture) for /.test(String(body?.error?.message ?? ''));
}

/** The made-up account for a scene, answered as its signed-in owner, or (`key`) one of its keys; `observe` is told of
 *  every call. */
export function chatWorld(world: ChatWorld, actsAs: 'owner' | 'key' = 'owner', observe?: Observe): ChatLabWorld {
    const scenario = world.beside ? AT_WORK_SCENARIOS[world.beside] : null;
    let agent: Json = {};
    const fake = fakeCoordinatorAgent({
        exists: !world.missing,
        agent: SWITCHING_AGENT,
        history: world.history ?? scenario?.history ?? (world.agentForApps ? [forAppsNote()] : undefined),
        streamed: world.streamed,
        operations: [...(world.operations ?? []), ...(scenario?.operations ?? [])],
        memories: world.memories,
        files: world.files,
        routes: routesOf(world, () => agent),
        // A turn sent in a scene is still at work when the shot is taken.
        turn: () => ({ hold: true }),
    });
    agent = fake.agent;
    // The account itself (GET /v1/account), as the console's fixtures have it.
    const account = makeFixtureFetch({ set: 'populated', actsAs });
    const answer = async (input: Parameters<typeof window.fetch>[0], init?: RequestInit): Promise<Response> => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = init?.method ?? 'GET';
        if (actsAs === 'key' && refusedToAccountKey(method, url.pathname)) return refusedToKey(method, url.pathname);
        const answer = await fake.fetch(input, init);
        if (!(await unrouted(answer))) return answer;
        const theirs = await account(input, init);
        if (!(await unrouted(theirs))) return theirs;
        console.warn(`[chat-lab] ${method} ${url.pathname}${url.search}: no fixture has a route for it.`);
        return answer;
    };
    const fetch: typeof window.fetch = (input, init) => {
        const answered = answer(input, init);
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        observe?.(init?.method ?? 'GET', url.pathname, answered);
        return answered;
    };
    return { client: workFixtureClient(fetch), fetch, live: createWorkLive() };
}
