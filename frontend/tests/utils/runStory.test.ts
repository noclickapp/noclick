// Regression pins for the run-results derivation (runStory.ts) — one test per
// failure class found in the first day of prod usage: text-gated sends losing
// media messages, the delivery envelope leaking into "What came in", trigger
// classification, provider nodes masquerading as ran nodes, and the outcome
// framing for bare chat turns.
import { describe, expect, it } from 'vitest';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import {
    buildRunStory,
    deriveLead,
    deriveSends,
    humanizeDiscordMentions,
    humanizeOp,
    humanizeSlackMarkup,
    outcomeModeFor,
    sanitizeEventPayload,
    type AgentInputGroup,
    type StoryNodeResult,
} from '~/components/design/run-results/runStory';
import type { ReplayToolCall } from '~/components/workflow/ReplayToolCallsPanel';

const call = (
    tool: string,
    operation: string,
    args: Record<string, unknown>,
    error?: string
): ReplayToolCall => ({
    agent_node_id: 'agent-1',
    tool_name: tool,
    tool_type: 'node_op',
    provider_node_id: null,
    operation,
    credential_id: null,
    arguments: args,
    result_status: error ? 'error' : 'success',
    error: error ?? null,
    result_preview: error ? null : '{"ok": true}',
    duration_ms: 900,
    timestamp: '2026-08-24T11:20:34Z',
});

const node = (over: Partial<StoryNodeResult>): StoryNodeResult => ({
    nodeId: 'n1',
    nodeType: 'automation-slack',
    label: 'Node',
    status: 'completed',
    output: null,
    isAgent: false,
    toolCalls: [],
    ...over,
});

const CRON_ENVELOPE = {
    schedule_id: 'f772b97e',
    workflow_id: '82583f4e',
    user_id: '26ed5553',
    node_id: 'trigger-cron_ipkc',
    triggered_at: '2026-08-24T10:50:12.567Z',
    payload: { source: 'cron_trigger', node_id: 'trigger-cron_ipkc' },
    _webhook: { id: '77d6bcc1', method: 'POST', headers: {}, query_params: null },
};

describe('deriveSends', () => {
    it('classifies by op name, not by extractable text — a captioned image send counts', () => {
        const sends = deriveSends([
            call('whatsapp__send_image_message', 'send_image_message', {
                to: '12025550107@c.us',
                image_url: 'https://r2.example/report.png',
                caption: 'Dummy report — testing image sending capability.',
            }),
        ]);
        expect(sends).toHaveLength(1);
        expect(sends[0].text).toBe('Dummy report — testing image sending capability.');
        expect(sends[0].media).toEqual({ kind: 'image', url: 'https://r2.example/report.png' });
    });

    it('keeps a captionless media_id send, with the kind inferred from the op', () => {
        const sends = deriveSends([
            call('whatsapp__send_document_message', 'send_document_message', {
                to: '2010@c.us',
                media_id: 'MEDIA123',
            }),
        ]);
        expect(sends).toHaveLength(1);
        expect(sends[0].text).toBeUndefined();
        expect(sends[0].media).toEqual({ kind: 'file' });
    });

    it('still excludes failed calls — they did not go out', () => {
        const sends = deriveSends([
            call('gmail__send_email_message', 'send_email_message', { to: 'a@b.c', body: 'hi' }, '401'),
        ]);
        expect(sends).toHaveLength(0);
    });

    it("maps telegram's camelCase chatId + bare media keys (catalog sweep)", () => {
        const sends = deriveSends([
            call('telegram__send_photo_image', 'send_photo_image', {
                chatId: '123456',
                photo: 'https://cdn.example/pic.jpg',
                caption: 'here you go',
            }),
        ]);
        expect(sends).toHaveLength(1);
        expect(sends[0].to).toBe('123456');
        expect(sends[0].text).toBe('here you go');
        expect(sends[0].media).toEqual({ kind: 'image', url: 'https://cdn.example/pic.jpg' });
    });

    it('maps twilio to_number/body and twitter message_text', () => {
        const sends = deriveSends([
            call('twilio__send_sms_message', 'send_sms_message', {
                to_number: '+15551234',
                body: 'Your code is 123',
            }),
            call('twitter__send_direct_message', 'send_direct_message', {
                participant_id: '99',
                message_text: 'hey there',
            }),
        ]);
        expect(sends.map((x) => [x.to, x.text])).toEqual([
            ['+15551234', 'Your code is 123'],
            ['99', 'hey there'],
        ]);
    });

    it('a discord embed with only a description still frames', () => {
        const sends = deriveSends([
            call('discord__send_embed_message_to_channel', 'send_embed_message_to_channel', {
                channel_id: '42',
                title: 'Deploy done',
                description: 'v2.1 is live',
            }),
        ]);
        expect(sends).toHaveLength(1);
        expect(sends[0].text).toBe('v2.1 is live');
    });

    it('send-named ops with no communicable payload are NOT sends', () => {
        const sends = deriveSends([
            call('http_request__send_http_get_request', 'send_http_get_request', {
                url: 'https://api.example/x',
            }),
            call('whatsapp__send_chat_typing_indicator', 'send_chat_typing_indicator', { to: 'x' }),
            call('stripe__send_invoice', 'send_invoice', { invoice_id: 'in_1' }),
            call('reddit__get_post', 'get_post', { post_id: 'abc' }),
        ]);
        expect(sends).toHaveLength(0);
    });

    it('plain text sends are unchanged', () => {
        const sends = deriveSends([
            call('slack__send_message_to_channel', 'send_message_to_channel', {
                channel: '#orders',
                text: 'heads up',
            }),
        ]);
        expect(sends[0].text).toBe('heads up');
        expect(sends[0].media).toBeUndefined();
    });
});

