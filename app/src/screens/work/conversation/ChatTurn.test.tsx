// @vitest-environment happy-dom
// A turn a WhatsApp message started, drawn as that chat (ChatTurn) from its activity item as the route answers it:
// what came in (a group's writer, a voice note's transcript, a photo, what it quoted, several messages in a row), the
// agent's replies with their time and tick, reactions under what they react to, its notes as pills (quiet with why,
// a reminder, a note, a lookup, a failure), a held call answered through its request, and "Handled by" opening its steps.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { failureOf, runningTurn, type TurnEntry, type UserEntry } from '@/lib/agentThread/thread';
import { toTurnActivity, type TurnActivity } from '@/lib/agentThread/turnActivity';
import { WorkProviders } from '../agents/fixtures/providers';
import { ChatTurn, chatName } from './ChatTurn';
import { CHAT_SCENES, HELD_REQUEST } from './fixtures/chatScenes';
import { fakeWorkAgent } from './fixtures/workAgent';

afterEach(cleanup);

const FACE = { id: 'agent-1', kind: 'agent' as const, name: 'WhatsApp', agentId: 'agent-1' };
const entry = (a: TurnActivity): UserEntry => ({ kind: 'user', key: a.turn.id, id: null, text: '', at: a.turn.startedAt, files: [], operationId: a.turn.id, author: null, via: null, trigger: { kind: 'event', id: 'trg' }, chat: null, command: null, subagent: null, steer: false, pending: false, references: [] });
const items = (name: keyof typeof CHAT_SCENES) => CHAT_SCENES[name]().activity.map((raw) => toTurnActivity(raw));

function show(a: TurnActivity, options: { header?: boolean; fake?: ReturnType<typeof fakeWorkAgent>; turn?: TurnEntry; failureTold?: boolean } = {}) {
    const fake = options.fake ?? fakeWorkAgent({ humanRequests: [HELD_REQUEST] });
    const view = render(
        <WorkProviders client={fake.client}>
            <ChatTurn activity={a} chat={a.chat} entry={entry(a)} turn={options.turn ?? null} failureTold={options.failureTold} agent={{ name: 'WhatsApp', face: FACE }} header={options.header ?? true} mode="all" requests={[]} onAnswer={() => undefined} />
        </WorkProviders>
    );
    return { fake, view, card: () => view.container.querySelector<HTMLElement>('[data-row="chat-turn"]')! };
}

