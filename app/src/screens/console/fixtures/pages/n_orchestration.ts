// Fixtures for agents that coordinate agents, wake-ups, channel subscriptions
// and workspaces (designed): `planner`, a coordinator whose `agents` tools
// spawned helpers (one now expired), the jobs it started with their updates,
// its wake-ups and what `ask` answers; two workspaces over the channels, and
// what the channels are subscribed to. Each agent's live fields (status, last
// active, running turns, children) ride i_agents.ts's rows; b.ts and c.ts serve
// the turns, conversations and channels from here. Stateless like the other
// pages: a write answers the row it would leave.
import {
    AGENTS,
    DAY,
    FIXTURE_NOW_MS,
    HOUR,
    MIN,
    PAGE_ERROR,
    USERS,
    ago,
    apiError,
    fixtureId,
    list,
    ok,
    pageList,
    rememberOperation,
    type FixtureReply,
    type FixtureRequest,
    type FixtureRoute,
} from '../core';

type Json = Record<string, unknown>;

const [SUPPORT, CONCIERGE] = AGENTS;
const [ACME, ANA] = USERS;
const ASSISTANTS = AGENTS.filter((a) => a.name === 'assistant');
const CODER = AGENTS.find((a) => a.name === 'coder')!;
const REVIEWER = AGENTS.find((a) => a.name === 'reviewer')!;
/** i_agents.ts's automation; named here by id so this file imports no other page. */
const DIGEST_ID = fixtureId(3, 20);
/** c.ts's `launch`, Acme's channel, which sits in Acme's workspace. */
export const ACME_LAUNCH_CHANNEL_ID = fixtureId(7, 101);

const iso = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString();
const aid = (n: number) => fixtureId(3, 60 + n);
const oid = (n: number) => fixtureId(4, 140_000 + n);
const wid = (n: number) => fixtureId(9, 140_100 + n);
const uid = (n: number) => fixtureId(9, 140_200 + n);
const wsid = (n: number) => fixtureId(9, 140_300 + n);
const sid = (n: number) => fixtureId(9, 140_400 + n);
const mid = (n: number) => fixtureId(9, 140_500 + n);
const cid = (n: number) => fixtureId(7, 140_000 + n);

// ── the coordinator and its children ───────────────────────────────────────

const MODEL = 'anthropic/claude-sonnet-4.6';

function agentRow(n: number, fields: Json): Json {
    return {
        object: 'agent',
        id: aid(n),
        model: MODEL,
        harness: 'sdk',
        can_request: [],
        grants: [],
        user_id: null,
        workflow_id: fixtureId(8, 60 + n),
        parent_id: null,
        ttl_s: null,
        expires_at: null,
        budget_usd_per_month: null,
        paused: false,
        trigger_kinds: [],
        browser_profile_id: null,
        card_id: null,
        volumes: {},
        secret_ids: [],
        timezone: null,
        network: null,
        shell: null,
        repos: [],
        ...fields,
    };
}

export const PLANNER = agentRow(0, {
    name: 'planner',
    instructions:
        'You run our product launches. Spawn a researcher for the competition and a writer for the announcement, keep track of them, and tell the launch channel how it is going.',
    // The agents capability: spawn, message, ask, status, list and cancel, within its own scope.
    tools: ['search', 'fetch', 'gmail.send_email', 'agents'],
    budget_usd_per_month: 25,
    created_at: ago(6 * DAY),
});

const RESEARCHER = agentRow(1, {
    name: 'research-rivals',
    instructions: "Every ten minutes, tell planner what you've read, what's worth copying and what's left.",
    tools: ['search', 'fetch'],
    parent_id: PLANNER.id,
    ttl_s: 3600,
    expires_at: iso(40 * MIN),
    budget_usd_per_month: 2,
    created_at: ago(20 * MIN),
});

const WRITER = agentRow(2, {
    name: 'announcement-writer',
    instructions: 'Before an email goes out, say who it goes to and why. Tell planner when anything on the press list looks wrong.',
    tools: ['gmail.send_email'],
    parent_id: PLANNER.id,
    ttl_s: 7200,
    expires_at: iso(75 * MIN),
    budget_usd_per_month: 3,
    created_at: ago(45 * MIN),
});

/** Spawned without a name: `<parent>-<8 hex>`. */
const PRICING = agentRow(3, {
    name: 'planner-7c41e09b',
    instructions: 'Report the price of each plan, as a table.',
    tools: ['fetch'],
    parent_id: PLANNER.id,
    ttl_s: 7200,
    expires_at: iso(50 * MIN),
    budget_usd_per_month: 1,
    created_at: ago(70 * MIN),
});

const SCOUT = agentRow(4, {
    name: 'old-scout',
    instructions: 'Find where our competitors announced their last launch.',
    tools: ['search'],
    parent_id: PLANNER.id,
    ttl_s: 3600,
    expires_at: ago(3 * DAY - HOUR),
    budget_usd_per_month: 1,
    created_at: ago(3 * DAY),
});

