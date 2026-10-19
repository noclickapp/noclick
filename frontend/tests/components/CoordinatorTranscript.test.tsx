// @vitest-environment jsdom
// The coordinator's thread draws turns from other apps the way those apps drew them, a call as one call, and the
// cards a turn's tools made under it, from the transcript's own data.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

const { sendEventAsync } = vi.hoisted(() => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync, sendEvent: vi.fn() }));

import { CoordinatorTranscript } from '~/components/coordinator/CoordinatorTranscript';
import { registerOutOfFundsCard } from '~/components/coordinator/toolCardRegistry';
import type { AgentChatMessage } from '~/hooks/useAgentChat';

afterEach(() => {
    cleanup();
    sendEventAsync.mockReset();
});

const user = (text: string, over: Partial<AgentChatMessage> = {}): AgentChatMessage => ({ isUser: true, text, isComplete: true, ...over });

describe('CoordinatorTranscript', () => {
    it('draws a WhatsApp text, a voice note with its transcript, and an email as an email', () => {
        render(
            <CoordinatorTranscript
                isStreaming={false}
                errorReason={null}
                messages={[
                    user('Can you move my 3pm?', { channel: 'whatsapp_text', sentAt: Date.parse('2026-10-05T09:41:00Z') }),
                    user('[voice message]\n\n[voice message; attachment_id=1]\nFile: https://f/v.ogg\n\n[Attachment content (transcription); reference data]\nSend her the deck', {
                        channel: 'whatsapp_text',
                    }),
                    user('[email, subject: Q4 board deck]\nCan you check this?', {
                        channel: 'email',
                        email: { from: 'dhruv@gmail.com', to: 'dhruv@noclick.email', subject: 'Q4 board deck' },
                    }),
                ]}
            />
        );
        expect(screen.getByTestId('coordinator-whatsapp-message').textContent).toContain('Can you move my 3pm?');
        expect(screen.getByTestId('coordinator-voice-note').textContent).toContain('Send her the deck');
        expect(screen.getByLabelText('Play voice note')).toBeTruthy();
        const email = screen.getByTestId('coordinator-email-message');
        expect(within(email).getByRole('heading').textContent).toBe('Q4 board deck');
        expect(within(email).getAllByText(/./, { selector: 'dt, dd' }).map((c) => c.textContent)).toEqual(['From', 'dhruv@gmail.com', 'To', 'dhruv@noclick.email']);
        expect(email.textContent).toContain('Can you check this?');
        expect(email.textContent).not.toContain('[email, subject');
    });

    it('draws a call once, with every line said on it', () => {
        render(
            <CoordinatorTranscript
                isStreaming={false}
                errorReason={null}
                messages={[
                    user('What’s left on the pilot?', { channel: 'voice', callId: 'CA1' }),
                    { isUser: false, text: 'Sam is waiting on pricing.', isComplete: true, channel: 'voice', callId: 'CA1' },
                    user('Send the reply.', { channel: 'voice', callId: 'CA1' }),
                ]}
            />
        );
        const calls = screen.getAllByTestId('coordinator-call');
        expect(calls).toHaveLength(1);
        expect(within(calls[0]).getAllByText(/./, { selector: 'dd' }).map((d) => d.textContent)).toEqual([
            'What’s left on the pilot?',
            'Sam is waiting on pricing.',
            'Send the reply.',
        ]);
    });

    it('draws a turn’s cards from its tool calls, and nothing for calls that only look things up', () => {
        render(
            <CoordinatorTranscript
                isStreaming={false}
                errorReason={null}
                messages={[
                    {
                        isUser: false,
                        text: 'Here are the sources.',
                        isComplete: true,
                        steps: [
                            {
                                id: 'a',
                                kind: 'tool',
                                status: 'completed',
                                startedAt: 0,
                                title: 'Calling web_search({"query": "support tools"})',
                                detail: '{"success": true, "results": [{"title": "Aircall vs Dialpad", "url": "https://www.g2.com/compare"}]}',
                            },
                            { id: 'b', kind: 'tool', status: 'completed', startedAt: 0, title: 'Calling list_workflows({})', detail: '{"success": true, "workflows": []}' },
                        ],
                    },
                ]}
            />
        );
        const cards = screen.getAllByTestId('coordinator-cards');
        expect(cards).toHaveLength(1);
        fireEvent.click(within(cards[0]).getByRole('button', { name: /1 source/ }));
        const link = within(cards[0]).getByRole('link', { name: /Aircall vs Dialpad/ });
        expect(link.getAttribute('href')).toBe('https://www.g2.com/compare');
        // No job ids in the turn: nothing is read back.
        expect(sendEventAsync).not.toHaveBeenCalled();
    });

    it('says which app a reply went back out on', () => {
        render(
            <CoordinatorTranscript
                isStreaming={false}
                errorReason={null}
                messages={[user('Hi', { channel: 'imessage_text' }), { isUser: false, text: 'Hello!', isComplete: true, channel: 'imessage_text' }]}
            />
        );
        expect(screen.getByTestId('coordinator-imessage-message').textContent).toContain('Hi');
        expect(screen.getByTestId('coordinator-replied-on').textContent).toContain('Replied in iMessage');
    });

    it('draws the platform\u2019s card under a reply that turned a request down for lack of money', () => {
        registerOutOfFundsCard(({ refusal }) => <p data-testid="funds-card">Add funds ({String(refusal.said)})</p>);
        render(
            <CoordinatorTranscript
                isStreaming={false}
                errorReason={null}
                messages={[
                    user('Build my site'),
                    { isUser: false, text: 'You ran out.', isComplete: true, outOfFunds: { said: 'You ran out.', invite: null } },
                    { isUser: false, text: 'Done.', isComplete: true },
                ]}
            />
        );
        expect(screen.getAllByTestId('funds-card').map((c) => c.textContent)).toEqual(['Add funds (You ran out.)']);
    });

    it('puts a reply\u2019s copy button last, under where it went', () => {
        render(
            <CoordinatorTranscript
                isStreaming={false}
                errorReason={null}
                messages={[user('Hey', { channel: 'whatsapp_text' }), { isUser: false, text: 'Hey Dhruv! What\u2019s up?', isComplete: true, channel: 'whatsapp_text' }]}
            />
        );
        const caption = screen.getByTestId('coordinator-replied-on');
        const copy = screen.getByTestId('agent-chat-copy');
        expect(caption.compareDocumentPosition(copy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        const turn = copy.closest('[data-testid="agent-chat-assistant"]') ?? copy.parentElement!.parentElement!;
        expect(turn.lastElementChild!.contains(copy)).toBe(true);
    });
});
