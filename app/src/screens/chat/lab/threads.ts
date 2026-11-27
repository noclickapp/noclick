// What the Chat lab's own scenes hold, beside the threads captured from accounts (fixtures/): a conversation that came
// in by every way into it, a turn still at work, the memories NoClick keeps and the files sent to it. Times are minutes
// before the lab's moment (CLOCK), which a screenshot fixes the browser's clock at.
import type { LiveEvent } from '../fixtures/coordinatorAgent';

type Json = Record<string, unknown>;

/** The moment the lab's scenes are set at (the newest captured thread's morning). */
export const CLOCK = '2026-11-12T10:00:00.000Z';
const at = (minutes: number) => new Date(Date.parse(CLOCK) - minutes * 60_000).toISOString();

/** The automation being set up in the morning's conversation (its setup card is its host's). */
export const SETUP_WORKFLOW = 'wf-setup';

/** A morning's conversation from everywhere it reaches NoClick: a text, a call, an email, NoClick's own notes and its
 *  look at a failed run (folded into what it handled), a space's news, an automation being set up from the MCP page,
 *  and a file it made. */
export const CHANNELS_HISTORY: Json[] = [
    { role: 'user', text: 'Are we open Saturday?', created_at: at(300), via: 'whatsapp' },
    { role: 'assistant', text: 'Yes, 9 to 3 this Saturday.', created_at: at(299) },
    { role: 'user', text: 'Book the van for Friday morning', created_at: at(240), via: 'call' },
    { role: 'assistant', text: 'Booked for Friday at 8.', created_at: at(239) },
    { role: 'user', text: 'Thanks, that’s all', created_at: at(238), via: 'call' },
    { role: 'assistant', text: 'Anytime.', created_at: at(238) },
    { role: 'user', text: '[email, subject: Invoice 1042]\nIs this one paid?', created_at: at(200), via: 'email' },
    { role: 'assistant', text: 'It is: paid on the 3rd, by card.', created_at: at(199) },
    { role: 'note', text: 'The nightly backup of Bakery orders ran: 1,204 rows saved.', created_at: at(170) },
    {
        role: 'user',
        text: 'A workflow failed a run.',
        created_at: at(160),
        operation_id: 'op-triage',
        trigger: { kind: 'platform', id: 'ev-1', event: { id: 'ev-1', type: 'workflow.run.failed', data: { workflow_id: 'wf-orders', workflow_name: 'Bakery orders' } } },
    },
    { role: 'assistant', text: 'Bakery orders failed once on a Gmail timeout; the next run went through, so nothing needs you.', created_at: at(159), operation_id: 'op-triage' },
    { role: 'note', text: 'Your Morning brief went out on WhatsApp at 8:00.', created_at: at(120) },
    { role: 'assistant', text: 'The spring menu is live in every channel.', created_at: at(100), notification: true, space: { workspace_id: 'ws_bakery', name: 'bakery', label: 'NoClick · Bakery team' } },
    { role: 'note', text: 'Let’s finish setting up Confluence + Monday.com.', created_at: at(90), data: { setup: { kind: 'mcp', workflow_id: SETUP_WORKFLOW, client: 'opencode' } } },
    { role: 'user', text: 'Make me a price list I can print', created_at: at(30) },
    {
        role: 'assistant',
        text: 'Here it is: one page, the spring menu’s prices.',
        created_at: at(29),
        files: [{ id: 'att-prices', name: 'price-list.pdf', mime_type: 'application/pdf', size_bytes: 48213, url: 'https://files.test/price-list.pdf' }],
    },
];

const CHANNEL_TURN = 'op-channel-turn';
/** The connect link NoClick made in #noclick's turn, whose page the hosted lab answers as Stripe's request. */
export const STRIPE_LINK = 'https://noclick.com/credential/provide/stripe-link-4f2a9c1e7b3d';

/** A turn #noclick's posts started, kept as a channel's turn is (the posts it was handed, a pin notice from the night
 *  before among them), where NoClick made a link to connect Stripe: drawn as the channel showed it, the link's row
 *  under its reply. */