/** Every agent's live fields (designed): what it's doing now, when it last did anything, its live children. */
interface Live {
    status: 'working' | 'waiting' | 'idle' | 'expired';
    last_active_at: string | null;
    running_turns: number;
    child_count: number;
    job_id: string | null;
}

const live = (status: Live['status'], lastActive: string | null, running = 0, children = 0, job: string | null = null): Live => ({
    status,
    last_active_at: lastActive,
    running_turns: running,
    child_count: children,
    job_id: job,
});

/** b.ts's turns decide the core agents': concierge is booking a table now, the rest are between turns. */
export const AGENT_LIVE: Record<string, Live> = {
    [SUPPORT.id]: live('idle', ago(3 * HOUR - 80)),
    [CONCIERGE.id]: live('working', ago(20_400), 1),
    [ASSISTANTS[0].id]: live('idle', ago(2 * DAY)),
    [ASSISTANTS[1].id]: live('idle', ago(5 * HOUR)),
    [CODER.id]: live('idle', ago(26 * HOUR)),
    [REVIEWER.id]: live('idle', null),
    [DIGEST_ID]: live('idle', ago(9 * HOUR)),
    [PLANNER.id as string]: live('working', ago(MIN), 1, 3),
    [RESEARCHER.id as string]: live('working', ago(40_000), 1, 0, oid(1)),
    [WRITER.id as string]: live('working', ago(30 * MIN), 1, 0, oid(2)),
    [PRICING.id as string]: live('idle', ago(40 * MIN), 0, 0, oid(3)),
    [SCOUT.id as string]: live('expired', ago(3 * DAY - 40 * MIN), 0, 0, oid(5)),
};

export const ORCHESTRATION_AGENTS: Json[] = [PLANNER, RESEARCHER, WRITER, PRICING, SCOUT];
export const PLANNER_CHILDREN = [RESEARCHER, WRITER, PRICING, SCOUT];

// ── jobs and their updates ─────────────────────────────────────────────────

const CONVERSATION = 'launch-oct';
/** A held call's human request: its page goes to the approver only, so the update carries no url. */
const APPROVAL_OPERATION = oid(90);

function update(n: number, job: number, agentId: unknown, kind: string, at: number, fields: Json): Json {
    return {
        object: 'job_update',
        id: uid(n),
        job_id: oid(job),
        agent_id: agentId,
        kind,
        text: null,
        tool: null,
        arguments: null,
        status: 'running',
        result: null,
        error: null,
        waiting_on: null,
        wakeup_id: null,
        created_at: ago(at),
        ...fields,
    };
}

/** Each job's updates, oldest first. */
export const JOB_UPDATES: Record<string, Json[]> = {
    [oid(1)]: [
        update(1, 1, RESEARCHER.id, 'every', 11 * MIN, {
            text: "Read nine launch posts. Rival A's pricing page and Rival B's changelog are worth copying; Rival C is next.",
            wakeup_id: wid(5),
        }),
        update(2, 1, RESEARCHER.id, 'every', MIN, {
            text: "Rival C's launch was quieter: one changelog post and a thread. Writing up all three now.",
            wakeup_id: wid(4),
        }),
    ],
    [oid(2)]: [
        update(3, 2, WRITER.id, 'before', 36 * MIN, {
            text: 'Sending the embargoed announcement to the press list for the 10:00 PT slot.',
            tool: 'gmail.send_email',
            arguments: { to: ['press@acme.test'], subject: 'Embargoed: Acme 3.0 ships October 8' },
            wakeup_id: wid(6),
        }),
        update(4, 2, WRITER.id, 'blocked', 35 * MIN, {
            text: 'Waiting for a person to approve its call to gmail.send_email.',
            status: 'awaiting_human',
            waiting_on: { kind: 'approval', url: null, operation_id: APPROVAL_OPERATION },
            wakeup_id: wid(6),
        }),
        update(5, 2, WRITER.id, 'message', 30 * MIN, {
            text: 'Three addresses on the press list bounced last time; I left them out of the send.',
            status: 'awaiting_human',
            wakeup_id: wid(7),
        }),
    ],
    [oid(3)]: [
        update(6, 3, PRICING.id, 'message', 68 * MIN, { text: 'Starting with the three pricing pages you named.', wakeup_id: wid(8) }),
        update(7, 3, PRICING.id, 'done', 40 * MIN, {
            text: 'Rival A charges $49 a seat, Rival B $39 with a yearly discount, and Rival C shows prices only after a demo.',
            status: 'succeeded',
            result: { text: 'Rival A charges $49 a seat, Rival B $39 with a yearly discount, and Rival C shows prices only after a demo.', conversation: 'task', cost_usd: 0.031 },
            wakeup_id: wid(9),
        }),
    ],
    [oid(4)]: [
        update(8, 4, SUPPORT.id, 'done', 2 * HOUR, {
            text: 'Customers ask most about seat pricing and whether the yearly discount carries over.',
            status: 'succeeded',
            result: { text: 'Customers ask most about seat pricing and whether the yearly discount carries over.', conversation: 'launch-faq', cost_usd: 0.004 },
            wakeup_id: wid(10),
        }),
    ],
    [oid(5)]: [
        update(9, 5, SCOUT.id, 'done', 3 * DAY - HOUR, {
            text: "Found two of the three launch posts: Rival A's on its blog and Rival B's on Product Hunt.",
            status: 'expired',
            error: { type: 'expired', message: "The agent's time ran out before it finished." },
        }),
    ],
};

