// @vitest-environment jsdom
// The coordinator's own notes (a failed run it looked into, an agent that messaged it) fold into one card per run,
// an entry per automation, instead of a wall of near-identical messages.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { CoordinatorTranscript } from '~/components/coordinator/CoordinatorTranscript';
import { UpdatesCard } from '~/components/coordinator/inline/updates';
import { answerLinkOf, entriesOf, headlineOf, updatesOf } from '~/components/coordinator/updates';
import { applyChatMessageEvent, persistedEventsToChatMessages, type AgentChatMessage } from '~/hooks/useAgentChat';

afterEach(cleanup);
// Notes render through the lazily loaded markdown renderer; load its chunk up front, as the Chat page does on open.
beforeAll(() => import('~/components/chat/MarkdownRenderer'), 60_000);

const KEEPALIVE = { kind: 'run_failure' as const, workflow_id: 'wf-keepalive', workflow_name: 'Webhook Keepalive' };
const AGENT = { kind: 'run_failure' as const, workflow_id: 'wf-agent', workflow_name: 'Telegram agent' };

function note(text: string, extra: Partial<AgentChatMessage> = {}): AgentChatMessage {
    return { isUser: false, text, isComplete: true, notification: true, ...extra };
}
const you = (text: string): AgentChatMessage => ({ isUser: true, text, isComplete: true });
const reply = (text: string): AgentChatMessage => ({ isUser: false, text, isComplete: true });

describe('updatesOf', () => {
    it('folds a run of notes, and a lone note only when it is about an automation', () => {
        const messages = [
            note('Your app is built.'), // a lone note about nothing in particular stays a message
            you('Thanks'),
            reply('Anytime.'),
            note('Keepalive timed out.', { signal: KEEPALIVE }), // one note about an automation is a card
            you('ok'),
            note('First.'),
            note('Second.'),
            note('Third.', { signal: AGENT }),
        ];
        const runs = updatesOf(messages);
        expect([...runs.keys()]).toEqual([3, 5, 6, 7]);
        expect(runs.get(3)!.notes.map((n) => n.text)).toEqual(['Keepalive timed out.']);
        expect(runs.get(6)).toBe(runs.get(5));
        expect(runs.get(7)!.start).toBe(5);
    });

    it('never folds an error, a reply or a note carrying media', () => {
        const messages = [
            note('One.'),
            { ...note(''), error: 'Agent stopped' },
            note('Two.'),
            note('A picture', { content: [{ type: 'image_url', image_url: { url: 'https://x.test/a.png' } }] }),
            note('Three.'),
        ];
        expect(updatesOf(messages).size).toBe(0);
    });
});

describe('entriesOf', () => {
    it('keeps one automation’s notes together where its newest note is, newest entry first', () => {
        const entries = entriesOf([
            note('Agent failed.', { signal: AGENT, sentAt: 1 }),
            note('Keepalive timed out.', { signal: KEEPALIVE, sentAt: 2 }),
            note('A note on its own.', { sentAt: 3, turnId: 'coordinator-wakeup:9' }),
            note('Agent failed again.', { signal: AGENT, sentAt: 4 }),
        ]);
        expect(entries.map((e) => [e.automation ?? e.key, e.notes.map((n) => n.text)])).toEqual([
            ['Telegram agent', ['Agent failed.', 'Agent failed again.']],
            ['coordinator-wakeup:9', ['A note on its own.']],
            ['Webhook Keepalive', ['Keepalive timed out.']],
        ]);
    });
});

describe('headlineOf', () => {
    it('reads the opening sentence as plain text without the automation’s name', () => {
        expect(headlineOf('**Telegram agent** failed again at 08:30 UTC. The builder found nothing new.', 'Telegram agent')).toBe(
            'Failed again at 08:30 UTC.'
        );
        expect(headlineOf('**Triage update:**\n\n- **Webhook Keepalive:** waiting on your choice.')).toBe('Triage update: Webhook Keepalive: waiting on your choice.');
        expect(headlineOf('Answer [here](https://noclick.com/b/abc) or at https://noclick.com/b/abc today')).toBe('Answer here or at today');
    });
});

it('finds the builder question a note asks you to answer', () => {
    expect(answerLinkOf('Your pick is needed. Answer link: https://noclick.com/b/e47b5e26-ba5e-4c27\nhttps://noclick.com/b/e47b5e26-ba5e-4c27')).toBe(
        'https://noclick.com/b/e47b5e26-ba5e-4c27'
    );
    expect(answerLinkOf('See https://noclick.com/dashboard')).toBeUndefined();
});

