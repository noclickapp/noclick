// @vitest-environment jsdom

// A trigger-started turn in the agent chat renders as the event it was — the
// run popup's native frame — and never as the agent's standing instructions
// or a payload dump. An event no frame fits shows the agent's concise text
// with the sanitized payload behind a disclosure.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TriggerEventMessage } from '~/components/chat/TriggerEventMessage';
import { setNodeIconData } from '~/lib/nodeIconRegistry';

afterEach(cleanup);

const slackOutput = {
    type: 'slack',
    action: 'on_channel_message',
    status: 'success',
    data: {
        token: 'verification-secret',
        authorizations: [{ user_id: 'U0BOT', is_bot: true }],
        event: { type: 'message', text: 'can someone look at <https://x.example|the doc>?', user: 'U1', channel: 'C1', ts: '1789060263.695389' },
    },
    channel_label: '#support',
};

describe('TriggerEventMessage', () => {
    it('frames a Slack message natively and keeps the envelope out of the DOM', () => {
        const { container } = render(
            <TriggerEventMessage
                trigger={{ nodeId: 's1', nodeType: 'automation-slack', label: 'Support', operation: 'on_channel_message', output: slackOutput }}
                text="Slack message from U1 in #support [channel C1]:\ncan someone look at the doc?"
            />
        );
        expect(screen.getByTestId('agent-chat-trigger-message')).toBeTruthy();
        expect(container.textContent).toContain('#support');
        expect(container.textContent).toContain('can someone look at the doc?');
        expect(container.textContent).not.toContain('verification-secret');
        expect(container.textContent).not.toContain('authorizations');
        // The caption names the node and its operation, not the agent's instructions.
        expect(container.textContent).toContain('Support');
    });

    it("shows the agent's concise text with the body behind a toggle when no frame fits", () => {
        const { container } = render(
            <TriggerEventMessage
                trigger={{
                    nodeId: 'w1',
                    nodeType: 'trigger-webhook',
                    label: 'Orders hook',
                    output: { order: { id: 7, total: '42.00' }, _webhook: { headers: { authorization: 'Bearer secret' } } },
                }}
                text={'Webhook POST received:\n{\n  "order": {\n    "id": 7,\n    "total": "42.00"\n  }\n}'}
            />
        );
        expect(container.textContent).toContain('Webhook POST received');
        expect(container.querySelector('pre')).toBeNull();
        fireEvent.click(screen.getByTestId('agent-chat-trigger-raw-toggle'));
        const raw = container.querySelector('pre')?.textContent ?? '';
        expect(raw).toContain('"total": "42.00"');
        expect(raw).not.toContain('Bearer secret');
    });

    it("leads the caption with the app's own mark and name once the icon registry is loaded", () => {
        const { container: bare } = render(
            <TriggerEventMessage
                trigger={{ nodeId: 'd1', nodeType: 'automation-discord', label: 'Community server', operation: 'on_message', output: {} }}
                text="Discord message"
            />
        );
        // Unloaded registry: the trigger bolt, node label + operation.
        expect(screen.getByTestId('agent-chat-trigger-caption').textContent).toBe('Community server · On message');
        expect(bare.querySelector('svg.lucide-zap')).toBeTruthy();
        cleanup();
        setNodeIconData({
            'automation-discord': {
                type: 'automation-discord',
                label: 'Discord',
                description: '',
                iconColor: '#5865F2',
                iconHtml: '<svg data-brand="discord"></svg>',
                dimensions: { width: 1, height: 1, iconSize: 1 },
            },
        });
        const { container } = render(
            <TriggerEventMessage
                trigger={{ nodeId: 'd1', nodeType: 'automation-discord', label: 'Community server', operation: 'on_message', output: {} }}
                text="Discord message"
            />
        );
        expect(screen.getByTestId('agent-chat-trigger-caption').textContent).toBe('Discord · Community server · On message');
        expect(container.querySelector('svg[data-brand="discord"]')).toBeTruthy();
        expect(container.querySelector('svg.lucide-zap')).toBeNull();
    });

    it('drops a label that merely repeats the node type (an unlabelled trigger)', () => {
        render(
            <TriggerEventMessage
                trigger={{ nodeId: 'w1', nodeType: 'automation-whatsapp', label: 'automation-whatsapp', operation: 'receive_message', output: {} }}
                text="WhatsApp message"
            />
        );
        expect(screen.getByTestId('agent-chat-trigger-caption').textContent).toBe('Receive message');
    });

    it('offers no payload toggle for an event with nothing but routing ids (a schedule tick)', () => {
        const { container } = render(
            <TriggerEventMessage
                trigger={{
                    nodeId: 'c1',
                    nodeType: 'trigger-cron',
                    label: 'Every morning',
                    output: { schedule_id: 's', triggered_at: '2026-09-12T01:00:00Z', payload: { source: 'cron_trigger', node_id: 'c1' } },
                }}
                text="Scheduled run fired at 2026-09-12T01:00:00Z"
            />
        );
        expect(container.textContent).toContain('Scheduled run fired at 2026-09-12T01:00:00Z');
        expect(screen.queryByTestId('agent-chat-trigger-raw-toggle')).toBeNull();
    });
});