describe('sanitizeEventPayload', () => {
    it('strips the delivery envelope down to nothing for a schedule tick', () => {
        expect(sanitizeEventPayload(CRON_ENVELOPE)).toEqual({});
    });

    it('keeps user-meaningful payload content, unwrapped', () => {
        const sanitized = sanitizeEventPayload({
            ...CRON_ENVELOPE,
            payload: { order: '#4817', customer: 'Aisha' },
        });
        expect(sanitized).toEqual({ order: '#4817', customer: 'Aisha' });
    });
});

describe('buildRunStory trigger presentation', () => {
    it('a cron trigger renders bare (time, no scenario, no raw dump)', () => {
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [
                node({ nodeId: 'cron', nodeType: 'trigger-cron', label: 'Schedule', output: CRON_ENVELOPE }),
            ],
        });
        expect(story.trigger?.bare).toBeTruthy();
        expect(story.trigger?.bare?.time).toMatch(/^\d{2}:\d{2}$/);
        expect(story.trigger?.scenario).toBeUndefined();
        expect(story.trigger?.event).toBeUndefined();
    });

    it('derives the lead from a payload-wrapped event (real WhatsApp delivery shape)', () => {
        setNodeIconData({
            'automation-whatsapp': { label: 'WhatsApp', triggerOps: ['receive_message'] },
        } as never);
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [
                node({
                    nodeId: 'wa-in',
                    nodeType: 'automation-whatsapp',
                    operation: 'receive_message',
                    output: {
                        event: 'message',
                        payload: {
                            id: 'wamid.X',
                            from: '12025550101@c.us',
                            body: 'Hi — found you through the Northwind ops group.',
                            hasMedia: false,
                        },
                        _data: { raw: true },
                    },
                }),
            ],
        });
        expect(story.trigger?.scenario?.lead.body).toBe(
            'Hi — found you through the Northwind ops group.'
        );
    });

    it('frames a WhatsApp voice note (null body, rehosted media) as a message with playable audio', () => {
        const lead = deriveLead('whatsapp', {
            event: 'message',
            payload: {
                id: 'false_12025550102@lid_3A95',
                timestamp: 1788964423,
                from: '12025550102@lid',
                fromMe: false,
                body: null,
                hasMedia: true,
                media: {
                    url: 'https://assets.example/ff059e24/voice.oga',
                    filename: '3A95025CC465397BA241.oga',
                    mimetype: 'audio/ogg; codecs=opus',
                    size: 15570,
                    rehosted: true,
                    resource_id: 'a225b541',
                },
                location: null,
                vCards: null,
                senderPhone: '12025550102',
            },
        });
        expect(lead).toBeNull(); // the top-level envelope is not the message
        const inner = deriveLead('whatsapp', sanitizeEventPayload({ event: 'message', payload: {
            from: '12025550102@lid', body: null, hasMedia: true, senderPhone: '12025550102',
            media: { url: 'https://assets.example/ff059e24/voice.oga', filename: 'v.oga', mimetype: 'audio/ogg; codecs=opus', rehosted: true },
        } }));
        expect(inner?.media).toEqual({ kind: 'audio', url: 'https://assets.example/ff059e24/voice.oga', name: 'v.oga' });
        expect(inner?.body).toBe('');
        // The phone beats the opaque @lid identity in the bubble header.
        expect(inner?.handle).toBe('12025550102');
    });

    it('keeps a captioned photo as body + image, and never exposes a non-rehosted provider URL', () => {
        const photo = deriveLead('whatsapp', {
            from: '1@c.us', body: 'look at this', hasMedia: true,
            media: { url: 'https://assets.example/x/photo.jpg', mimetype: 'image/jpeg', filename: 'photo.jpg', rehosted: true },
        });
        expect(photo?.body).toBe('look at this');
        expect(photo?.media?.kind).toBe('image');
        expect(photo?.media?.url).toBe('https://assets.example/x/photo.jpg');
        const stale = deriveLead('whatsapp', {
            from: '1@c.us', body: null, hasMedia: true,
            media: { url: 'https://api.wahooks.example/files/abc', mimetype: 'application/pdf', filename: 'invoice.pdf' },
        });
        expect(stale?.media).toEqual({ kind: 'file', url: undefined, name: 'invoice.pdf' });
    });

    it('describes WhatsApp locations and contact cards instead of dropping them', () => {
        const loc = deriveLead('whatsapp', {
            from: '1@c.us', body: null, hasMedia: false,
            location: { latitude: 28.6139, longitude: 77.209, description: 'Connaught Place' },
        });
        expect(loc?.body).toBe('📍 Connaught Place (28.6139, 77.209)');
        const card = deriveLead('whatsapp', {
            from: '1@c.us', body: null, hasMedia: false,
            vCards: ['BEGIN:VCARD\nVERSION:3.0\nFN:Priya Raman\nTEL:+14155550184\nEND:VCARD'],
        });
        expect(card?.body).toBe('👤 Shared contact: Priya Raman');
        // Nothing recognisable still falls through to the raw event.
        expect(deriveLead('whatsapp', { from: '1@c.us', body: null, hasMedia: false, ack: 2 })).toBeNull();
    });

    it('frames a Telegram voice message as an audio chip (file ids have no browser URL)', () => {
        const lead = deriveLead('telegram', sanitizeEventPayload({
            update_id: 1,
            message: {
                message_id: 7,
                from: { first_name: 'Sam', username: 'sam' },
                chat: { id: 42 },
                date: 1788964423,
                voice: { file_id: 'AwACAgIAAxkB', duration: 4, mime_type: 'audio/ogg' },
            },
        }));
        expect(lead?.media).toEqual({ kind: 'audio', name: undefined });
        expect(lead?.body).toBe('');
        const doc = deriveLead('telegram', {
            caption: 'the deck', chat: { id: 42 },
            document: { file_id: 'BQAC', file_name: 'deck.pdf', mime_type: 'application/pdf' },
        });
        expect(doc?.body).toBe('the deck');
        expect(doc?.media).toEqual({ kind: 'file', name: 'deck.pdf' });
    });

    it('classifies a provider-type trigger via registry triggerOps (operation from the graph)', () => {
        setNodeIconData({
            'automation-whatsapp': { label: 'WhatsApp', triggerOps: ['receive_message'] },
        } as never);
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [
                node({
                    nodeId: 'wa-in',
                    nodeType: 'automation-whatsapp',
                    label: 'WhatsApp',
                    operation: 'receive_message',
                    output: { body: 'hi there', sender_name: 'Aisha', from: '+91 98', chat_id: '9198@c.us' },
                }),
            ],
        });
        expect(story.trigger?.nodeId).toBe('wa-in');
        expect(story.trigger?.scenario?.lead.body).toBe('hi there');
        expect(story.supporting).toHaveLength(0);
    });
});