export const CHANNEL_TURN_HISTORY: Json[] = [
    {
        role: 'user',
        text: 'You are @NoClick in the channel "noclick" (channel_id ch_noclick). Other members: none.\nNew messages since your last turn:\n\nNoClick: owner pinned a message to this channel.\nowner: help me connect my stripe account\n\nReply with your message to the channel: your reply is posted for you, so never post it yourself too.',
        created_at: at(25),
        operation_id: CHANNEL_TURN,
        chat: 'channel:ch_noclick',
        channel: {
            id: 'ch_noclick',
            name: 'noclick',
            space: null,
            thread: null,
            posts: [
                { id: 'p-pin', author: { type: 'system', id: null, name: 'NoClick' }, text: 'owner pinned a message to this channel.', created_at: at(475), thread_id: null, files: [] },
                { id: 'p-ask', author: { type: 'account', id: null, name: 'owner' }, text: 'help me connect my stripe account', created_at: at(25), thread_id: null, files: [] },
            ],
        },
    },
    {
        role: 'assistant',
        text: `I found your Stripe connection and created a link to connect it. Open this link and authorize Stripe:\n\n${STRIPE_LINK}`,
        created_at: new Date(Date.parse(at(25)) + 22_000).toISOString(),
        operation_id: CHANNEL_TURN,
        tool_calls: [
            { tool: 'noclick__search', arguments: { query: 'connect Stripe' }, result: '{"success": true, "results": []}', is_error: false, created_at: at(25) },
            {
                tool: 'noclick__api_call',
                arguments: { operation: 'connections_list' },
                result: '{"success": true, "response": {"object": "list", "data": [{"object": "connection", "id": "conn-stripe", "name": "stripe", "status": "pending"}]}}',
                is_error: false,
                created_at: at(25),
            },
            {
                tool: 'noclick__api_call',
                arguments: { operation: 'connections_connect_link_create', arguments: { ref: 'stripe' } },
                result: JSON.stringify({ operation_id: 'op-stripe-link', status: 'awaiting_human', success: true, response: { object: 'connect_link', url: STRIPE_LINK, credential_type: 'stripe_oauth' } }),
                is_error: false,
                created_at: at(25),
            },
        ],
    },
];

const RUN = 'op-run';

/** A turn still at work: the person's message, what NoClick has said and done so far, and its operation running. */
export const WORKING: { history: Json[]; streamed: LiveEvent[]; operations: Json[] } = {
    history: [{ role: 'user', text: 'Can you build a small website for my flower shop?', created_at: at(2), operation_id: RUN }],
    streamed: [
        { type: 'text', text: 'On it. ', operation_id: RUN },
        { type: 'tool_call', tool: 'noclick__api_call', arguments: { operation: 'projects_create' }, operation_id: RUN },
        { type: 'tool_result', tool: 'noclick__api_call', result: '{"project": "juniper-stems"}', operation_id: RUN },
        { type: 'tool_call', tool: 'noclick__api_call', arguments: { operation: 'repos_files_put' }, operation_id: RUN },
    ],
    operations: [{ object: 'operation', id: RUN, kind: 'agent.message', status: 'running', created_at: at(2), updated_at: at(1) }],
};

/** What NoClick remembers, as its memory lists it. */
export const MEMORIES: Json[] = [
    { name: 'reach', description: 'How Maya likes to be reached', content: 'WhatsApp before 9, email after. Never call on Sundays.', updated_by: 'agent', updated_at: at(60 * 24 * 3), conversation: 'owner' },
    { name: 'bakery-hours', description: 'Morrow Bakery’s opening hours', content: 'Mon to Sat 9 to 6, Sunday closed. Saturdays in winter: 9 to 3.', updated_by: 'console', updated_at: at(60 * 24 * 9), conversation: null },
    { name: 'suppliers', description: 'Who supplies what, and when to order', content: 'Flour from Hartwell Mills, ordered Mondays. Butter from Dale Farm, Thursdays.', updated_by: 'agent', updated_at: at(60 * 24 * 20), conversation: 'owner' },
];

/** Files sent to NoClick before, as the account's attachments list them. */
export const FILES: Json[] = [
    { object: 'attachment', id: 'res-menu', name: 'spring-menu.pdf', mime_type: 'application/pdf', size_bytes: 182_044, kind: 'file', url: 'https://files.test/spring-menu.pdf', created_at: at(60 * 24) },
    { object: 'attachment', id: 'res-q3', name: 'q3-sales.csv', mime_type: 'text/csv', size_bytes: 9_120, kind: 'file', url: 'https://files.test/q3-sales.csv', created_at: at(60 * 24 * 6) },
    { object: 'attachment', id: 'res-lease', name: 'lease-renewal.docx', mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', size_bytes: 33_400, kind: 'file', url: 'https://files.test/lease-renewal.docx', created_at: at(60 * 24 * 12) },
];