function jobRow(n: number, fields: Json & { agent_id: unknown; kind: string; status: string; created: number; updates: unknown[] }): Json {
    const { created, ...rest } = fields;
    const updates = JOB_UPDATES[oid(n)] ?? [];
    return rememberOperation({
        object: 'operation',
        id: oid(n),
        step: null,
        user_id: null,
        key_id: null,
        started_by: PLANNER.id,
        conversation: 'task',
        parent_conversation: CONVERSATION,
        latest_update: updates.at(-1) ?? null,
        result: null,
        error: null,
        created_at: ago(created),
        updated_at: String(updates.at(-1)?.created_at ?? ago(created)),
        events: [{ status: 'queued', at: ago(created) }, { status: 'running', at: ago(created - 400) }],
        ...rest,
    });
}

/** The jobs planner started, newest first: three spawned tasks, one message to another agent, one that expired. */
export const PLANNER_JOBS: Json[] = [
    jobRow(1, {
        kind: 'agent.task',
        status: 'running',
        step: 'working',
        agent_id: RESEARCHER.id,
        summary: 'Find the last three launches in our category and what made them work.',
        updates: ['done', { every_s: 600 }],
        input: { agent_id: RESEARCHER.id, task: 'Find the last three launches in our category and what made them work.', conversation: 'task', started_by: PLANNER.id, parent_conversation: CONVERSATION },
        created: 20 * MIN,
    }),
    jobRow(2, {
        kind: 'agent.task',
        status: 'awaiting_human',
        agent_id: WRITER.id,
        summary: 'Write the launch announcement and send it to the press list under embargo.',
        updates: ['done', 'blocked', { before: ['gmail.send_email'] }],
        input: { agent_id: WRITER.id, task: 'Write the launch announcement and send it to the press list under embargo.', conversation: 'task', started_by: PLANNER.id, parent_conversation: CONVERSATION },
        events: [
            { status: 'queued', at: ago(45 * MIN) },
            { status: 'running', at: ago(45 * MIN - 400) },
            { status: 'awaiting_human', at: ago(35 * MIN) },
        ],
        created: 45 * MIN,
    }),
    jobRow(3, {
        kind: 'agent.task',
        status: 'succeeded',
        agent_id: PRICING.id,
        summary: "Read Rival A, B and C's pricing pages.",
        updates: ['done'],
        result: JOB_UPDATES[oid(3)][1].result,
        events: [
            { status: 'queued', at: ago(70 * MIN) },
            { status: 'running', at: ago(70 * MIN - 400) },
            { status: 'succeeded', at: ago(40 * MIN) },
        ],
        created: 70 * MIN,
    }),
    jobRow(4, {
        kind: 'agent.message',
        status: 'succeeded',
        agent_id: SUPPORT.id,
        summary: 'What do customers ask most about the new plans?',
        conversation: 'launch-faq',
        updates: ['done'],
        result: JOB_UPDATES[oid(4)][0].result,
        events: [
            { status: 'queued', at: ago(2 * HOUR + 40_000) },
            { status: 'running', at: ago(2 * HOUR + 39_000) },
            { status: 'succeeded', at: ago(2 * HOUR) },
        ],
        created: 2 * HOUR + 40_000,
    }),
    jobRow(5, {
        kind: 'agent.task',
        status: 'expired',
        agent_id: SCOUT.id,
        summary: 'Find where our competitors announced their last launch.',
        parent_conversation: 'launch-sept',
        updates: ['done'],
        error: { type: 'expired', message: "The agent's time ran out before it finished." },
        events: [
            { status: 'queued', at: ago(3 * DAY) },
            { status: 'running', at: ago(3 * DAY - 400) },
            { status: 'expired', at: ago(3 * DAY - HOUR) },
        ],
        created: 3 * DAY,
    }),
];

const turn = (n: number, agent: Json, status: string, at: number, fields: Json = {}): Json =>
    rememberOperation({
        object: 'operation',
        id: oid(n),
        kind: 'agent.message',
        status,
        step: null,
        agent_id: agent.id,
        user_id: null,
        key_id: null,
        summary: fields.summary ?? 'A turn',
        input: { agent_id: agent.id, conversation: fields.conversation ?? 'task' },
        result: null,
        error: null,
        created_at: ago(at),
        updated_at: ago(at),
        events: [{ status: 'running', at: ago(at) }],
        ...fields,
    });

