// What the tab of what's at work reads in eight moments of one account, each written as /v1 answers it: the
// coordinator's conversation (its replies' calls as history saves them, results cut at 500 characters), the
// operations those calls started (GET /v1/operations/{id}), the coding agents listing (GET /v1/agents/coding), the
// account's apps (GET /v1/projects), each live session and its edits, the agents behind a build's tasks and their
// task conversations, and the purchases held for the owner (GET /v1/approvals). The coordinator itself runs on Claude
// Code here, so the coding listing names it too, as it does for such an account. Times are relative to when the module
// loaded, so the clocks run.
import type { ExtraRoutes } from './coordinatorAgent';

type Json = Record<string, unknown>;

export const SCENARIO_IDS = ['none', 'one', 'sandbox', 'three', 'waiting', 'cap', 'failed', 'busy'] as const;
export type ScenarioId = (typeof SCENARIO_IDS)[number];

export interface AtWorkScenario {
    id: ScenarioId;
    title: string;
    history: Json[];
    operations: Json[];
    coding: Json[];
    projects: Json[];
    agents: Json[];
    approvals: Json[];
    /** By app: GET .../live, and every edit of its session so far. */
    live: Record<string, { state: Json; edits: Json[] }>;
    /** By agent: its task conversation. */
    conversations: Record<string, Json[]>;
}

const NOW = Date.now();
const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

// ── The account's apps ──────────────────────────────────────────────────────

const LARKSPUR = { id: '6b1f0c2e-4c1a-4b8e-9a51-2f7d3c8e1a01', name: 'larkspur', title: 'Larkspur', host: 'larkspur.noclick.test', repo: 'c0a7d3f1-5e2b-4f61-8d09-77a1b2c3d4e5' };
const MORROW = { id: '9d4e7a10-2b3c-4d5e-8f60-1a2b3c4d5e6f', name: 'morrow-bakehouse', title: 'Morrow Bakehouse', host: 'morrow-bakehouse.noclick.test', repo: 'e4f5a6b7-c8d9-4e0f-9a1b-2c3d4e5f6a7b' };
const COORDINATOR_ID = '8d6f1d3a-0c4e-4d55-9a5b-1f6f2c7b9e01';
const SUPPORT_INBOX = '4b5c6d7e-8f9a-4b0c-9d1e-2f3a4b5c6d7e';

function project(app: typeof LARKSPUR, deployed: boolean): Json {
    return {
        object: 'project',
        id: app.id,
        name: app.name,
        title: app.title,
        url: `https://${app.host}`,
        hostname: app.host,
        repo_id: app.repo,
        live_editing: true,
        production: deployed ? { object: 'deployment', id: `${app.id.slice(0, 8)}-d000-4000-8000-000000000001`, url: `https://${app.host}`, status: 'ready' } : null,
    };
}

const BOTH = [project(LARKSPUR, true), project(MORROW, true)];
const BUILDING = [project(LARKSPUR, true), project(MORROW, false)];

const NO_USAGE = { input_tokens: 0, output_tokens: 0, cached_tokens: 0, usd: 0 };
const NOCLICK_KEY = { kind: 'noclick', connection: null, credential_type: null };

function coding(fields: Json): Json {
    return { object: 'coding_agent', user_id: null, app: null, paused: null, pauses: [], job: null, runs: [], spent_usd_this_month: 0, model_usage_this_month: NO_USAGE, ...fields };
}

// Larkspur's coding agent: Codex on GPT-Luna on NoClick's key, editing the live site.
const LARKSPUR_CODER = {
    agent_id: '3a9b8c7d-6e5f-4a3b-9c2d-1e0f9a8b7c6d',
    name: 'larkspur-coder',
    harness: 'codex',
    model: 'gpt-6-luna',
    credential: NOCLICK_KEY,
    app: { project_id: LARKSPUR.id, name: LARKSPUR.name, title: LARKSPUR.title, coder: true },
};

// Morrow Bakehouse's: Claude Code on the person's Claude plan, in a sandbox of its own.
const MORROW_CODER = {
    agent_id: '7c6d5e4f-3a2b-4c1d-8e9f-0a1b2c3d4e5f',
    name: 'morrow-bakehouse-coder',
    harness: 'claude_code',
    model: 'sonnet',
    credential: { kind: 'plan', connection: 'claude', credential_type: 'agent_claude_code_oauth', connected: true },
    app: { project_id: MORROW.id, name: MORROW.name, title: MORROW.title, coder: true },
};

