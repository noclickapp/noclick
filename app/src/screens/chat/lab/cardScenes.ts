// What the Chat lab's card scenes hold: a build of an automation (waiting on its question, then done and published)
// and a call held for the owner's approval (a purchase, a deletion), each as the thread keeps the call that started it
// and as /v1 answers the card's reads. A host whose build card reads the builder its own way finds the build's
// automation and its parked question here too (MARKETS).
// Times are minutes before the lab's moment (CLOCK).
import { CLOCK } from './threads';

type Json = Record<string, unknown>;

const at = (minutes: number) => new Date(Date.parse(CLOCK) - minutes * 60_000).toISOString();

export const MARKETS = 'wf-markets';
const MARKETS_BUILD = 'op-build-markets';
export const MARKETS_NAME = 'Portland markets';
const MARKETS_ABOUT = 'Portland markets and food events, every Monday.';

/** The automation the build draws, as the account stores it: a schedule, a search and an email. */
export const MARKETS_GRAPH = {
    nodes: [
        { id: 'schedule', type: 'trigger-cron', position: { x: 0, y: 0 }, config: { label: 'Every Monday at 7' } },
        { id: 'search', type: 'automation-exa', position: { x: 320, y: 0 }, config: { label: 'Find markets and food events', operation: 'search' } },
        { id: 'email', type: 'automation-send-email', position: { x: 640, y: 0 }, config: { label: 'Email me the list', operation: 'send' } },
    ],
    edges: [
        { id: 'e-schedule-search', source: 'schedule', target: 'search' },
        { id: 'e-search-email', source: 'search', target: 'email' },
    ],
};

const DAYS = [
    { id: 'monday', label: 'Monday' },
    { id: 'tuesday', label: 'Tuesday' },
    { id: 'friday', label: 'Friday' },
];
const ASKED = 'Which morning should the list arrive?';
const DAY = { id: 'day', label: 'Day', description: 'The list covers the two weeks after it.', required: true, type: 'selection', options: DAYS };

/** The question the build waits on, as its operation carries it. */
const MARKETS_QUESTION = { id: 'ask-day', title: ASKED, inputs: [DAY], answer_url: 'https://noclick.test/b/link-markets', answerable_from_code: true };
/** The same question as the builder parked it, which its form reads. */
export const MARKETS_ASK = { ask_id: 'ask-day', title: ASKED, inputs: [{ ...DAY, nodeId: 'schedule', credentialType: null }] };

function marketsBuild(status: string, extra: Json = {}): Json {
    return { object: 'operation', id: MARKETS_BUILD, kind: 'workflow.build', summary: `Building ${MARKETS_NAME}`, workflow_id: MARKETS, created_at: at(6), updated_at: at(4), status, ...extra };
}

const MARKETS_HISTORY: Json[] = [
    { role: 'user', text: 'Every Monday at 7am, email me the farmers markets and food events in Portland for the next two weeks.', created_at: at(7) },
    {
        role: 'assistant',
        text: 'I’m building it now.',
        created_at: at(6),
        tool_calls: [
            {
                tool: 'noclick__api_call',
                arguments: { operation: 'workflows_create', arguments: { name: MARKETS_NAME } },
                result: JSON.stringify({
                    success: true,
                    operation_id: MARKETS_BUILD,
                    status: 'running',
                    response: { object: 'workflow', id: MARKETS, name: MARKETS_NAME, description: MARKETS_ABOUT, steps: [], build: marketsBuild('running', { step: 'building' }) },
                }),
                is_error: false,
                created_at: at(6),
            },
        ],
    },
];

/** A build of an automation as /v1 answers its card: its operation waiting on a question (`asking`) or finished with
 *  its app published (`done`), and the automation's graph. */