/** The turns running now (each agent's Now), and the planner turns its wake-ups started. */
export const ORCHESTRATION_TURNS: Json[] = [
    turn(11, PLANNER, 'running', MIN, { summary: 'An update from research-rivals', conversation: CONVERSATION }),
    turn(12, RESEARCHER, 'running', 20 * MIN, { summary: 'Find the last three launches in our category and what made them work.' }),
    turn(13, WRITER, 'awaiting_human', 45 * MIN, {
        summary: 'Write the launch announcement and send it to the press list under embargo.',
        events: [{ status: 'running', at: ago(45 * MIN) }, { status: 'awaiting_human', at: ago(35 * MIN) }],
    }),
    turn(14, PLANNER, 'succeeded', 10 * MIN, {
        summary: 'An update from research-rivals',
        conversation: CONVERSATION,
        result: { text: 'Told the channel research is two-thirds done.', conversation: CONVERSATION, tool_calls: [], cost_usd: 0.006 },
        events: [{ status: 'running', at: ago(10 * MIN) }, { status: 'succeeded', at: ago(9 * MIN) }],
    }),
];

const conversationRow = (agent: Json, conversation: string, title: string, preview: string, turns: number, cost: number, at: number) => ({
    object: 'agent_conversation',
    conversation,
    agent_id: agent.id,
    user_id: null,
    title,
    preview,
    turns,
    cost_usd: cost,
    last_activity: ago(at),
    status: 'active',
    handed_off_to: null,
    model_usage: null,
});

/** The coordinator's thread its updates wake, and each child's task (b.ts lists them with its own). */
export const ORCHESTRATION_CONVERSATIONS: Json[] = [
    conversationRow(PLANNER, CONVERSATION, 'October launch', 'Told the channel research is two-thirds done.', 9, 0.084, MIN),
    conversationRow(RESEARCHER, 'task', 'Recent launches in our category', "Rival C's launch was quieter: one changelog post and a thread.", 1, 0.052, 40_000),
    conversationRow(WRITER, 'task', 'Launch announcement', 'Waiting for approval to email the press list.', 1, 0.021, 30 * MIN),
    conversationRow(PRICING, 'task', "Rivals' pricing", 'Rival A charges $49 a seat, Rival B $39 with a yearly discount…', 1, 0.031, 40 * MIN),
];

/** Their transcripts, by `<agent id>/<conversation>` (every child's task conversation is called `task`). */
export const ORCHESTRATION_TRANSCRIPTS: Record<string, { role: string; text: string; created_at: string }[]> = {
    [`${PLANNER.id}/${CONVERSATION}`]: [
        { role: 'user', text: 'Run the October launch: research the competition, write the announcement, and keep #launch-oct posted.', created_at: ago(75 * MIN) },
        { role: 'assistant', text: 'Spawned a researcher, a pricing check and a writer. I will post in #launch-oct as their updates come in.', created_at: ago(74 * MIN) },
        { role: 'user', text: "[update from research-rivals] Read nine launch posts. Rival A's pricing page and Rival B's changelog are worth copying; Rival C is next.", created_at: ago(10 * MIN) },
        { role: 'assistant', text: 'Told the channel research is two-thirds done.', created_at: ago(9 * MIN) },
    ],
    [`${RESEARCHER.id}/task`]: [{ role: 'user', text: 'Find the last three launches in our category and what made them work.', created_at: ago(20 * MIN) }],
    [`${WRITER.id}/task`]: [{ role: 'user', text: 'Write the launch announcement and send it to the press list under embargo.', created_at: ago(45 * MIN) }],
    [`${PRICING.id}/task`]: [
        { role: 'user', text: "Read Rival A, B and C's pricing pages.", created_at: ago(70 * MIN) },
        { role: 'assistant', text: 'Rival A charges $49 a seat, Rival B $39 with a yearly discount, and Rival C shows prices only after a demo.', created_at: ago(40 * MIN) },
    ],
};

/** Every operation here, for reads filtered to its agent or kind (b.ts adds them only then, so the Logs story stays as it is). */
export const ORCHESTRATION_OPERATIONS: Json[] = [...PLANNER_JOBS, ...ORCHESTRATION_TURNS];
export const ORCHESTRATION_AGENT_IDS = new Set(ORCHESTRATION_AGENTS.map((a) => String(a.id)));

// ── wake-ups ───────────────────────────────────────────────────────────────

function wakeup(n: number, fields: Json & { source: string; status: string; note: string }): Json {
    return {
        object: 'wakeup',
        id: wid(n),
        agent_id: PLANNER.id,
        user_id: null,
        conversation: CONVERSATION,
        at: null,
        when: null,
        woken_by: null,
        operation_id: null,
        depth: 0,
        error: null,
        created_at: ago(HOUR),
        delivered_at: null,
        ...fields,
    };
}

const updateOf = (n: number) => Object.values(JOB_UPDATES).flat().find((u) => u.id === uid(n))!;