describe('a chat turn', () => {
    it('reads what came in as the message that started it, then those it took along, oldest first', () => {
        const [single] = items('contact');
        expect(single.inbound).toHaveLength(1);
        const [burst] = items('burst');
        expect(burst.inbound.map((m) => [m.senderName, m.text, m.messageId])).toEqual([
            ['Arjun', 'Rowan are you driving Saturday?', 'op-trek-burst-msg'],
            ['Arjun', 'We need one more car', 'op-trek-burst-msg-1'],
            ['Sana', 'I can take two people', 'op-trek-burst-msg-2'],
        ]);
        // Each at when it arrived; one the turn didn't keep a time for reads as the turn's start.
        expect(burst.inbound[1].at - burst.inbound[0].at).toBe(60_000);
        const raw = CHAT_SCENES.burst().activity[0] as { also_inbound: { at: string | null }[] };
        raw.also_inbound[0].at = null;
        const read = toTurnActivity(raw as never);
        expect(read.inbound[1].at).toBe(read.turn.startedAt);
    });

    it('draws a batched turn’s messages in order, each with its own time, and a reaction under the one it reacts to', () => {
        const [burst] = items('burst');
        const { card } = show(burst);
        const bubbles = [...card().querySelectorAll<HTMLElement>('[data-incoming]')];
        expect(bubbles.map((b) => b.textContent)).toEqual(burst.inbound.map((m) => expect.stringContaining(m.text)));
        expect(bubbles.map((b) => b.querySelector('time')!.getAttribute('dateTime'))).toEqual(burst.inbound.map((m) => new Date(m.at).toISOString()));
        // 👍 reacts to Arjun's second message: under it, not under the last one or the first.
        const reacted = [...card().querySelectorAll('[data-incoming]')].map((b) => b.parentElement!.querySelector('[data-reaction]')?.textContent ?? null);
        expect(reacted).toEqual([null, '👍', null]);
        // The reply comes after all of them.
        const all = [...card().querySelectorAll('[data-incoming], [data-outgoing]')];
        expect(all.at(-1)!.hasAttribute('data-outgoing')).toBe(true);
    });

    it('draws a contact’s message, the reply with its time and tick, and a note about the chat', async () => {
        const [latest] = items('contact');
        const { card } = show(latest);
        await waitFor(() => expect(card()).toBeTruthy());
        const header = card().querySelector('[data-chat-header]')!;
        expect(header.textContent).toContain('Priya Shah');
        expect(header.textContent).toContain('Direct chat · +1 202 555 0101');
        expect(card().querySelector('[data-incoming]')!.textContent).toContain('Are you around Thursday evening');
        const out = card().querySelector('[data-outgoing]')!;
        expect(out.textContent).toContain('Want me to hold 6:30');
        expect(out.querySelector('time')).toBeTruthy();
        expect(within(out as HTMLElement).getByLabelText('Sent')).toBeTruthy();
        expect(card().querySelector('[data-pill="note"]')!.textContent).toBe('Saved a note about this chat');
        expect(card().querySelector('[data-typing]')).toBeNull();
        expect(card().dataset.status).toBe('done');
    });

    it('names a group’s writers, and their messages in a row sit together, once per writer', () => {
        const [burst] = items('burst');
        const { card } = show(burst);
        const runs = card().querySelectorAll('[data-incoming-run]');
        expect(runs).toHaveLength(2);
        expect([...runs].map((r) => r.querySelectorAll('[data-incoming]').length)).toEqual([2, 1]);
        // The writer's name heads their run, their picture (here initials) sits beside it.
        expect(runs[0].querySelectorAll('[data-incoming]')[0].textContent).toContain('Arjun');
        expect(runs[0].querySelectorAll('[data-incoming]')[1].textContent).not.toContain('Arjun');
        expect(runs[1].querySelector('[data-initials]')!.textContent).toBe('S');
        expect(card().querySelector('[data-chat-header]')!.textContent).toContain('Group');
    });

    it('says when a reminder wakes it as it was set, and draws your own chat with your face', () => {
        const [own] = items('self');
        const { card } = show(own);
        expect(card().querySelector('[data-pill="reminder"]')!.textContent).toBe('Set a reminder in 45 minutes: call the bank');
        const header = card().querySelector('[data-chat-header]')!;
        expect(header.textContent).toContain('Message yourself');
        expect(header.textContent).toContain('Your own chat');
        expect(header.querySelector('[data-initials]')!.textContent).toBe('R');
    });

    it('says why it stayed quiet', () => {
        const [quiet] = items('group');
        const { card } = show(quiet);
        expect(card().querySelector('[data-pill="quiet"]')!.textContent).toBe('WhatsApp stayed quiet: A question to the whole group, and nobody asked for Rowan.');
        expect(card().querySelector('[data-outgoing]')).toBeNull();
    });

    it('draws a voice note with its transcript, the reaction under it, and the reminder it set', () => {
        const [voice] = items('voice');
        const { card } = show(voice);
        const note = card().querySelector('[data-voice]')!;
        expect(note.textContent).toContain('0:42');
        expect(note.textContent).toContain('Transcript');
        expect(note.textContent).toContain('Bring the good mangoes');
        // The reaction is under the message it reacts to, before the reply.
        const run = card().querySelector('[data-incoming-run]')!;
        expect(run.querySelector('[data-reaction]')!.textContent).toBe('❤️');
        const day = new Date(voice.did[2].when!).toLocaleString('en-US', { weekday: 'short' });
        expect(card().querySelector('[data-pill="reminder"]')!.textContent).toBe(`Set a reminder for ${day} 11:00 AM: buy mangoes`);
    });

    it('draws a photo that came in, what a message quoted, and a lookup', () => {
        const [, photo] = items('contact');
        expect(show(photo).card().querySelector('[data-incoming]')!.textContent).toContain('Photo');
        cleanup();
        const [held] = items('held');
        const { card } = show(held);
        expect(card().querySelector('[data-incoming]')!.textContent).toContain('Sending the October numbers today');
        expect(card().querySelector('[data-pill="found"]')!.textContent).toBe('Looked up “October invoice”');
    });

    it('says what didn’t go through, in the tool’s words and the error’s', () => {
        const [latest] = items('contact');
        const failed: TurnActivity = {
            ...latest,
            did: [{ ...latest.did[0], kind: 'failed', text: 'whatsapp__send_image_message: Wirefern timed out', tool: 'whatsapp__send_image_message' }],
            turn: { ...latest.turn, status: 'failed' },
        };
        const { card } = show(failed);
        expect(card().querySelector('[data-pill="failed"]')!.textContent).toBe('whatsapp · send image message didn’t go through: Wirefern timed out');
        expect(card().querySelector('[data-chat-footer]')!.textContent).toContain('WhatsApp didn’t finish');
    });

    it('says its plan’s limit in one quiet line, never a failed pill or a refused key, unless a move’s line says it', () => {
        const [latest] = items('contact');
        const stopped: TurnActivity = { ...latest, did: [{ ...latest.did[0], kind: 'failed', text: 'The turn failed', tool: null }], turn: { ...latest.turn, status: 'failed' } };
        const failure = failureOf({ type: 'plan_limit_reached', reason: 'plan_limit', connection: 'work', integration: 'anthropic', message: 'Your Claude plan (work) is used up until 3:20 PM.' });
        const turn: TurnEntry = { kind: 'turn', key: 't', operationId: latest.turn.id, id: 'm9', parts: [], reply: null, files: [], reasoning: [], status: 'failed', startedAt: latest.turn.startedAt, endedAt: latest.turn.startedAt + 4000, compacting: null, downloading: null, failure, announced: [], outOfFunds: null, groups: [], summary: null };
        const { card } = show(stopped, { turn });
        expect(card().querySelector('[data-row="plan-limit"]')!.textContent).toBe('Your Claude plan (work) is used up until 3:20 PM.');
        expect(card().querySelector('[data-pill="failed"]')).toBeNull();
        expect(card().querySelector('[data-testid="refused-turn"]')).toBeNull();
        expect(card().textContent).not.toMatch(/refused|Reconnect|Sign in again/);
        cleanup();
        const told = show(stopped, { turn, failureTold: true });
        expect(told.card().querySelector('[data-row="plan-limit"]')).toBeNull();
        expect(told.card().querySelector('[data-pill="failed"]')).toBeNull();
    });

    it('holds a call for your yes: Approve and Decline answer its request, as its page does', async () => {
        const [held] = items('held');
        const { fake, card } = show(held);
        const box = card().querySelector<HTMLElement>('[data-held]')!;
        expect(box.textContent).toContain('Waiting for your yes: Send email: the October invoice to Rahul');
        const approve = within(box).getByRole('button', { name: 'Approve' });
        await waitFor(() => expect(approve.hasAttribute('disabled')).toBe(false));
        fireEvent.click(approve);
        await waitFor(() => expect(card().textContent).toContain('Approved: Send email: the October invoice to Rahul'));
        expect(fake.requests.filter((r) => r.method === 'POST').map((r) => [r.path, r.body])).toEqual([['/v1/humans/requests/req-held/answer', { approved: true, note: null }]]);
        cleanup();

        const again = fakeWorkAgent({ humanRequests: [HELD_REQUEST] });
        const declined = show(held, { fake: again });
        const decline = await waitFor(() => {
            const b = within(declined.card().querySelector<HTMLElement>('[data-held]')!).getByRole('button', { name: 'Decline' });
            expect(b.hasAttribute('disabled')).toBe(false);
            return b;
        });
        fireEvent.click(decline);
        await waitFor(() => expect(declined.card().textContent).toContain('You declined, so it didn’t run'));
        expect(again.requests.filter((r) => r.method === 'POST').map((r) => r.body)).toEqual([{ approved: false, note: null }]);
    });

    it('ends in "Handled by" with how long it worked, its steps a tap away', () => {
        const [latest] = items('contact');
        const { card } = show(latest);
        const footer = card().querySelector<HTMLElement>('[data-chat-footer]')!;
        const toggle = within(footer).getByRole('button', { name: /Handled by WhatsApp/ });
        expect(toggle.textContent).toContain('· 4s');
        expect(toggle.getAttribute('aria-expanded')).toBe('false');
        fireEvent.click(toggle);
        expect(toggle.getAttribute('aria-expanded')).toBe('true');
        expect(footer.querySelectorAll('[data-step]')).toHaveLength(2);
    });

    it('while it works: typing on its side and its steps, live', () => {
        const [live] = items('running');
        const turn = { ...runningTurn(live.turn.id, live.turn.startedAt), parts: [] };
        render(
            <WorkProviders client={fakeWorkAgent().client}>
                <ChatTurn activity={live} chat={live.chat} entry={entry(live)} turn={turn} agent={{ name: 'WhatsApp', face: FACE }} header mode="all" requests={[]} onAnswer={() => undefined} />
            </WorkProviders>
        );
        expect(screen.getByRole('status', { name: 'WhatsApp is typing' })).toBeTruthy();
        expect(document.querySelector('[data-chat-footer]')!.textContent).toContain('WhatsApp is working');
    });

    it('names a chat by its person, its group, its number, or as your own', () => {
        const [latest] = items('contact');
        expect(chatName(latest.chat)).toBe('Priya Shah');
        expect(chatName({ ...latest.chat, name: null })).toBe('+1 202 555 0101');
        expect(chatName({ ...latest.chat, kind: 'self' })).toBe('Message yourself');
        expect(chatName({ ...latest.chat, kind: 'group', name: null, number: null })).toBe('A group');
    });
});
