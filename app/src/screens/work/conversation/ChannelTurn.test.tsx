// @vitest-environment happy-dom
// A turn a channel's posts started, drawn as the channel showed it (ChannelTurn) from the message the API keeps: the
// posts with who wrote them, the agent's row saying what it's doing as it works, its reply as it writes it, "Handled
// by" opening its steps, and the text the agent read behind a fold, never as the person's bubble.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentEvent, JsonObject } from 'noclick';
import { toAgentEvent, toMessage } from '@/sdk/source';
import { applyEvent, EMPTY_THREAD, fromHistory, type Thread } from '@/lib/agentThread/thread';
import { WorkProviders } from '../agents/fixtures/providers';
import { fakeWorkAgent } from './fixtures/workAgent';
import { timelineRows } from './Timeline';

afterEach(cleanup);

const AT = Date.parse('2026-11-24T10:00:00Z');
const iso = (s: number) => new Date(AT + s * 1000).toISOString();
const OP = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a11';
const READ = 'You are @Scout in the channel "launch" (channel_id ch_1) of the space "Bakery" (workspace_id ws_1).\nNew messages since your last turn:\n\nPriya: @Scout did the retry fix ship?\n\nReply with your message to the channel.';

const CHANNEL = {
    id: 'ch_1',
    name: 'launch',
    space: { id: 'ws_1', name: 'Bakery' },
    thread: null,
    posts: [
        { id: 'm_1', author: { type: 'user', id: 'login-priya', name: 'Priya' }, text: '@Scout did the retry fix ship?', created_at: iso(-2), thread_id: null, files: [] },
        { id: 'm_2', author: { type: 'account', id: null, name: 'owner' }, text: 'and is it on the preview?', created_at: iso(-1), thread_id: null, files: [{ name: 'notes.txt', mime_type: 'text/plain' }] },
    ],
};
// A reply naming the link its call's card draws (a card, not an ask the turn's result kept), and a link no card draws.
const LINK = 'https://noclick.com/credential/provide/tok-stripe';
const CONNECT = {
    tool: 'noclick__api_call',
    arguments: { operation: 'connections_connect_link_create' },
    result: JSON.stringify({ operation_id: 'op-link', status: 'awaiting_human', success: true, response: { object: 'connect_link', url: LINK, credential_type: 'stripe_oauth' } }),
    is_error: false,
    created_at: iso(2),
};
const LINKED = { id: '3', role: 'assistant', text: `Open this link and authorize Stripe:\n\n${LINK}\n\nThe [docs](https://docs.stripe.com) say more.`, created_at: iso(4), operation_id: OP, tool_calls: [CONNECT] };
const ASKED = { id: '2', role: 'user', text: READ, created_at: iso(0), operation_id: OP, chat: 'channel:ch_1', channel: CHANNEL };

type Frame = JsonObject & { type: string };
const play = (thread: Thread, frames: readonly Frame[]): Thread =>
    frames.map(({ type, ...data }): AgentEvent => toAgentEvent(type, data)).reduce((t, e, i) => applyEvent(t, e, AT + i * 1000), thread);
const history = (...messages: JsonObject[]): Thread => ({ ...EMPTY_THREAD, entries: fromHistory(messages.map(toMessage), AT + 60_000) });

function show(thread: Thread, onOpenChannel?: (id: string, thread?: string) => void) {
    const fake = fakeWorkAgent();
    const face = { id: 'agent-1', kind: 'agent' as const, name: 'Scout', agentId: 'agent-1' };
    const view = render(
        <WorkProviders client={fake.client}>
            <div>
                {timelineRows({
                    thread,
                    mode: 'all',
                    mine: (e) => e.author?.type === 'account' && !e.author.id,
                    onAnswer: () => undefined,
                    agentName: 'Scout',
                    agent: { name: 'Scout', face },
                    onOpenChannel,
                })}
            </div>
        </WorkProviders>
    );
    return { view, card: () => view.container.querySelector<HTMLElement>('[data-row="channel-turn"]')! };
}