/** planner's wake-ups, newest first: what it set itself, what your code set, and the ones NoClick set for its updates and answers. */
export const WAKEUPS: Json[] = [
    wakeup(1, { source: 'wake_me', status: 'pending', at: iso(50 * MIN), depth: 1, note: 'Check whether ops approved the press email; if not, ask them once.', created_at: ago(30 * MIN) }),
    wakeup(2, {
        source: 'code',
        status: 'pending',
        when: { operation_id: oid(2) },
        note: 'When the announcement has gone out, post the launch checklist in #launch-oct.',
        created_at: ago(44 * MIN),
    }),
    wakeup(3, {
        source: 'code',
        status: 'pending',
        when: { event: 'connection.connected', filters: { name: 'hubspot' } },
        note: 'HubSpot is connected: import the press contacts and tag them launch-oct.',
        created_at: ago(DAY),
    }),
    wakeup(4, { source: 'update', status: 'delivered', at: ago(MIN), delivered_at: ago(MIN), operation_id: oid(11), woken_by: { update: updateOf(2) }, note: 'An update from research-rivals.', created_at: ago(MIN) }),
    wakeup(5, { source: 'update', status: 'delivered', at: ago(11 * MIN), delivered_at: ago(10 * MIN), operation_id: oid(14), woken_by: { update: updateOf(1) }, note: 'An update from research-rivals.', created_at: ago(11 * MIN) }),
    wakeup(7, { source: 'update', status: 'delivered', at: ago(30 * MIN), delivered_at: ago(30 * MIN), woken_by: { update: updateOf(5) }, note: 'An update from announcement-writer.', created_at: ago(30 * MIN) }),
    wakeup(6, { source: 'update', status: 'delivered', at: ago(35 * MIN), delivered_at: ago(35 * MIN), woken_by: { update: updateOf(4) }, note: 'Two updates from announcement-writer.', created_at: ago(36 * MIN) }),
    wakeup(9, { source: 'update', status: 'delivered', at: ago(40 * MIN), delivered_at: ago(40 * MIN), woken_by: { update: updateOf(7) }, note: 'planner-7c41e09b finished its task.', created_at: ago(40 * MIN) }),
    wakeup(8, { source: 'update', status: 'delivered', at: ago(68 * MIN), delivered_at: ago(68 * MIN), woken_by: { update: updateOf(6) }, note: 'An update from planner-7c41e09b.', created_at: ago(68 * MIN) }),
    wakeup(10, { source: 'update', status: 'delivered', at: ago(2 * HOUR), delivered_at: ago(2 * HOUR), woken_by: { update: updateOf(8) }, note: 'support-bot answered your message.', created_at: ago(2 * HOUR) }),
    wakeup(11, {
        source: 'answer',
        status: 'delivered',
        at: ago(2 * HOUR + 10 * MIN),
        delivered_at: ago(2 * HOUR + 10 * MIN),
        woken_by: { operation_id: fixtureId(4, 140_090), kind: 'credential.connect', status: 'succeeded', result: { connection: { name: 'hubspot', status: 'connected' } } },
        note: 'You asked your user to connect an account, and that link is done: see whether they connected it, and carry on with what you needed it for.',
        created_at: ago(5 * HOUR),
    }),
    wakeup(12, {
        source: 'wake_me',
        status: 'failed',
        at: ago(DAY),
        depth: 3,
        note: 'See whether the beta signups crossed 500.',
        error: { type: 'payment_required', message: "Your account couldn't pay for this turn: $0.00 left, $0.04 needed." },
        created_at: ago(DAY + 2 * HOUR),
    }),
    wakeup(13, { source: 'code', status: 'canceled', at: ago(2 * DAY), note: 'Remind the team about the launch retro.', created_at: ago(5 * DAY) }),
];

/** support-bot, an account agent, set this one itself in one of its users' threads. */
export const SHARED_WAKEUPS: Json[] = [
    wakeup(14, {
        agent_id: AGENTS[0].id,
        user_id: 'acme',
        conversation: 'booking-17',
        source: 'wake_me',
        status: 'pending',
        at: iso(2 * HOUR),
        depth: 1,
        note: 'See whether the deposit cleared, and confirm the booking.',
        created_at: ago(10 * MIN),
    }),
];

// ── ask ────────────────────────────────────────────────────────────────────

/** What `ask` answers, by agent: from a snapshot, or (interject) from the turn it joined. */
function askReply(r: FixtureRequest): FixtureReply {
    const body = (r.body ?? {}) as { question?: string; conversation?: string; interject?: boolean };
    const known = ORCHESTRATION_AGENTS.some((a) => a.id === r.params.id) || AGENTS.some((a) => a.id === r.params.id) || r.params.id === DIGEST_ID;
    if (!known) return apiError(404, 'not_found', `Agent ${r.params.id} not found.`);
    if (!body.question?.trim()) return apiError(400, 'invalid_request', 'Ask a question.', 'Send the question as text.');
    const running = AGENT_LIVE[r.params.id]?.running_turns ?? 0;
    const joined = body.interject && running ? (ORCHESTRATION_TURNS.find((t) => t.agent_id === r.params.id && t.status === 'running')?.id ?? null) : null;
    const planner = r.params.id === PLANNER.id;
    const text = joined
        ? planner
            ? "Noted: I've told research-rivals to skip Rival C's enterprise tier and finish the write-up."
            : "Noted. I'll take that into account for the rest of this turn."
        : planner
          ? 'Research is two-thirds done: Rival A and Rival B are written up and Rival C is in progress. The announcement is drafted and waiting for ops to approve the press email.'
          : 'From its conversation so far: it finished its last turn and is waiting for its next message.';
    const conversation = body.conversation || (planner ? CONVERSATION : 'task');
    return {
        status: 202,
        body: rememberOperation({
            object: 'operation',
            id: oid(joined ? 31 : 30),
            kind: 'agent.ask',
            status: 'succeeded',
            agent_id: r.params.id,
            user_id: r.headers.get('NoClick-User'),
            summary: body.question,
            input: { agent_id: r.params.id, question: body.question, conversation, interject: !!body.interject },
            result: { text, conversation, tool_calls: [], joined, cost_usd: 0.002 },
            error: null,
            created_at: new Date(FIXTURE_NOW_MS).toISOString(),
            updated_at: new Date(FIXTURE_NOW_MS).toISOString(),
            events: [{ status: 'running', at: new Date(FIXTURE_NOW_MS).toISOString() }, { status: 'succeeded', at: new Date(FIXTURE_NOW_MS).toISOString() }],
        }),
    };
}