describe('tool providers', () => {
    it('provider-wired nodes become toolkit entries, never "ran" rows', () => {
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [
                node({ nodeId: 'agent-1', nodeType: 'agent', label: 'Agent', isAgent: true, output: { type: 'agent', response: 'done' } }),
                node({
                    nodeId: 'slack-tools',
                    nodeType: 'automation-slack',
                    label: 'Slack',
                    output: {
                        type: 'node_op_tool_provider',
                        node_type: 'automation-slack',
                        allowed_operations: ['send_message_to_channel', 'get_channel_messages'],
                        credential_label: 'Slack — 7/25/2026',
                    },
                }),
                node({ nodeId: 'sheet', nodeType: 'automation-google-sheets', label: 'Log', output: { appended: 1 } }),
            ],
        });
        expect(story.providers).toHaveLength(1);
        expect(story.providers[0].operations).toEqual([
            'send_message_to_channel',
            'get_channel_messages',
        ]);
        expect(story.providers[0].credentialLabel).toBe('Slack — 7/25/2026');
        expect(story.supporting.map((n) => n.nodeId)).toEqual(['sheet']);
    });

    it('humanizes operation names for the toolkit list', () => {
        expect(humanizeOp('send_message_to_channel')).toBe('Send message to channel');
    });
});