describe('a channel turn', () => {
    it('draws the posts it was handed as the channel did, the reply, and the text it read behind a fold', () => {
        const { card } = show(history(ASKED, { id: '3', role: 'assistant', text: 'Yes, it shipped this morning.', created_at: iso(4), operation_id: OP }));
        expect(card().dataset.status).toBe('done');
        expect(card().querySelector('[data-channel-header]')!.textContent).toContain('launch');
        expect(card().querySelector('[data-channel-header]')!.textContent).toContain('Bakery');
        const posts = [...card().querySelectorAll('[data-post]')].map((p) => p.textContent);
        expect(posts[0]).toContain('Priya');
        expect(posts[0]).toContain('did the retry fix ship?');
        // The account's own post is yours, its file named under it.
        expect(posts[1]).toContain('You');
        expect(posts[1]).toContain('notes.txt');
        expect(posts[2]).toContain('Scout');
        expect(posts[2]).toContain('Yes, it shipped this morning.');
        expect(card().querySelector('[data-channel-foot]')!.textContent).toContain('Handled by Scout');
        // What it read isn't the person's words: it waits behind its fold.
        expect(screen.queryByText(/channel_id ch_1/)).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: /What Scout read/ }));
        expect(screen.getByText(/channel_id ch_1/)).toBeTruthy();
    });

    it('says what it is doing in its row while it works, then its words arrive there as it writes them', () => {
        const arrived = play(EMPTY_THREAD, [{ type: 'message', ...ASKED }]);
        let { card } = show(arrived);
        expect(card().dataset.status).toBe('running');
        expect(card().querySelector('[data-channel-now]')!.textContent).toContain('Starting');
        // Before any work, the foot says nothing yet.
        expect(card().querySelector('[data-channel-foot]')).toBeNull();
        cleanup();

        const working = play(arrived, [
            { type: 'tool_call', id: 'toolu_1', tool: 'shell', source: 'harness', arguments: { command: 'git log -1' }, kind: 'command', command: 'git log -1', operation_id: OP },
        ]);
        ({ card } = show(working));
        expect(card().querySelector('[data-channel-now]')!.textContent).toMatch(/git log -1/);
        expect(card().querySelector('[data-channel-foot]')!.textContent).toMatch(/Working for .* · 1 step/);
        cleanup();

        const writing = play(working, [
            { type: 'tool_result', id: 'toolu_1', tool: 'shell', source: 'harness', is_error: false, exit_code: 0, kind: 'command', operation_id: OP },
            { type: 'text', text: 'Yes, it shipped', operation_id: OP },
        ]);
        ({ card } = show(writing));
        expect(card().querySelector('[data-channel-now]')).toBeNull();
        const own = card().querySelector('[data-writing]')!;
        expect(own.textContent).toContain('Yes, it shipped');
    });

    it('says it stayed quiet when it posted nothing', () => {
        const quiet = play(EMPTY_THREAD, [
            { type: 'message', ...ASKED },
            { type: 'turn_end', status: 'succeeded', text: '', operation_id: OP },
        ]);
        const { card } = show(quiet);
        expect(card().dataset.status).toBe('done');
        expect(card().textContent).toContain('Stayed quiet.');
    });

    it('names the thread its reply posts in and opens the channel there', () => {
        const onOpen = vi.fn();
        const inThread = { ...CHANNEL, thread: { id: 'm_0', author: { type: 'agent', id: 'agent-2', name: 'Growth' }, text: 'The new copy is on a preview.' } };
        const { card } = show(history({ ...ASKED, channel: inThread }), onOpen);
        expect(card().querySelector('[data-channel-header]')!.textContent).toContain('A thread in #launch');
        expect(card().querySelector('[data-channel-thread]')!.textContent).toContain('Growth’s message: “The new copy is on a preview.”');
        fireEvent.click(screen.getByRole('button', { name: /Open/ }));
        expect(onOpen).toHaveBeenCalledWith('ch_1', 'm_0');
    });

    it('draws a connect link’s row once, under its reply inside the card, and leaves an old pin notice out', async () => {
        const pin = { id: 'm_0', author: { type: 'system', id: null, name: 'NoClick' }, text: 'owner pinned a message to this channel.', created_at: iso(-600), thread_id: null, files: [] };
        const halted = { id: 'm_00', author: { type: 'system', id: null, name: 'NoClick' }, text: 'Stopped after 10 agent turns without a person.', created_at: iso(-300), thread_id: null, files: [] };
        const { card } = show(
            history(
                { ...ASKED, channel: { ...CHANNEL, posts: [pin, halted, ...CHANNEL.posts] } },
                LINKED
            )
        );
        const posts = [...card().querySelectorAll('[data-post]')];
        // The pin notice is the channel's record, never a post; NoClick's other notes wear its mark, as the channel draws them.
        expect(card().textContent).not.toContain('pinned a message');
        expect(posts[0]!.textContent).toContain('Stopped after 10 agent turns');
        expect(posts[0]!.querySelector('[data-noclick-mark]')).toBeTruthy();
        // The row sits in the reply's own column, inside the card's body, ahead of its foot.
        const reply = posts[posts.length - 1]!;
        const row = await screen.findByTestId('coordinator-cards');
        expect(reply.contains(row)).toBe(true);
        expect(row.compareDocumentPosition(card().querySelector('[data-channel-foot]')!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        // Its link reads once, as the row; a link no card draws stays in the reply.
        expect([...reply.querySelectorAll(`a[href="${LINK}"]`)].every((a) => row.contains(a))).toBe(true);
        expect(reply.textContent).toContain('Open this link and authorize Stripe:');
        expect(reply.querySelector('a[href="https://docs.stripe.com"]')).toBeTruthy();
    });

    it('draws a message with no channel as it did', () => {
        const { view } = show(history({ id: '1', role: 'user', text: 'Hi there', created_at: iso(0), operation_id: OP, author: { type: 'account', id: null, name: 'Sam' } }));
        expect(view.container.querySelector('[data-row="channel-turn"]')).toBeNull();
        expect(screen.getByText('Hi there')).toBeTruthy();
    });

    it('reads a link its card draws once in a turn no channel started too', async () => {
        const { view } = show(history({ id: '1', role: 'user', text: 'help me connect my stripe account', created_at: iso(0), operation_id: OP, author: { type: 'account', id: null, name: 'Sam' } }, LINKED));
        const row = await screen.findByTestId('coordinator-cards');
        const reply = view.container.querySelector('[data-reply]')!;
        expect(reply.textContent).toContain('Open this link and authorize Stripe:');
        expect(reply.querySelector(`a[href="${LINK}"]`)).toBeNull();
        expect(reply.querySelector('a[href="https://docs.stripe.com"]')).toBeTruthy();
        expect(row.querySelector(`a[href="${LINK}"]`)).toBeTruthy();
    });
});