describe('UpdatesCard', () => {
    const now = new Date('2026-10-05T12:00:00');
    const at = (iso: string) => new Date(iso).getTime();
    const entries = entriesOf([
        note('**Telegram agent** failed at 02:30 UTC: its agent did not start.', { signal: AGENT, sentAt: at('2026-10-04T02:32:00') }),
        note('**Webhook Keepalive** needs your pick. Answer link: https://noclick.com/b/abc', { signal: KEEPALIVE, sentAt: at('2026-10-04T09:40:00') }),
        note('**Telegram agent** failed again at 08:30 UTC with the same timeout.', { signal: AGENT, sentAt: at('2026-10-05T08:32:00') }),
    ]);

    it('shows each automation’s latest line, with the question one tap away', async () => {
        render(<UpdatesCard entries={entries} now={now} />);
        const rows = screen.getAllByRole('button', { expanded: false });
        expect(rows.map((r) => r.textContent)).toEqual([
            expect.stringContaining('Telegram agent · 2 updatesFailed again at 08:30 UTC with the same timeout.'),
            expect.stringContaining('Webhook KeepaliveNeeds your pick.'),
        ]);
        expect(screen.getByRole('link', { name: 'Answer' }).getAttribute('href')).toBe('https://noclick.com/b/abc');
        expect(screen.getByText(/^3 updates · /)).toBeTruthy();
        // The notes themselves stay folded until asked for.
        expect(screen.queryByText(/its agent did not start/)).toBeNull();
        fireEvent.click(rows[0]);
        expect(rows[0].getAttribute('aria-expanded')).toBe('true');
        expect(screen.getByText(/its agent did not start/)).toBeTruthy();
        // The note renders as markdown once the renderer's chunk is in (plain text until then).
        expect(await screen.findByText(/the same timeout/, { selector: 'p' })).toBeTruthy();
    });

    it('keeps a long run to its newest entries until asked for all', () => {
        const many = Array.from({ length: 6 }, (_, i) => ({ key: `n${i}`, notes: [{ text: `Update ${i}.`, sentAt: at('2026-10-05T08:00:00') + i }] }));
        render(<UpdatesCard entries={many} now={now} />);
        expect(screen.queryByText('Update 4.')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: /Show all 6/ }));
        expect(screen.getByText('Update 4.')).toBeTruthy();
    });
});

describe('the automation a note is about', () => {
    it('is restored from the transcript and read off a live note', () => {
        const [restored] = persistedEventsToChatMessages([
            { role: 'assistant', message: 'Timed out again.', notification: true, turn_id: 'coordinator-wakeup:1', signal: KEEPALIVE },
        ]);
        expect(restored.signal).toEqual(KEEPALIVE);
        const [live] = applyChatMessageEvent([], {
            message: 'Failed again.',
            finished: true,
            notification: true,
            turn_id: 'coordinator-wakeup:2',
            signal: AGENT,
        });
        expect(live).toMatchObject({ notification: true, signal: AGENT });
        expect(live.sentAt).toBeGreaterThan(0);
    });
});

it('folds a thread of notes written before they named their automation into one card', () => {
    // The persisted shape of a thread whose triage notes came in pairs (a message to the web, then the turn's own
    // note) around a builder question, as they were stored before notes carried their automation.
    const pair = (n: number, text: string) => [
        { role: 'assistant', message: `${text} Answer link: https://noclick.com/b/q${n}\nhttps://noclick.com/b/q${n}`, notification: true, turn_id: `coordinator-message:${n}`, timestamp: `2026-09-2${n}T08:32:00Z` },
        { role: 'assistant', message: `**${text}** I notified you.`, notification: true, turn_id: `coordinator-wakeup:${n}`, coordinator_wakeup_id: `${n}`, timestamp: `2026-09-2${n}T08:32:05Z` },
    ];
    // Raw transcript JSON: it carries keys the chat doesn't read (a wake-up id, a builder question).
    const stored: unknown[] = [
        { role: 'user', message: 'Watch my automations', channel: 'web' },
        { role: 'assistant', message: 'Will do.' },
        ...pair(1, 'Keepalive timed out.'),
        { builder_ask: { link_id: 'q1' }, timestamp: '2026-09-21T09:00:00Z' },
        ...pair(2, 'Keepalive timed out again.'),
        ...pair(3, 'Telegram agent failed again.'),
    ];
    const messages = persistedEventsToChatMessages(stored as Parameters<typeof persistedEventsToChatMessages>[0]);
    render(<CoordinatorTranscript messages={messages} isStreaming={false} errorReason={null} />);
    expect(screen.getAllByTestId('agent-chat-agent-message')).toHaveLength(1); // the reply; every note is in the card
    expect(screen.getByText(/^6 updates · /)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Show all 6/ })).toBeTruthy();
    expect(screen.getAllByRole('link', { name: 'Answer' }).map((a) => a.getAttribute('href'))).toEqual([
        'https://noclick.com/b/q3',
        'https://noclick.com/b/q2',
    ]);
});