describe('outcomeModeFor', () => {
    const agentNode = (over: Partial<StoryNodeResult> = {}) =>
        node({ nodeId: 'a', nodeType: 'agent', label: 'Agent', isAgent: true, output: { type: 'agent', response: 'Hi! How can I help?' }, ...over });

    it('a bare chat turn leads with the reply, not "Nothing went out"', () => {
        const story = buildRunStory({ workflowName: 'Wf', results: [agentNode()] });
        expect(outcomeModeFor(story)).toBe('reply');
    });

    it('an agent that worked and sent nothing is restraint', () => {
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [
                agentNode({ toolCalls: [call('linear__search_issues', 'search_issues', { query: 'x' })] }),
            ],
        });
        expect(outcomeModeFor(story)).toBe('restraint');
    });

    it('sends win when present', () => {
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [
                agentNode({
                    toolCalls: [call('whatsapp__send_image_message', 'send_image_message', { to: 'x', image_url: 'https://a/b.png' })],
                }),
            ],
        });
        expect(outcomeModeFor(story)).toBe('sends');
    });
});

/* A warm agent's finished turn arrives as its own RESPONSE run: the agent
   output is the callback-built package (input_execution_ids, inputs_total),
   and the run's trigger node never fired in it. The 2026-09-02 popup showed
   the trigger's restored last output as "What came in": a "No live event: …"
   envelope from a manual run, later another guest's message. */
