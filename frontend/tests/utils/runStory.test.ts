// Regression pins for the run-results derivation (runStory.ts) — one test per
// failure class found in the first day of prod usage: text-gated sends losing
// media messages, the delivery envelope leaking into "What came in", trigger
// classification, provider nodes masquerading as ran nodes, and the outcome
// framing for bare chat turns.
import { describe, expect, it } from 'vitest';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import {
    buildRunStory,
    deriveSends,
    humanizeOp,
    outcomeModeFor,
    sanitizeEventPayload,
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