/** The coordinator itself, on Claude Code: the coding listing names it beside the account's other coding agents. */
export function ownCoding(state: 'warm' | 'working'): Json {
    const working = state === 'working';
    return coding({
        agent_id: COORDINATOR_ID,
        name: 'coordinator',
        harness: 'claude_code',
        model: 'opus',
        credential: { kind: 'plan', connection: 'claude', credential_type: 'agent_claude_code_oauth', connected: true },
        place: 'sandbox',
        state,
        job: working ? { operation_id: 'c0c0c0c0-1d2e-4f3a-8b4c-5d6e7f8a9b0c', conversation: 'owner', status: 'running', step: 'working', since: ago(0.3), title: null, text: 'What’s going on with my sites?' } : null,
        runs: [{ conversation: 'owner', place: 'sandbox', since: ago(9), busy: working }],
        spent_usd_this_month: 3.4,
    });
}

/** An agent of the account's own (no app, not a child), on OpenCode: warm between its tickets, or on one. */
export function supportInbox(state: 'warm' | 'working'): Json {
    const working = state === 'working';
    return coding({
        agent_id: SUPPORT_INBOX,
        name: 'support-inbox',
        harness: 'opencode',
        model: 'openrouter/~openai/gpt-luna-latest',
        credential: NOCLICK_KEY,
        place: 'sandbox',
        state,
        job: working ? { operation_id: 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d', conversation: 'ticket-2292', status: 'running', step: 'working', since: ago(0.8), title: 'Refund for order 1182', text: 'Refund order 1182: the box arrived crushed.' } : null,
        runs: [{ conversation: working ? 'ticket-2292' : 'ticket-2291', place: 'sandbox', since: ago(4), busy: working }],
        spent_usd_this_month: 2.18,
    });
}

// ── An app's live session ───────────────────────────────────────────────────

const SESSION_ID = '0e1d2c3b-4a59-4687-b7a6-958473625140';
const HEAD = '8c41f2e09ab3d7c6e5f4a3b2c1d0e9f8a7b6c5d4';

const EDITED = ['src/components/MenuPhoto.astro', 'scripts/resize-photos.mjs', 'src/pages/menu.astro', 'src/data/hours.ts', 'src/components/Footer.astro', 'src/styles/footer.css'];
const OUTCOMES = ['hot', 'none', 'hot', 'hot', 'hot', 'hot'];

function liveLarkspur(): { state: Json; edits: Json[] } {
    const edits = EDITED.map((file, i) => ({ seq: i + 1, boot: 'b7', at: NOW - (EDITED.length - i) * 20_000, files: [file], outcome: OUTCOMES[i], clients: 0 }));
    return {
        state: {
            object: 'live',
            project_id: LARKSPUR.id,
            enabled: true,
            supported: true,
            session: {
                object: 'live_session',
                id: SESSION_ID,
                project_id: LARKSPUR.id,
                state: 'live',
                git: { branch: 'noclick-live', head: HEAD, pushed: HEAD, dirty: true, state: 'clean', conflict: [] },
                edits: { count: edits.length, hot: 5, reload: 0, error: 0, none: 1, last_seq: edits.length },
                started_at: ago(3.2),
                live_at: ago(3.1),
            },
            attached: [{ agent_id: LARKSPUR_CODER.agent_id, conversation: 'code' }],
        },
        edits,
    };
}

// ── The thread's parts ──────────────────────────────────────────────────────

const you = (text: string, minutes: number): Json => ({ role: 'user', text, created_at: ago(minutes) });

/** A reply, its calls as history saves them (each result cut at 500 characters). */
function noclick(text: string, minutes: number, calls: Json[] = []): Json {
    return { role: 'assistant', text, created_at: ago(minutes), ...(calls.length ? { tool_calls: calls } : {}) };
}

function call(operation: string, args: Json, result: Json, minutes: number): Json {
    return { tool: 'noclick__api_call', arguments: { operation, arguments: args }, result: JSON.stringify(result).slice(0, 500), is_error: false, created_at: ago(minutes) };
}

// What the coordinator's instructions name a coding job by, and the whole of what it handed over.
const MENU_TITLE = 'Faster menu page';
const MENU_ASK = 'Speed up the menu page on phones: it loads all 38 photos at full size. Then put the opening hours (Mon to Sat 9 to 6, Sunday closed) in the footer on every page.';

/** A change handed to an app's coding agent, as the hand-off answered (coder._view). */
function handOff(operationId: string, coder: typeof LARKSPUR_CODER | typeof MORROW_CODER, title: string, text: string, minutes: number): Json {
    const live = coder === LARKSPUR_CODER;
    const app = live ? LARKSPUR : MORROW;
    return call(
        'projects_live_changes_create',
        { project_id: `app:${app.name}`, title, text },
        {
            success: true,
            response: {
                object: 'coding_job',
                operation_id: operationId,
                status: 'queued',
                joined: false,
                switching: false,
                agent_id: coder.agent_id,
                agent: coder.name,
                conversation: 'code',
                harness: coder.harness,
                model: coder.model,
                credential: live ? 'noclick' : 'plan',
                why: live ? 'no model key of the account’s: NoClick’s own key, charged at its cost' : 'the account’s Claude plan: Claude Code, in its own sandbox',
                place: live ? 'live' : 'sandbox',
                url: `https://${app.host}`,
                branch: live ? 'noclick-live' : 'noclick-code',
                ...(live ? { enter_url: `https://${app.host}/__noclick/live/4Hk9xQ2mRt7Lp0Vb3Nc8Zw` } : {}),
            },
        },
        minutes
    );
}

/** An operation as GET /v1/operations/{id} answers it (the owner reads its summary). */
function operation(id: string, kind: string, minutes: number, fields: Json): Json {
    return {
        object: 'operation',
        id,
        kind,
        status: 'running',
        step: 'working',
        result: null,
        error: null,
        created_at: ago(minutes),
        updated_at: ago(0.2),
        user_id: null,
        key_id: null,
        agent_id: null,
        started_at: ago(minutes),
        finished_at: null,
        progress: null,
        events: [],
        ...fields,
    };
}

function turn(id: string, agentId: string, minutes: number, title: string, text: string, fields: Json = {}): Json {
    return operation(id, 'agent.message', minutes, { agent_id: agentId, conversation: 'code', title, summary: text.slice(0, 119), ...fields });
}

// ── A build's children (agents_children_create: one agent.task each) ────────

const CHILD = {
    pages: { id: 'b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e', job: 'd1e2f3a4-b5c6-4d7e-8f9a-0b1c2d3e4f5a', name: 'morrow-pages', title: 'Write the pages', task: 'Write the site’s pages: home, order and visit, from BRIEF.md, in the warm, plain voice it describes. Commit to noclick-code.' },
    menu: { id: 'c2d3e4f5-a6b7-4c8d-9e0f-1a2b3c4d5e6f', job: 'e2f3a4b5-c6d7-4e8f-9a0b-1c2d3e4f5a6b', name: 'morrow-menu', title: 'Menu from the PDF', task: 'Turn the menu PDF into the menu page: every item, its price and its allergens, in src/data/menu.json. Mark anything you can’t read.' },
    photos: { id: 'd3e4f5a6-b7c8-4d9e-8f0a-2b3c4d5e6f7a', job: 'f3a4b5c6-d7e8-4f9a-8b1c-2d3e4f5a6b7c', name: 'morrow-photos', title: 'Prepare the photos', task: 'Prepare the photos: crop the 14 the owner sent for where BRIEF.md puts them, even out the light, and save web sizes to public/photos.' },
};
type Child = typeof CHILD.pages;

function childAgent(c: Child, harness: string, model: string): Json {
    return {
        object: 'agent',
        id: c.id,
        name: c.name,
        model,
        harness,
        parent_id: COORDINATOR_ID,
        status: 'active',
        repos: [{ repo_id: MORROW.repo, branch: 'main', push: ['noclick-code'] }],
    };
}

const CHILD_AGENTS = [childAgent(CHILD.pages, 'claude_code', 'sonnet'), childAgent(CHILD.menu, 'claude_code', 'sonnet'), childAgent(CHILD.photos, 'sdk', 'openai/gpt-6-luna')];

function spawned(c: Child, minutes: number): Json {
    return call(
        'agents_children_create',
        { agent_id: 'agent:coordinator', task: c.task, title: c.title, conversation: 'owner' },
        { success: true, operation_id: c.job, status: 'queued', response: { object: 'agent', id: c.id, name: c.name, parent_id: COORDINATOR_ID, job_id: c.job, job: { object: 'operation', id: c.job, kind: 'agent.task', status: 'queued' } } },
        minutes
    );
}

function update(c: Child, kind: string, text: string, minutes: number, waitingOn: Json | null = null): Json {
    return { object: 'job_update', id: `${c.job.slice(0, 8)}-u${Math.round(minutes * 10)}`, job_id: c.job, agent_id: c.id, kind, text, waiting_on: waitingOn, created_at: ago(minutes) };
}

function task(c: Child, minutes: number, fields: Json): Json {
    return operation(c.job, 'agent.task', minutes, { agent_id: c.id, started_by: COORDINATOR_ID, conversation: 'task', parent_conversation: 'owner', updates: ['done', 'blocked'], title: c.title, summary: c.task.slice(0, 119), latest_update: null, ...fields });
}

const KEY = { kind: 'key', connection: 'anthropic', credential_type: 'agent_anthropic', connected: true };

function childCoding(c: Child, minutes: number, state = 'working'): Json {
    const working = state === 'working';
    return coding({
        agent_id: c.id,
        name: c.name,
        harness: 'claude_code',
        model: 'sonnet',
        credential: KEY,
        place: 'sandbox',
        state,
        job: working ? { operation_id: `${c.job.slice(0, 24)}aaaaaaaaaaaa`, conversation: 'task', status: 'running', step: 'working', since: ago(minutes), title: c.title, text: c.task } : null,
        runs: state === 'stopped' ? [] : [{ conversation: 'task', place: 'sandbox', since: ago(minutes), busy: working }],
        model_usage_this_month: { input_tokens: 412_000, output_tokens: 38_500, cached_tokens: 301_000, usd: 1.12 },
    });
}

// Each child's task conversation: its finished turns' steps, as history keeps them.
const harnessStep = (tool: string, args: Json, minutes: number, result: string | null = null) => ({ tool, arguments: args, result, is_error: false, created_at: ago(minutes), source: 'harness' });
const CONVERSATIONS: Record<string, Json[]> = {
    [CHILD.pages.id]: [
        { role: 'user', text: CHILD.pages.task, created_at: ago(12) },
        {
            role: 'assistant',
            text: 'Home and visit are written and build.',
            created_at: ago(2),
            tool_calls: [
                harnessStep('Read', { file_path: '/workspace/morrow-bakehouse/BRIEF.md' }, 11),
                harnessStep('Write', { file_path: '/workspace/morrow-bakehouse/src/pages/index.astro' }, 9),
                harnessStep('Write', { file_path: '/workspace/morrow-bakehouse/src/pages/visit.astro' }, 6),
                harnessStep('shell', { command: 'npm run build' }, 4, '> astro build\n 4 page(s) built in 3.41s'),
                harnessStep('Edit', { file_path: '/workspace/morrow-bakehouse/src/pages/order.astro' }, 2),
            ],
        },
    ],
    [CHILD.menu.id]: [
        { role: 'user', text: CHILD.menu.task, created_at: ago(12) },
        {
            role: 'assistant',
            text: 'Read 34 items.',
            created_at: ago(1),
            tool_calls: [
                harnessStep('Read', { file_path: '/workspace/morrow-bakehouse/menu.pdf' }, 10),
                harnessStep('shell', { command: 'pdftotext -layout menu.pdf -' }, 9),
                harnessStep('Write', { file_path: '/workspace/morrow-bakehouse/src/data/menu.json' }, 5),
            ],
        },
    ],
    [CHILD.photos.id]: [
        { role: 'user', text: CHILD.photos.task, created_at: ago(12) },
        {
            role: 'assistant',
            text: 'Cropped 9 of the 14.',
            created_at: ago(1),
            tool_calls: [
                { tool: 'files__write', arguments: { path: 'public/photos/hero-1600.jpg' }, result: null, is_error: false, created_at: ago(3) },
                { tool: 'files__write', arguments: { path: 'public/photos/croissants-800.jpg' }, result: null, is_error: false, created_at: ago(1) },
            ],
        },
    ],
};

/** The build of Morrow Bakehouse's site `minutes` in: each child working, or (the menu) done. */
function children(minutes: number, menuDone = false): { coding: Json[]; ops: Json[]; calls: Json[] } {
    const pages = task(CHILD.pages, minutes, { latest_update: update(CHILD.pages, 'every', 'Home and visit are written and build. Doing the order page next.', 1.5) });
    const menu = task(
        CHILD.menu,
        minutes,
        menuDone
            ? { status: 'succeeded', step: null, finished_at: ago(2), result: { text: 'Done: 34 items in src/data/menu.json.' }, latest_update: update(CHILD.menu, 'done', 'Done: 34 items. Three prices were unreadable; listed in NOTES.md.', 2) }
            : { latest_update: update(CHILD.menu, 'message', 'Read 34 items. Three prices are unreadable; marking them for the owner.', 0.8) }
    );
    const photos = task(CHILD.photos, minutes, { latest_update: update(CHILD.photos, 'every', 'Cropped 9 of the 14 photos.', 0.6) });
    return {
        coding: [childCoding(CHILD.pages, minutes), childCoding(CHILD.menu, minutes, menuDone ? 'warm' : 'working')],
        ops: [pages, menu, photos],
        calls: [spawned(CHILD.pages, minutes), spawned(CHILD.menu, minutes), spawned(CHILD.photos, minutes)],
    };
}

const CONNECT_URL = 'https://noclick.com/credential/provide/pQ7vX2kL9mN4rT8wZ3yB';

/** The same build a while on: menu and photos done, the pages held on a Stripe connection its task asked for. */
function childrenWaiting(minutes: number): { coding: Json[]; ops: Json[]; calls: Json[] } {
    const pages = task(CHILD.pages, minutes, {
        status: 'awaiting_human',
        step: 'blocked',
        latest_update: update(CHILD.pages, 'blocked', 'Waiting for its user to connect Stripe (\'stripe\').', 3, { kind: 'connection', url: CONNECT_URL, operation_id: '2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e' }),
    });
    const done = (c: Child, reply: string, finished: number) => task(c, minutes, { status: 'succeeded', step: null, finished_at: ago(finished), updated_at: ago(finished), result: { text: reply }, latest_update: update(c, 'done', reply, finished) });
    return {
        coding: [childCoding(CHILD.pages, minutes, 'warm'), childCoding(CHILD.menu, minutes, 'stopped')],
        ops: [pages, done(CHILD.menu, 'Done: 34 items. Three prices were unreadable; listed in NOTES.md.', 8), done(CHILD.photos, 'Done: 14 photos in public/photos at 800 and 1600 wide.', 5)],
        calls: [spawned(CHILD.pages, minutes), spawned(CHILD.menu, minutes), spawned(CHILD.photos, minutes)],
    };
}

const CAP = 'You’ve hit your $50 monthly cap, so work that costs money waits until it resets on November 1, or until you raise it in Settings → Plan and billing.';
const BOOT_FAILED = 'nc_daemon boot failed: the agent’s sandbox exited (code 137) before it reported why';

const DOMAIN_APPROVAL: Json = {
    object: 'approval',
    id: 'aa11bb22-cc33-4d44-8e55-ff6677889900',
    status: 'pending',
    action: 'Buy morrowbakehouse.com for 1 year',
    summary: 'Buy morrowbakehouse.com for 1 year',
    price: { amount_usd: 11.25, recurrence: 'yearly', terms: 'morrowbakehouse.com, registered to you for 1 year', renewal: { amount_usd: 11.25, months: 12 } },
    operation: 'domains_create',
    method: 'POST',
    path: '/v1/domains',
    arguments: { name: 'morrowbakehouse.com', max_price_usd: 11.25, years: 1 },
    reason: null,
    connection: { kind: 'assistant', name: 'NoClick', grant_id: null },
    user_id: null,
    operation_id: '0a9b8c7d-6e5f-4a3b-8c2d-1e0f9a8b7c6e',
    held_call_status: 'awaiting_human',
    created_at: ago(2.5),
    expires_at: new Date(NOW + 24 * 3600_000).toISOString(),
    decided_at: null,
    note: null,
    sent_to: ['web'],
    impact: null,
    consent: [],
};

const MENU_TURN = '5c4d3e2f-1a0b-4c9d-8e7f-6a5b4c3d2e1f';
const FOOTER_TURN = '8a7b6c5d-4e3f-4a2b-9c1d-0e9f8a7b6c51';
const PICKUP_TURN = '7e6f5a4b-3c2d-4e1f-8a9b-0c1d2e3f4a5b';
const PICKUP_TITLE = 'Pickup every 30 minutes';
const PICKUP_ASK = 'Change pickup times to every 30 minutes on the order form, instead of every hour.';
const RUN = '9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a';

const LARKSPUR_WORKING = coding({
    ...LARKSPUR_CODER,
    place: 'live',
    state: 'working',
    job: { operation_id: MENU_TURN, conversation: 'code', status: 'running', step: 'working', since: ago(3.2), title: MENU_TITLE, text: MENU_ASK },
    runs: [{ conversation: 'code', place: 'live', since: ago(3.1), project_id: LARKSPUR.id, daemon: true, busy: true }],
    spent_usd_this_month: 0.61,
});

const BASE = { projects: BOTH, agents: [], approvals: [], live: {}, conversations: CONVERSATIONS, operations: [] as Json[] };

export const AT_WORK_SCENARIOS: Record<ScenarioId, AtWorkScenario> = {
    none: {
        ...BASE,
        id: 'none',
        title: 'Nothing running',
        // The coordinator and an agent of the account's own are warm, ready for their next message: nothing's going.
        coding: [ownCoding('warm'), coding({ ...LARKSPUR_CODER, place: 'live', state: 'stopped', spent_usd_this_month: 0.38 }), coding({ ...MORROW_CODER, place: 'sandbox', state: 'stopped' }), supportInbox('warm')],
        operations: [
            turn(FOOTER_TURN, LARKSPUR_CODER.agent_id, 60 * 20 + 5, 'Hours in the footer', 'Put the opening hours in the footer on every page: Mon to Sat 9 to 6, Sunday closed.', {
                status: 'succeeded',
                step: null,
                finished_at: ago(60 * 20 + 1),
                updated_at: ago(60 * 20 + 1),
                result: {
                    text: 'Changed src/components/Footer.astro to show the hours from src/data/hours.ts.',
                    code: { project_id: LARKSPUR.id, repo_id: LARKSPUR.repo, branch: 'noclick-live', commits: [{ sha: '3f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39', message: 'Opening hours in the footer' }], failed_commands: [] },
                },
            }),
        ],
        history: [
            you('Can you put our opening hours in the footer of larkspur? Mon to Sat 9 to 6, Sunday closed.', 60 * 20 + 6),
            noclick('Handed to Larkspur’s coding agent. It’s making the change on the live site, so you can watch it land. I’ll tell you when it’s done.', 60 * 20 + 5, [
                handOff(FOOTER_TURN, LARKSPUR_CODER, 'Hours in the footer', 'Put the opening hours in the footer on every page: Mon to Sat 9 to 6, Sunday closed.', 60 * 20 + 5),
            ]),
            noclick('Done: the footer on [larkspur.noclick.test](https://larkspur.noclick.test) shows your hours on every page, and it’s deployed.', 60 * 20),
            you('perfect, thanks', 60 * 19),
            noclick('Anytime.', 60 * 19),
        ],
    },
    one: {
        ...BASE,
        id: 'one',
        title: 'One coding agent, live',
        coding: [LARKSPUR_WORKING, coding({ ...MORROW_CODER, place: 'sandbox', state: 'stopped' })],
        live: { [LARKSPUR.id]: liveLarkspur() },
        operations: [turn(MENU_TURN, LARKSPUR_CODER.agent_id, 3.2, MENU_TITLE, MENU_ASK)],
        history: [
            you('The menu page on larkspur is really slow on my phone. And can the opening hours go in the footer? Mon to Sat 9 to 6, Sunday closed.', 3.4),
            noclick('On it. Larkspur’s coding agent is making both changes on the live site, so you can watch them land. I’ll check in every few minutes.', 3.3, [handOff(MENU_TURN, LARKSPUR_CODER, MENU_TITLE, MENU_ASK, 3.3)]),
            noclick('The menu page was loading all 38 photos at full size; it’s resizing them now. The footer comes next.', 0.5),
        ],
    },
    sandbox: {
        ...BASE,
        id: 'sandbox',
        title: 'One coding agent, in a sandbox',
        coding: [
            coding({
                ...MORROW_CODER,
                place: 'sandbox',
                state: 'working',
                job: { operation_id: PICKUP_TURN, conversation: 'code', status: 'running', step: 'working', since: ago(1.4), title: PICKUP_TITLE, text: PICKUP_ASK },
                runs: [{ conversation: 'code', place: 'sandbox', since: ago(1.3), project_id: MORROW.id, daemon: true, busy: true }],
                spent_usd_this_month: 0.09,
            }),
            coding({ ...LARKSPUR_CODER, place: 'live', state: 'stopped', spent_usd_this_month: 0.61 }),
        ],
        operations: [turn(PICKUP_TURN, MORROW_CODER.agent_id, 1.4, PICKUP_TITLE, PICKUP_ASK)],
        history: [
            you('On morrow-bakehouse, change the order form so pickup times go every 30 minutes instead of every hour', 1.5),
            noclick('Handed to Morrow Bakehouse’s coding agent. It runs on your Claude plan, so it works in its own copy of the site, and I’ll publish the change once I’ve checked it.', 1.4, [
                handOff(PICKUP_TURN, MORROW_CODER, PICKUP_TITLE, PICKUP_ASK, 1.4),
            ]),
        ],
    },
    three: (() => {
        const build = children(7);
        return {
            ...BASE,
            id: 'three',
            title: 'Three in parallel',
            projects: BUILDING,
            agents: CHILD_AGENTS,
            coding: [...build.coding, coding({ ...LARKSPUR_CODER, place: 'live', state: 'stopped', spent_usd_this_month: 0.61 })],
            operations: build.ops,
            history: [
                you('Build a site for Morrow Bakehouse: home, the menu from the PDF, an order form, and a visit page with the map. Use the photos I sent.', 7.4),
                noclick('Splitting this three ways so it’s quicker: one agent writes the pages, one turns your menu PDF into the menu, and one prepares the photos. I’ll put it together and show you a preview before anything goes live.', 7.2, build.calls),
            ],
        };
    })(),
    waiting: (() => {
        const build = childrenWaiting(16);
        return {
            ...BASE,
            id: 'waiting',
            title: 'Waiting on you',
            projects: BUILDING,
            agents: CHILD_AGENTS,
            coding: [...build.coding, coding({ ...LARKSPUR_CODER, place: 'live', state: 'stopped', spent_usd_this_month: 0.61 })],
            operations: build.ops,
            history: [
                you('Build a site for Morrow Bakehouse: home, the menu from the PDF, an order form that takes payment, and a visit page with the map.', 16.4),
                noclick('Splitting this three ways so it’s quicker: one agent writes the pages, one turns your menu PDF into the menu, and one prepares the photos. I’ll show you a preview before anything goes live.', 16.2, build.calls),
                noclick(
                    `The menu and the photos are done. One thing needs you before the order form is finished: **it takes card payments once the bakery’s Stripe account is connected.** [Connect Stripe](${CONNECT_URL}) takes a minute; or tell me to skip payments, and orders will come to your inbox to settle in the shop.`,
                    3
                ),
            ],
        };
    })(),
    cap: {
        ...BASE,
        id: 'cap',
        title: 'Paused by the spending cap',
        coding: [LARKSPUR_CODER, MORROW_CODER].map((coder) =>
            coding({ ...coder, place: coder === LARKSPUR_CODER ? 'live' : 'sandbox', state: 'paused', paused: { reason: 'spend_cap', message: CAP }, pauses: [{ reason: 'spend_cap', message: CAP }], spent_usd_this_month: coder === LARKSPUR_CODER ? 6.12 : 2.4 })
        ),
        history: [
            you('Make the photos on larkspur’s home page bigger, like full width', 1.2),
            noclick('I can’t start that right now: you’ve hit your $50 monthly cap, so work that costs money waits until it resets on November 1. You can raise it in Settings → Plan and billing, and I’ll start as soon as you do.', 1.1),
        ],
    },
    failed: {
        ...BASE,
        id: 'failed',
        title: 'Didn’t start',
        coding: [
            coding({ ...MORROW_CODER, place: 'sandbox', state: 'paused', paused: { reason: 'failed_start', message: BOOT_FAILED }, pauses: [{ reason: 'failed_start', message: BOOT_FAILED }], spent_usd_this_month: 0.09 }),
            coding({ ...LARKSPUR_CODER, place: 'live', state: 'stopped', spent_usd_this_month: 0.61 }),
        ],
        operations: [
            turn(PICKUP_TURN, MORROW_CODER.agent_id, 4.4, PICKUP_TITLE, PICKUP_ASK, {
                status: 'failed',
                step: null,
                finished_at: ago(3.95),
                error: { type: 'platform_error', message: BOOT_FAILED },
            }),
        ],
        history: [
            you('On morrow-bakehouse, change the order form so pickup times go every 30 minutes instead of every hour', 4.5),
            noclick('Handed to Morrow Bakehouse’s coding agent. It runs on your Claude plan, so it works in its own copy of the site, and I’ll publish the change once I’ve checked it.', 4.4, [
                handOff(PICKUP_TURN, MORROW_CODER, PICKUP_TITLE, PICKUP_ASK, 4.4),
            ]),
            noclick('It didn’t start: its sandbox stopped before the agent could begin, which is on our side, not your plan. Want me to try again?', 3.9),
        ],
    },
    busy: (() => {
        const build = children(12, true);
        const run = operation(RUN, 'workflow.run', 1.1, { step: 'agent_turn', summary: 'Wholesale orders to the kitchen sheet' });
        const startRun = call('workflows_runs_create', { workflow_id: 'workflow:wholesale-orders' }, { success: true, operation_id: RUN, status: 'queued', response: { object: 'operation', id: RUN, kind: 'workflow.run', status: 'queued' } }, 1.1);
        return {
            ...BASE,
            id: 'busy',
            title: 'Everything at once',
            projects: BUILDING,
            agents: CHILD_AGENTS,
            live: { [LARKSPUR.id]: liveLarkspur() },
            approvals: [DOMAIN_APPROVAL],
            coding: [ownCoding('working'), { ...LARKSPUR_WORKING, spent_usd_this_month: 4.86 }, ...build.coding, supportInbox('warm')],
            operations: [...build.ops, run, turn(MENU_TURN, LARKSPUR_CODER.agent_id, 3.2, MENU_TITLE, MENU_ASK)],
            history: [
                you('The menu page on larkspur is really slow on my phone. And put the opening hours in the footer: Mon to Sat 9 to 6, Sunday closed.', 12.6),
                noclick('On it. Larkspur’s coding agent is making both changes on the live site.', 12.5, [handOff(MENU_TURN, LARKSPUR_CODER, MENU_TITLE, MENU_ASK, 12.5)]),
                you('Also build the Morrow Bakehouse site: home, menu from the PDF, order form, visit page. Get it a domain too.', 12.2),
                noclick('Splitting the site three ways: pages, the menu, and the photos. For the domain, morrowbakehouse.com is free at $11.25 a year; it waits for your OK.', 12, build.calls),
                you('And run the wholesale orders now', 1.2),
                noclick('Running it now.', 1.1, [startRun]),
                noclick('The menu’s done: 34 items. Three prices were unreadable (Rye loaf, Seeded batard, Plum galette), so I’ll ask you for those when I show you the preview.', 2),
            ],
        };
    })(),
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** The scenario's /v1 beside the coordinator's own (`fakeCoordinatorAgent`'s `routes`); `writes` records the enter
 *  links minted, the operations stopped and the approvals answered (with what was sent). */
export function atWorkRoutes(scenario: AtWorkScenario, writes: { method: string; path: string; body?: unknown }[] = []): ExtraRoutes {
    return (method, path, query, body) => {
        if (method === 'GET' && path === '/v1/agents/coding') return json({ object: 'list', data: scenario.coding, read_at: new Date().toISOString() });
        if (method === 'GET' && path === '/v1/projects') return json({ object: 'list', data: scenario.projects, next_cursor: null });
        if (method === 'GET' && path === '/v1/approvals') return json({ object: 'list', data: scenario.approvals.filter((a) => !query.get('status') || a.status === query.get('status')), next_cursor: null });
        const approval = method === 'GET' && path.match(/^\/v1\/approvals\/([^/]+)$/);
        if (approval) {
            const found = scenario.approvals.find((a) => a.id === approval[1]);
            return found ? json(found) : json({ error: { type: 'not_found', message: `No approval '${approval[1]}' in this account.` } }, 404);
        }
        const live = path.match(/^\/v1\/projects\/([^/]+)\/live(\/edits)?$/);
        if (method === 'GET' && live && scenario.live[live[1]]) {
            const { state, edits } = scenario.live[live[1]];
            if (!live[2]) return json(state);
            const after = Number(query.get('after') ?? 0);
            const shown = edits.filter((e) => Number(e.seq) > after).slice(0, Number(query.get('limit') ?? 50));
            return json({ object: 'list', data: shown, last_seq: shown.length ? shown[shown.length - 1].seq : after, session: { id: SESSION_ID, state: 'live' } });
        }
        // Each helper's one session: a child's task, a coding agent's own (the conversation its turns run in).
        const sessions = path.match(/^\/v1\/agents\/([^/]+)\/conversations$/);
        if (method === 'GET' && sessions) {
            const coder = scenario.coding.find((c) => c.agent_id === sessions[1]) as { job?: { conversation?: string } | null } | undefined;
            const session = scenario.conversations[sessions[1]] ? 'task' : coder?.job?.conversation;
            if (session) return json({ object: 'list', data: [{ object: 'agent_conversation', conversation: session, active: true, people: [] }], next_cursor: null });
        }
        const conversation = path.match(/^\/v1\/agents\/([^/]+)\/conversations\/task$/);
        if (method === 'GET' && conversation && scenario.conversations[conversation[1]]) return json({ object: 'conversation', id: 'task', agent_id: conversation[1], messages: scenario.conversations[conversation[1]] });
        // The rest of a child's task conversation, as its conversation (Work's) reads it beside the chat: nothing asked
        // of anyone, no commands of its harness.
        const asked = path.match(/^\/v1\/agents\/([^/]+)\/conversations\/task\/(requests|commands)$/);
        if (method === 'GET' && asked && scenario.conversations[asked[1]]) return json(asked[2] === 'requests' ? { object: 'list', data: [] } : { harness: 'claude_code', commands: [] });
        const agent = path.match(/^\/v1\/agents\/([^/]+)$/);
        const child = agent && scenario.agents.find((a) => a.id === agent[1]);
        if (method === 'GET' && child) return json(child);
        // A coding agent at work, as GET /v1/agents/{id} reads it.
        const coder = agent && (scenario.coding as { agent_id?: string; name?: string; harness?: string; model?: string }[]).find((c) => c.agent_id === agent[1]);
        if (method === 'GET' && coder) return json({ object: 'agent', id: coder.agent_id, name: coder.name, harness: coder.harness, model: coder.model, user_id: null, status: 'active', origin: 'api' });
        if (method === 'POST' && /^\/v1\/projects\/[^/]+\/live\/enter_links$/.test(path)) {
            writes.push({ method, path });
            return json({ url: `https://${LARKSPUR.host}/__noclick/live/entered`, expires_at: new Date(Date.now() + 7200_000).toISOString() });
        }
        // The owner's answer, as the approval page posts it: the approval decided, as GET /v1/approvals/{id} then reads it.
        const answer = path.match(/^\/v1\/approvals\/([^/]+)\/answer$/);
        const held = answer && scenario.approvals.find((a) => a.id === answer[1]);
        if (method === 'POST' && held) {
            writes.push({ method, path, body });
            const { approved, note } = body as { approved: boolean; note: string | null };
            const decided = { ...held, status: approved ? 'approved' : 'declined', decided_at: new Date().toISOString(), note };
            scenario.approvals = scenario.approvals.map((a) => (a.id === held.id ? decided : a));
            return json(decided);
        }
        if (method === 'POST' && /^\/v1\/operations\/[^/]+\/cancel$/.test(path)) {
            writes.push({ method, path });
            return json({ object: 'operation', id: path.split('/')[3], status: 'canceled' });
        }
        return undefined;
    };
}

export const AT_WORK_IDS = { LARKSPUR, MORROW, LARKSPUR_CODER: LARKSPUR_CODER.agent_id, MORROW_CODER: MORROW_CODER.agent_id, CHILD, MENU_TURN, FOOTER_TURN, DOMAIN_APPROVAL_ID: DOMAIN_APPROVAL.id as string, SUPPORT_INBOX, COORDINATOR: COORDINATOR_ID };