describe('response runs (a warm agent turn fired as its own run)', () => {
    const NO_EVENT = {
        status: 'no_event',
        action: 'receive_message',
        data: {},
        message: "No live event: 'receive_message' only carries data when a real delivery fires the workflow.",
    };
    const delivery = (executionId: string, body: string, from = '12025550102@lid') => ({
        executionId,
        status: 'completed',
        output: { event: 'message', payload: { from, body, hasMedia: false } },
    });
    const waGroup = (runs: AgentInputGroup['runs']): AgentInputGroup => ({
        nodeId: 'wa-in',
        nodeType: 'automation-whatsapp',
        operation: 'receive_message',
        label: 'WhatsApp',
        runs,
    });
    const packagedAgent = (ids: string[], inputsTotal = ids.length): StoryNodeResult =>
        node({
            nodeId: 'agent-1',
            nodeType: 'agent',
            label: 'Agent Chat',
            isAgent: true,
            output: {
                type: 'agent',
                status: 'completed',
                response: 'Replied warmly.',
                input_execution_ids: ids,
                inputs_total: inputsTotal,
            },
        });
    // Legacy row: the trigger restored as context before context stopped persisting.
    const restoredTrigger = () =>
        node({ nodeId: 'wa-in', nodeType: 'automation-whatsapp', operation: 'receive_message', output: NO_EVENT });
    const whatsappRegistry = () =>
        setNodeIconData({
            'automation-whatsapp': { label: 'WhatsApp', triggerOps: ['receive_message'] },
            'automation-stripe': { label: 'Stripe', triggerOps: ['payment_received'] },
        } as never);

    it('frames the consumed delivery as "What came in", never the restored trigger', () => {
        whatsappRegistry();
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [packagedAgent(['d1']), restoredTrigger()],
            agentInputs: [waGroup([delivery('d1', 'Hello, how are you?')])],
        });
        expect(story.trigger?.nodeId).toBe('wa-in');
        expect(story.trigger?.scenario?.lead.body).toBe('Hello, how are you?');
        expect(story.trigger?.deliveries).toBe(1);
        expect(story.inputs).toEqual([]); // a lone delivery IS the inbound section
        expect(story.supporting).toHaveLength(0); // the restored trigger is not "Also ran"
    });

    it('shows no inbound event when the deliveries were not retained', () => {
        whatsappRegistry();
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [packagedAgent(['d1']), restoredTrigger()],
            agentInputs: [],
        });
        expect(story.trigger).toBeUndefined();
        expect(story.supporting).toHaveLength(0);
    });

    it('frames the latest of several deliveries and keeps them all in the rail', () => {
        whatsappRegistry();
        const group = waGroup([delivery('d1', 'first'), delivery('d2', 'second, please')]);
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [packagedAgent(['d1', 'd2'])],
            agentInputs: [group],
        });
        expect(story.trigger?.scenario?.lead.body).toBe('second, please');
        expect(story.trigger?.deliveries).toBe(2);
        expect(story.inputs).toEqual([group]);
    });

    it('with several triggers feeding one turn, frames the newest delivery, not the first group', () => {
        whatsappRegistry();
        const stripe: AgentInputGroup = {
            nodeId: 'stripe-in',
            nodeType: 'automation-stripe',
            operation: 'payment_received',
            label: 'Stripe',
            runs: [{ executionId: 'd1', status: 'completed', output: { text: 'paid $40' } }],
        };
        const wa = waGroup([delivery('d2', 'hi'), delivery('d3', 'anyone there?')]);
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [packagedAgent(['d1', 'd2', 'd3'])],
            agentInputs: [stripe, wa], // grouped by first appearance: stripe first
        });
        expect(story.trigger?.nodeId).toBe('wa-in');
        expect(story.trigger?.scenario?.lead.body).toBe('anyone there?');
        expect(story.trigger?.deliveries).toBe(3);
        expect(story.inputs).toEqual([stripe, wa]);
    });

    it('reports the package total when the resolved deliveries are capped', () => {
        whatsappRegistry();
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [packagedAgent(['d40'], 40)],
            agentInputs: [waGroup([delivery('d40', 'last one')])],
        });
        expect(story.trigger?.deliveries).toBe(40);
    });

    it('keys on the packaged agent even when a downstream agent row comes first', () => {
        whatsappRegistry();
        const sdkAgent = node({
            nodeId: 'agent-2',
            nodeType: 'agent',
            label: 'Summariser',
            isAgent: true,
            output: { type: 'agent', status: 'completed', response: 'summary' },
        });
        const story = buildRunStory({
            workflowName: 'Wf',
            results: [sdkAgent, packagedAgent(['d1'])],
            agentInputs: [waGroup([delivery('d1', 'Hello')])],
        });
        expect(story.agent?.nodeId).toBe('agent-1');
        expect(story.trigger?.scenario?.lead.body).toBe('Hello');
    });

    it('a no-event envelope is the trigger explaining itself, never a message', () => {
        whatsappRegistry();
        expect(deriveLead('whatsapp', NO_EVENT)).toBeNull();
        // A manual run of the trigger itself (not a response run).
        const story = buildRunStory({ workflowName: 'Wf', results: [restoredTrigger()] });
        expect(story.trigger?.scenario).toBeUndefined();
        expect(story.trigger?.event).toBeUndefined();
        expect(story.trigger?.notice).toContain('No live event');
    });
});