// ── workspaces ─────────────────────────────────────────────────────────────

const LOGO = `data:image/svg+xml;utf8,${encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" fill="#111827"/><path d="M11 29 20 10l9 19h-5l-4-9-4 9z" fill="#f9fafb"/></svg>'
)}`;

const wsMember = (n: number, fields: Json): Json => ({ object: 'workspace_member', id: mid(n), agent_id: null, user_id: null, created_at: ago(10 * DAY), ...fields });

export const WORKSPACES: Json[] = [
    {
        object: 'workspace',
        id: wsid(1),
        name: 'Launch team',
        logo_url: null,
        user_id: null,
        status: 'active',
        budget_usd_per_month: 50,
        spent_usd: 12.4,
        channel_count: 2,
        members: [
            wsMember(1, { type: 'agent', agent_id: PLANNER.id, name: 'planner' }),
            wsMember(2, { type: 'agent', agent_id: SUPPORT.id, name: 'support-bot' }),
            wsMember(3, { type: 'agent', agent_id: CODER.id, name: 'coder' }),
            wsMember(4, { type: 'user', user_id: ANA.id, name: ANA.name }),
        ],
        created_at: ago(10 * DAY),
    },
    {
        object: 'workspace',
        id: wsid(2),
        name: 'Acme',
        logo_url: LOGO,
        user_id: ACME.id,
        status: 'active',
        budget_usd_per_month: null,
        spent_usd: 3.42,
        channel_count: 1,
        members: [
            wsMember(5, { type: 'agent', agent_id: CONCIERGE.id, name: 'concierge' }),
            wsMember(6, { type: 'agent', agent_id: SUPPORT.id, name: 'support-bot' }),
            wsMember(7, { type: 'user', user_id: ACME.id, name: ACME.name }),
        ],
        created_at: ago(3 * DAY),
    },
];
export const [LAUNCH_WORKSPACE, ACME_WORKSPACE] = WORKSPACES;

const chMember = (n: number, fields: Json) => ({
    object: 'channel_member',
    id: fixtureId(0, 140_000 + n),
    agent_id: null,
    a2a_url: null,
    a2a_header_names: null,
    user_id: null,
    busy: false,
    created_at: ago(9 * DAY),
    ...fields,
});

/** The Launch team's channels; c.ts lists them beside its own. */
export const WORKSPACE_CHANNELS: Json[] = [
    {
        object: 'channel',
        id: cid(1),
        name: 'launch-oct',
        mode: 'mentions',
        status: 'open',
        halt_reason: null,
        max_agent_turns: 20,
        max_mention_hops: 8,
        budget_usd: 10,
        spent_usd: 2.15,
        agent_turns_since_human: 1,
        user_id: null,
        workspace_id: LAUNCH_WORKSPACE.id,
        // A workspace channel can hold several of your users.
        members: [
            chMember(1, { type: 'agent', name: 'planner', agent_id: PLANNER.id }),
            chMember(2, { type: 'agent', name: 'support-bot', agent_id: SUPPORT.id }),
            chMember(3, { type: 'user', name: ANA.id, user_id: ANA.id }),
        ],
        created_at: ago(9 * DAY),
    },
    {
        object: 'channel',
        id: cid(2),
        name: 'alerts',
        mode: 'all',
        status: 'open',
        halt_reason: null,
        max_agent_turns: 6,
        max_mention_hops: 2,
        budget_usd: 5,
        spent_usd: 0.88,
        agent_turns_since_human: 2,
        user_id: null,
        workspace_id: LAUNCH_WORKSPACE.id,
        members: [chMember(4, { type: 'agent', name: 'support-bot', agent_id: SUPPORT.id }), chMember(5, { type: 'agent', name: 'coder', agent_id: CODER.id })],
        created_at: ago(8 * DAY),
    },
];
export const [LAUNCH_OCT_CHANNEL, ALERTS_CHANNEL] = WORKSPACE_CHANNELS;

