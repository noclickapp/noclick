// @vitest-environment jsdom
// Email in the coordinator's thread: the owner's email reads as an email (subject, from, to, what they wrote), and
// NoClick's reply says where it was emailed and how far it got, from the receipt saved on the reply and the
// coordinator:email_reply frames that move it (fed here exactly as the relay delivers them). A reply saved before
// receipts says only that it was emailed, never a state.
import { act, cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { CoordinatorTranscript } from '~/components/coordinator/CoordinatorTranscript';
import { persistedEventsToChatMessages, type AgentChatMessage } from '~/hooks/useAgentChat';
import type { CoordinatorEmailReply } from '~/types/socket-events.generated';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

const OWNER = 'dhruv@gmail.com';
const ADDRESS = 'dhruv@noclick.email';
const ROOM = 'coordinator:00000000-0000-0000-0000-000000000001';

let socket: MockSocket;
let teardown: () => void;

beforeEach(() => {
    ({ socket, teardown } = installMockSocket());
});
afterEach(() => {
    cleanup();
    teardown();
});

const asked: AgentChatMessage = {
    isUser: true,
    text: '[email, subject: Hey]\nHey just checking if you can see this',
    isComplete: true,
    channel: 'email',
    email: { from: OWNER, to: ADDRESS, subject: 'Hey' },
};

function reply(receipt?: Partial<CoordinatorEmailReply>, sentAt = Date.now()): AgentChatMessage {
    return {
        isUser: false,
        text: 'Yes, I can see your email.',
        isComplete: true,
        channel: 'email',
        sentAt,
        emailReply: receipt ? { id: 'r1', state: 'sending', to: OWNER, ...receipt } : undefined,
    };
}

function show(messages: AgentChatMessage[]) {
    return render(<CoordinatorTranscript isStreaming={false} errorReason={null} messages={messages} />);
}

const receipt = () => screen.getByTestId('coordinator-email-receipt');
const SENT = { state: 'sent' as const, subject: 'Re: Hey', at: '2026-10-12T20:09:49Z', message_id: 'abc@noclick.email' };

async function frame(update: Partial<CoordinatorEmailReply>) {
    const data = { type: 'coordinator:email_reply', conversation_id: ROOM, reply: { id: 'r1', to: OWNER, state: 'sending', ...update } };
    await act(async () => socket.serverEmit('coordinator:email_reply', data as never));
}

describe('email in the coordinator thread', () => {
    it('reads a saved email turn and its reply with their header and receipt', () => {
        const [user, assistant] = persistedEventsToChatMessages([
            { role: 'user', message: asked.text, channel: 'email', email: { from: OWNER, to: ADDRESS, subject: 'Hey' } },
            { role: 'assistant', message: 'Yes, I can see your email.', channel: 'email', email_reply: { id: 'r1', state: 'sent', to: OWNER, subject: 'Re: Hey' } },
        ]);
        expect(user.email).toEqual({ from: OWNER, to: ADDRESS, subject: 'Hey' });
        expect(user.emailReply).toBeUndefined();
        expect(assistant.emailReply).toEqual({ id: 'r1', state: 'sent', to: OWNER, subject: 'Re: Hey' });
        expect(assistant.email).toBeUndefined();
    });

    it('draws your email with its subject, who it was from and to, and what you wrote', () => {
        show([asked]);
        const email = screen.getByTestId('coordinator-email-message');
        expect(within(email).getByRole('heading').textContent).toBe('Hey');
        expect(within(email).getAllByText(/./, { selector: 'dt, dd' }).map((c) => c.textContent)).toEqual(['From', OWNER, 'To', ADDRESS]);
        expect(email.textContent).toContain('Hey just checking if you can see this');
        expect(email.textContent).not.toContain('[email');
    });

    it('draws mail from before addresses were kept with its subject alone', () => {
        show([{ ...asked, email: undefined }]);
        const email = screen.getByTestId('coordinator-email-message');
        expect(within(email).getByRole('heading').textContent).toBe('Hey');
        expect(email.querySelector('dl')).toBeNull();
    });

    it.each([
        ['sending', {}, 'Emailing dhruv@gmail.com', 'Sending', false],
        ['sent', SENT, 'Emailed to dhruv@gmail.com · Re: Hey', 'Sent', true],
        ['delayed', { ...SENT, state: 'delayed' as const, error: '451 4.2.0 Try later' }, 'Emailed to dhruv@gmail.com · Re: Hey', 'Delivery delayed, retrying', true],
        ['delivered', { ...SENT, state: 'delivered' as const }, 'Emailed to dhruv@gmail.com · Re: Hey', 'Delivered', true],
        ['bounced', { ...SENT, state: 'bounced' as const, error: '550 5.1.1 User unknown' }, 'Emailed to dhruv@gmail.com · Re: Hey', 'Bounced: 550 5.1.1 User unknown', false],
        ['unknown', { state: 'unknown' as const, reason: 'error' as const }, 'Email to dhruv@gmail.com', 'Couldn’t confirm it was sent', false],
    ])('a %s reply says so, and offers your webmail only for mail that is or will be in it', (state, saved, where, said, opens) => {
        show([asked, reply(saved)]);
        expect(receipt().dataset.state).toBe(state);
        expect(receipt().textContent).toContain(where);
        expect(receipt().textContent).toContain(said);
        const open = screen.queryByRole('link', { name: /Open Gmail/ });
        expect(!!open).toBe(opens);
        if (open) {
            expect(open.getAttribute('target')).toBe('_blank');
            expect(decodeURIComponent(new URL(open.getAttribute('href')!).hash)).toBe('#search/rfc822msgid:abc@noclick.email');
        }
        expect(screen.queryByTestId('coordinator-replied-on')).toBeNull();
    });

    it.each([
        ['credits', 'Insufficient credits: 0.00 < 0.01 required', 'your NoClick balance has run out', 'Insufficient credits: 0.00 < 0.01 required'],
        ['send_failed', 'Cloudflare email send failed: rate limited', 'the mail service refused it', 'Cloudflare email send failed: rate limited'],
        ['no_address', null, 'NoClick has no email address yet', null],
    ] as const)('a reply that never went out (%s) says why in the failure tone', (reason, error, why, title) => {
        show([asked, reply({ state: 'failed', reason, error })]);
        expect(receipt().dataset.state).toBe('failed');
        expect(receipt().textContent).toBe(`Couldn’t send the email: ${why}.`);
        expect(receipt().className).toContain('text-red-600');
        expect(receipt().getAttribute('title')).toBe(title);
        expect(screen.queryByRole('link', { name: /Open/ })).toBeNull();
    });

    it('stops saying sending once a send never reported back', () => {
        show([asked, reply({}, Date.now() - 6 * 60 * 1000)]);
        expect(receipt().dataset.state).toBe('unknown');
    });

    it('moves a reply live as its frames arrive, and never back', async () => {
        show([asked, reply({})]);
        expect(receipt().dataset.state).toBe('sending');
        await frame(SENT);
        expect(receipt().dataset.state).toBe('sent');
        expect(receipt().textContent).toContain('Re: Hey');
        await frame({ ...SENT, state: 'delivered' });
        expect(receipt().dataset.state).toBe('delivered');
        // A late frame, or a read of an older copy, never takes it back.
        await frame({ ...SENT, state: 'delayed' });
        expect(receipt().dataset.state).toBe('delivered');
        // Another reply's frame leaves this one alone.
        await frame({ id: 'r2', state: 'failed', reason: 'credits' });
        expect(screen.getAllByTestId('coordinator-email-receipt')).toHaveLength(1);
        expect(receipt().dataset.state).toBe('delivered');
    });

    it('says where an email NoClick sent you went, or why it never went', () => {
        const messaged = (result: object): AgentChatMessage => ({
            isUser: false,
            text: 'I emailed you the summary.',
            isComplete: true,
            steps: [{ id: 's', kind: 'tool', status: 'completed', startedAt: 0, title: 'Calling message_owner({"text": "Summary", "channel": "email"})', detail: JSON.stringify(result) }],
        });
        show([
            messaged({ success: true, channel: 'email', sent_to: OWNER, subject: 'Your summary', delivery_status: 'queued', message_id: '<m1@noclick.email>' }),
            messaged({ success: false, channel: 'email', reason: 'credits', error: 'Insufficient credits: 0.00 < 0.01 required' }),
            messaged({ success: false, unconfirmed: true, channel: 'email', reason: 'error', sent_to: OWNER, error: 'The mail service didn’t confirm the email (ReadTimeout).' }),
        ]);
        const [sent, refused, unconfirmed] = screen.getAllByTestId('coordinator-email-receipt');
        expect(sent.dataset.state).toBe('sent');
        expect(sent.textContent).toContain('Emailed to dhruv@gmail.com · Your summary');
        expect(decodeURIComponent(new URL(within(sent).getByRole('link', { name: /Open Gmail/ }).getAttribute('href')!).hash)).toBe('#search/rfc822msgid:m1@noclick.email');
        expect(refused.textContent).toBe('Couldn’t send the email: your NoClick balance has run out.');
        // Cut off once it was out, it may have gone: never "couldn't send".
        expect(unconfirmed.dataset.state).toBe('unknown');
        expect(unconfirmed.textContent).toContain('Couldn’t confirm it was sent');
    });

    it('keeps "Replied by email" for a reply saved before receipts, with no state', () => {
        show([asked, reply(undefined)]);
        expect(screen.getByTestId('coordinator-replied-on').textContent).toBe('Replied by email');
        expect(screen.queryByTestId('coordinator-email-receipt')).toBeNull();
    });
});