export function buildScene(state: 'asking' | 'done') {
    const operation =
        state === 'asking'
            ? marketsBuild('awaiting_human', { step: 'asking', question: MARKETS_QUESTION })
            : marketsBuild('succeeded', {
                  finished_at: at(3),
                  result: { object: 'workflow_build', workflow_id: MARKETS, summary: 'Built it.', steps: [], app_url: null, published: { state: 'published', url: 'https://markets.noclick.test' } },
              });
    const graph = { object: 'workflow_graph', workflow_id: MARKETS, version: 3, name: MARKETS_NAME, description: MARKETS_ABOUT, settings: {}, settings_withheld: [], graph: { ...MARKETS_GRAPH, withheld: {} } };
    return { history: MARKETS_HISTORY, operations: [operation], reads: { [`/v1/workflows/${MARKETS}/graph`]: graph } };
}

const HELD_DOMAIN = '6d1c2b8e-4a3f-4c5d-9e7b-1f2a3b4c5d6e';
const HELD_DELETION = '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d';
const EXPIRES = new Date(Date.parse(CLOCK) + 24 * 3_600_000).toISOString();

/** What a held call answered, and the approval its card reads (GET /v1/approvals/{id}). */
function held(id: string, asked: string, approval: Json): { call: Json; approval: Json } {
    const operation = `op-held-${id.slice(0, 8)}`;
    return {
        call: { success: true, status: 'awaiting_approval', approval_id: id, operation_id: operation, summary: asked, price: approval.price, impact: approval.impact, expires_at: EXPIRES, sent_to: ['web'] },
        approval: {
            object: 'approval',
            id,
            status: 'pending',
            action: asked,
            summary: asked,
            subject: null,
            reason: null,
            connection: { kind: 'assistant', name: 'NoClick', grant_id: 'grant-noclick' },
            user_id: null,
            operation_id: operation,
            held_call_status: 'awaiting_approval',
            created_at: at(2),
            expires_at: EXPIRES,
            decided_at: null,
            note: null,
            sent_to: ['web'],
            consent: [],
            ...approval,
        },
    };
}

const PRICE = { amount_usd: 11.25, recurrence: 'yearly', terms: 'Renews every year at $11.25 until you let it go.', renewal: null };
const IMPACT = {
    deletes: 'Deletes the secret old-stripe-key.',
    depends_on_it: ['Agent Bookkeeper reads it'],
    data_lost: ['Its value, which nothing else keeps'],
    stops_billing: [],
    reversible: false,
};

/** A purchase, or a deletion, NoClick asked the owner to approve: the turn that asked, and the approval as /v1 has it. */
export function approvalScene(kind: 'purchase' | 'deletion') {
    const { call, approval } =
        kind === 'purchase'
            ? held(HELD_DOMAIN, 'Buy morrowbakery.com for 1 year', { price: PRICE, impact: null, operation: 'domains_create', method: 'POST', path: '/v1/domains', arguments: { name: 'morrowbakery.com', years: 1 } })
            : held(HELD_DELETION, 'Delete secret old-stripe-key', { price: null, impact: IMPACT, operation: 'secrets_delete', method: 'DELETE', path: '/v1/secrets/sec_old', arguments: {} });
    const tool = kind === 'purchase' ? { tool: 'noclick__buy', arguments: { quote_id: 'qt_domain' } } : { tool: 'noclick__delete', arguments: { ref: 'secret:old-stripe-key' } };
    const history: Json[] = [
        { role: 'user', text: kind === 'purchase' ? 'Get the bakery its own domain' : 'Delete the old Stripe key, we rotated it', created_at: at(3) },
        {
            role: 'assistant',
            text: kind === 'purchase' ? 'morrowbakery.com is $11.25 a year; approve it below and I’ll register it.' : 'That deletion can’t be undone, so it waits for your OK below.',
            created_at: at(2),
            tool_calls: [{ ...tool, result: JSON.stringify(call), is_error: false, created_at: at(2) }],
        },
    ];
    const list = { object: 'list', data: [approval], next_cursor: null };
    return { history, reads: { [`/v1/approvals/${approval.id}`]: approval, '/v1/approvals': list } };
}