const message = (n: number, channelId: unknown, author: Json, text: string, at: number, fields: Json = {}) => ({
    object: 'channel_message',
    id: fixtureId(0, 140_100 + n),
    channel_id: channelId,
    author,
    text,
    mentions: [],
    created_at: ago(at),
    ...fields,
});

/** What the Launch team's channels say; in #alerts, apps post what they were subscribed to. */
export const WORKSPACE_CHANNEL_MESSAGES = [
    message(1, LAUNCH_OCT_CHANNEL.id, { type: 'user', id: ANA.id, name: ANA.id }, "@planner how's the launch looking?", 12 * MIN),
    message(2, LAUNCH_OCT_CHANNEL.id, { type: 'agent', id: PLANNER.id, name: 'planner' }, 'Research is two-thirds done, and the announcement is waiting for ops to approve the press email.', 9 * MIN),
    message(
        5,
        ALERTS_CHANNEL.id,
        { type: 'app', id: null, name: 'deploys' },
        'A POST to deploys: the web deploy of 9f3e2c1 failed at its health check.',
        3 * HOUR,
        { subscription_id: sid(2), event: { service: 'web', status: 'failed', sha: '9f3e2c1', stage: 'health_check' } }
    ),
    message(
        3,
        ALERTS_CHANNEL.id,
        { type: 'app', id: null, name: 'Stripe' },
        'Stripe: invoice.payment_failed. Invoice INV-1042 for Acme Corp ($95.00) failed: the card was declined. Customer cus_Q8fT2kLm.',
        25 * MIN,
        { subscription_id: sid(1), event: { type: 'invoice.payment_failed', data: { object: { id: 'in_1Q8fT2', number: 'INV-1042', amount_due: 9500, customer: 'cus_Q8fT2kLm' } } } }
    ),
    message(4, ALERTS_CHANNEL.id, { type: 'agent', id: SUPPORT.id, name: 'support-bot' }, "I emailed Acme's billing contact a link to update the card.", 24 * MIN),
];

// ── subscriptions ──────────────────────────────────────────────────────────

function subscription(n: number, fields: Json): Json {
    return {
        object: 'subscription',
        id: sid(n),
        channel_id: null,
        workspace_id: null,
        channels: null,
        wake: null,
        filters: {},
        status: 'active',
        error: null,
        url: null,
        last_event_at: null,
        created_at: ago(7 * DAY),
        ...fields,
    };
}

export const SUBSCRIPTIONS: Json[] = [
    subscription(1, {
        channel_id: ALERTS_CHANNEL.id,
        source: { kind: 'event', connection: 'stripe', event: 'invoice.payment_failed', filters: {} },
        wake: [SUPPORT.id],
        last_event_at: ago(25 * MIN),
    }),
    subscription(2, {
        channel_id: ALERTS_CHANNEL.id,
        source: { kind: 'webhook', name: 'deploys', message: 'A deploy finished.' },
        filters: { status: 'failed' },
        url: 'https://hooks.noclick.app/s/sub_4kQz8vN2pL7xR3',
        last_event_at: ago(3 * HOUR),
    }),
    subscription(3, {
        channel_id: ALERTS_CHANNEL.id,
        source: { kind: 'platform', type: 'operation.failed' },
        filters: { kind: 'agent.message' },
        wake: 'all',
        last_event_at: ago(50 * MIN),
    }),
    subscription(4, {
        channel_id: ACME_LAUNCH_CHANNEL_ID,
        source: { kind: 'event', connection: 'hubspot', event: 'contact_created', filters: {} },
        wake: 'all',
        status: 'error',
        error: "Acme has no connection named hubspot, so no events arrive. Create it and they start.",
        created_at: ago(2 * DAY),
    }),
    // Workspace-wide: every Launch team channel hears about a broken connection.
    subscription(5, {
        workspace_id: LAUNCH_WORKSPACE.id,
        channels: 'all',
        source: { kind: 'platform', type: 'connection.disconnected' },
        last_event_at: ago(4 * DAY),
    }),
];

// ── routes ─────────────────────────────────────────────────────────────────

function csv(query: URLSearchParams, name: string): string[] | null {
    const value = query.get(name);
    return value ? value.split(',').filter(Boolean) : null;
}

const LIVE_STATUSES = ['queued', 'running', 'awaiting_human'];

function jobsOf(r: FixtureRequest): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    if (r.set !== 'populated' || r.params.id !== PLANNER.id) return list([]);
    const statuses = csv(r.query, 'status')?.flatMap((s) => (s === 'live' ? LIVE_STATUSES : [s]));
    const kinds = csv(r.query, 'kind');
    const rows = PLANNER_JOBS.filter(
        (j) =>
            (!statuses || statuses.includes(String(j.status))) &&
            (!kinds || kinds.includes(String(j.kind))) &&
            (!r.query.get('agent_id') || j.agent_id === r.query.get('agent_id')) &&
            (!r.query.get('conversation') || j.parent_conversation === r.query.get('conversation'))
    );
    return list(rows);
}

const allWakeups = () => [...WAKEUPS, ...SHARED_WAKEUPS];