describe('discord gateway messages', () => {
    const message = {
        event_type: 'on_mention',
        message_id: 'm1',
        content: '<@bot> can you ping <@u2> about the deploy?',
        channel_id: '1545037700548137093',
        channel_name: 'general',
        guild_id: '1545037700548137090',
        guild_name: 'NoClick Sandbox',
        author_id: 'u1',
        author_username: 'dana',
        author_display_name: 'Dana K',
        mentions: [
            { id: 'bot', username: 'noclick', display_name: 'NoClick' },
            { id: 'u2', username: 'sam', display_name: 'Sam' },
        ],
        attachments: [{ url: 'https://cdn/x.png', filename: 'x.png' }],
        sent_at: '2026-09-03T12:34:09.208000+00:00',
        data: { source: 'gateway' },
    };

    it('frames a channel message with names, humanized mentions and attachments', () => {
        const lead = deriveLead('discord', message);
        expect(lead).toMatchObject({
            title: '#general',
            meta: 'NoClick Sandbox',
            author: 'Dana K',
            handle: '@dana',
            body: '@NoClick can you ping @Sam about the deploy?\n📎 x.png',
        });
        expect(lead?.time).toBeTruthy();
    });

    it('falls back to ids when the listener had no names, and to the raw event without text', () => {
        const unnamed = { ...message, channel_name: undefined, guild_name: undefined };
        expect(deriveLead('discord', unnamed)?.title).toBe('#1545037700548137093');
        expect(deriveLead('discord', { ...message, content: '', attachments: [] })).toBeNull();
    });

    it('frames a slash command as its invocation', () => {
        const lead = deriveLead('discord', {
            event_type: 'on_slash_command',
            command_name: 'ask',
            options: { question: 'status?' },
            username: 'dana',
            channel_id: 'c1',
        });
        expect(lead).toMatchObject({ title: '#c1', body: '/ask question: status?', author: 'dana' });
    });

    it('humanizes mention markup on its own', () => {
        expect(humanizeDiscordMentions('<@!1> <@&2> <#3>', [{ id: '1', username: 'sam' }])).toBe('@sam @role #channel');
    });
});

// The Slack trigger's output nests the Events API envelope under `data` and
// the message under `event`; reading `text` off the top level framed NO Slack
// run natively (every one fell back to the JSON view, 2026-09-10).
describe('deriveLead · slack', () => {
    const output = (event: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
        type: 'slack',
        action: 'on_channel_message',
        status: 'success',
        event_type: 'message',
        team_id: 'T1',
        data: { token: 'x', team_id: 'T1', api_app_id: 'A1', type: 'event_callback', event: { type: 'message', ...event } },
        timestamp: 1789060264.1,
        ...extra,
    });
    const lead = (event: Record<string, unknown>, extra?: Record<string, unknown>) => {
        const out = output(event, extra);
        return deriveLead('slack', out) ?? deriveLead('slack', sanitizeEventPayload(out));
    };

    it('frames a channel message from the nested event, by the picked label', () => {
        const l = lead(
            { text: 'hey <@U2|dana> see <https://x.io|the doc>', user: 'U1', channel: 'C1', ts: '1789060263.695389' },
            { channel_label: '#support' }
        )!;
        expect(l.title).toBe('#support');
        expect(l.body).toBe('hey @dana see the doc');
        expect(l.handle).toBe('@U1');
        expect(l.author).toBeUndefined();
        expect(l.time).toMatch(/^\d\d:\d\d$/);
    });

    it('falls back to the channel id and names a system subtype', () => {
        const l = lead({ subtype: 'channel_join', text: '<@U1> has joined the channel', user: 'U1', channel: 'C1', ts: '1' })!;
        expect(l.title).toBe('#C1');
        expect(l.meta).toBe('#C1 · joined the channel');
        expect(l.body).toBe('@U1 has joined the channel');
    });

    it('a bot post is authored by the bot and its attachments are what came in', () => {
        const l = lead({
            subtype: 'bot_message',
            text: ':speech_balloon: Conversation from Ahnaf.',
            bot_id: 'B1',
            username: 'Support desk',
            channel: 'C1',
            ts: '2',
            attachments: [{ fallback: 'Conversation is unresolved. Please reply.' }],
        })!;
        expect(l.author).toBe('Support desk');
        expect(l.handle).toBeUndefined();
        expect(l.body).toBe(':speech_balloon: Conversation from Ahnaf.\nConversation is unresolved. Please reply.');
    });

    it('a thread reply says so, and an empty event is not a lead', () => {
        const l = lead({ text: 'ok', user: 'U1', channel: 'C1', ts: '3.1', thread_ts: '2.0' })!;
        expect(l.meta).toBe('#C1 · in a thread');
        expect(lead({ subtype: 'message_deleted', channel: 'C1', ts: '4' })).toBeNull();
    });

    it('humanizes Slack markup', () => {
        expect(humanizeSlackMarkup('<@U1> <#C1|general> <!here> <https://a.io> &amp; <!subteam^S1|@ops>')).toBe(
            '@U1 #general @here https://a.io & @ops'
        );
    });
});