function wakeupsOf(r: FixtureRequest): FixtureReply {
    if (r.set === 'error') return PAGE_ERROR;
    const statuses = csv(r.query, 'status');
    // `user_id` names whose threads; without it, the acting user's (the header), else the account's.
    const inThread = (w: Json) => (r.query.get('user_id') !== null ? userMatches(r.query, w.user_id) : w.user_id === r.headers.get('NoClick-User'));
    const rows = (r.set === 'populated' ? allWakeups() : []).filter(
        (w) =>
            w.agent_id === r.params.id &&
            inThread(w) &&
            (!statuses || statuses.includes(String(w.status))) &&
            (!r.query.get('conversation') || w.conversation === r.query.get('conversation'))
    );
    return list(rows);
}

function cancelWakeup(r: FixtureRequest): FixtureReply {
    const row = allWakeups().find((w) => w.id === r.params.wakeup && w.agent_id === r.params.id);
    if (!row) return apiError(404, 'not_found', 'No such wake-up.');
    if (row.status !== 'pending') return apiError(409, 'conflict', `This wake-up is already ${String(row.status)}.`, 'Only a pending wake-up can be canceled.');
    return ok({ ...row, status: 'canceled' });
}

function createWakeup(r: FixtureRequest): FixtureReply {
    const body = (r.body ?? {}) as Json;
    const at = typeof body.at === 'string' ? body.at : typeof body.after_s === 'number' ? iso(body.after_s * 1000) : null;
    return ok(wakeup(99, { agent_id: r.params.id, user_id: r.headers.get('NoClick-User'), source: 'code', status: 'pending', note: String(body.note ?? ''), conversation: body.conversation, at, when: body.when ?? null, created_at: iso(0) }));
}

const channelSubscriptions = (channelId: string) => SUBSCRIPTIONS.filter((s) => s.channel_id === channelId);

/** A workspace's own reads honour the same `user_id` filter as every list. */
function userMatches(query: URLSearchParams, rowUserId: unknown): boolean {
    const filter = query.get('user_id');
    if (filter === 'all') return true;
    if (filter === null || filter === 'none') return rowUserId === null;
    return filter === rowUserId;
}

const workspaceOf = (id: string) => WORKSPACES.find((w) => w.id === id);

export const routes: readonly FixtureRoute[] = [
    { method: 'GET', path: '/v1/agents/:id/wakeups', reply: wakeupsOf },
    { method: 'POST', path: '/v1/agents/:id/wakeups', reply: createWakeup },
    {
        method: 'GET',
        path: '/v1/agents/:id/wakeups/:wakeup',
        reply: (r) => {
            const row = allWakeups().find((w) => w.id === r.params.wakeup && w.agent_id === r.params.id);
            return row ? ok(row) : apiError(404, 'not_found', 'No such wake-up.');
        },
    },
    { method: 'POST', path: '/v1/agents/:id/wakeups/:wakeup/cancel', reply: cancelWakeup },
    { method: 'GET', path: '/v1/agents/:id/jobs', reply: jobsOf },
    { method: 'POST', path: '/v1/agents/:id/ask', reply: askReply },
    {
        method: 'GET',
        path: '/v1/operations/:id/updates',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : list(JOB_UPDATES[r.params.id] ?? [])),
    },
    {
        method: 'GET',
        path: '/v1/channels/:id/subscriptions',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : list(r.set === 'populated' ? channelSubscriptions(r.params.id) : [])),
    },
    {
        method: 'DELETE',
        path: '/v1/channels/:id/subscriptions/:sub',
        reply: (r) =>
            channelSubscriptions(r.params.id).some((s) => s.id === r.params.sub)
                ? ok({ object: 'subscription', id: r.params.sub, deleted: true })
                : apiError(404, 'not_found', 'No such subscription on this channel.'),
    },
    {
        method: 'GET',
        path: '/v1/workspaces',
        reply: (r) => {
            const status = r.query.get('status');
            const name = r.query.get('name');
            return pageList(r, WORKSPACES.filter((w) => userMatches(r.query, w.user_id) && (!status || w.status === status) && (!name || w.name === name)));
        },
    },
    {
        method: 'GET',
        path: '/v1/workspaces/:id',
        reply: (r) => {
            const row = workspaceOf(r.params.id);
            return row ? ok(row) : apiError(404, 'not_found', `No workspace ${r.params.id}.`);
        },
    },
    {
        method: 'GET',
        path: '/v1/workspaces/:id/subscriptions',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : list(r.set === 'populated' ? SUBSCRIPTIONS.filter((s) => s.workspace_id === r.params.id) : [])),
    },
    {
        method: 'DELETE',
        path: '/v1/workspaces/:id/subscriptions/:sub',
        reply: (r) =>
            SUBSCRIPTIONS.some((s) => s.workspace_id === r.params.id && s.id === r.params.sub)
                ? ok({ object: 'subscription', id: r.params.sub, deleted: true })
                : apiError(404, 'not_found', 'No such subscription on this workspace.'),
    },
];
