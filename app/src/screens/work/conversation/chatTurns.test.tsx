// @vitest-environment happy-dom
// Work's agent conversation over the fake /v1, through the real SDK: a WhatsApp chat's triggered turns draw as that
// chat (ChatTurn) once what came in on them is read, its header once a run, while a schedule's turn keeps its own row;
// a turn at work types and shows its live steps, and the conversation's own live frames make it final in place (one
// read of its activity per burst of frames, none on a timer); a conversation with no such turns reads none.
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { WorkProviders } from '../agents/fixtures/providers';
import { AgentConversation } from './AgentConversation';
import { CHAT_SCENES, WHATSAPP_TRIGGER } from './fixtures/chatScenes';
import { AGENT_ID, fakeWorkAgent } from './fixtures/workAgent';

beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

function show(fake: ReturnType<typeof fakeWorkAgent>, conversation: string) {
    const view = render(
        <WorkProviders client={fake.client}>
            <AgentConversation agentId={AGENT_ID} conversation={conversation} onOpenProfile={() => undefined} onOpenMachine={() => undefined} />
        </WorkProviders>
    );
    return {
        chats: () => [...view.container.querySelectorAll<HTMLElement>('[data-row="chat-turn"]')],
        rows: (row: string) => view.container.querySelectorAll(`[data-row="${row}"]`),
        reads: () => fake.requests.filter((r) => r.path.endsWith('/activity')).length,
    };
}

it('draws a chat’s triggered turns as the chat, its header once, and a schedule’s turn as its own row', async () => {
    const scene = CHAT_SCENES.contact();
    const cron = [
        { id: 'cron-in', role: 'user', text: 'Send the morning summary.', created_at: new Date(Date.now() - 60_000).toISOString(), operation_id: 'op-cron', trigger: { kind: 'cron', id: 'trg-cron', title: 'Every morning' } },
        { id: 'cron-out', role: 'assistant', text: 'Sent.', created_at: new Date(Date.now() - 50_000).toISOString(), operation_id: 'op-cron' },
    ];
    const fake = fakeWorkAgent({ agent: { name: 'WhatsApp' }, histories: { [scene.conversation]: [...scene.history, ...cron] }, activity: { [scene.conversation]: scene.activity }, triggers: [WHATSAPP_TRIGGER] });
    const view = show(fake, scene.conversation);
    await waitFor(() => expect(view.chats()).toHaveLength(2));
    // Read once, as the conversation opened.
    expect(view.reads()).toBe(1);
    expect(view.chats().map((c) => !!c.querySelector('[data-chat-header]'))).toEqual([true, false]);
    // Their turns draw inside them, and no "Triggered by" row stands for them.
    expect(view.rows('trigger')).toHaveLength(1);
    expect(view.rows('trigger')[0].textContent).toContain('Every morning');
    expect(view.rows('turn')).toHaveLength(1);
});

it('a turn at work types and shows its steps, then the live frames make it final in place', async () => {
    const scene = CHAT_SCENES.running();
    const c = scene.conversation;
    const fake = fakeWorkAgent({
        agent: { name: 'WhatsApp' },
        histories: { [c]: scene.history },
        activity: { [c]: scene.activity },
        operations: [{ object: 'operation', id: 'op-live', kind: 'agent.message', status: 'running', conversation: c, created_at: new Date().toISOString() }],
    });
    const view = show(fake, c);
    await waitFor(() => expect(view.chats()).toHaveLength(1));
    const card = view.chats()[0];
    await waitFor(() => expect(fake.watching()).toBe(1));
    expect(card.dataset.status).toBe('running');
    expect(card.querySelector('[data-typing]')).toBeTruthy();

    fake.emit([{ type: 'tool_call', id: 'call-1', tool: 'web__search', arguments: { query: 'tables for four' }, kind: 'tool', operation_id: 'op-live' }], c);
    await waitFor(() => expect(card.querySelector('[data-chat-footer] [data-step="tool"]')).toBeTruthy());
    expect(card.querySelector('[data-chat-footer]')!.textContent).toContain('WhatsApp is working');

    // The turn's calls land in its record as they complete; its frames say so, and it reads them once a burst.
    const reads = view.reads();
    const [item] = fake.activity.get(c)! as { did: unknown[]; turn: Record<string, unknown> }[];
    const now = new Date().toISOString();
    item.did = [{ kind: 'reply', text: 'Booked a table for four at 8:30.', emoji: null, at: now, held_request_id: null, message_id: 'm-1', tool: 'whatsapp__send_text_message' }];
    item.turn = { ...item.turn, status: 'done', worked_s: 6, steps: [{ tool: 'web__search', at: now, error: null }, { tool: 'whatsapp__send_text_message', at: now, error: null }] };
    fake.emit(
        [
            { type: 'tool_result', id: 'call-1', tool: 'web__search', is_error: false, kind: 'tool', operation_id: 'op-live' },
            { type: 'tool_call', id: 'call-2', tool: 'whatsapp__send_text_message', arguments: { body: 'Booked' }, kind: 'tool', operation_id: 'op-live' },
            { type: 'tool_result', id: 'call-2', tool: 'whatsapp__send_text_message', is_error: false, kind: 'tool', operation_id: 'op-live' },
        ],
        c
    );
    fake.settle('op-live', 'succeeded', { result: { text: 'Booked it.' } });

    await waitFor(() => expect(view.chats()[0].dataset.status).toBe('done'));
    // The same card, now final: the reply in place of the typing, "Handled by", no row of its own beside it.
    expect(view.chats()[0]).toBe(card);
    expect(card.querySelector('[data-typing]')).toBeNull();
    expect(card.querySelector('[data-outgoing]')!.textContent).toContain('Booked a table for four at 8:30.');
    expect(card.querySelector('[data-chat-footer]')!.textContent).toMatch(/Handled by WhatsApp\s*· 6s/);
    expect(view.rows('turn')).toHaveLength(0);
    expect(view.reads() - reads).toBe(1);

    // Nothing reads it again on its own.
    await new Promise((r) => setTimeout(r, 600));
    expect(view.reads() - reads).toBe(1);
});

it('a message that comes in while the chat is open draws as begun, then fills in', async () => {
    const scene = CHAT_SCENES.contact();
    const c = scene.conversation;
    const fake = fakeWorkAgent({ histories: { [c]: scene.history }, activity: { [c]: scene.activity } });
    const view = show(fake, c);
    await waitFor(() => expect(view.chats()).toHaveLength(2));
    await waitFor(() => expect(fake.watching()).toBe(1));

    const fresh = CHAT_SCENES.running();
    fake.operations.set('op-live', { object: 'operation', id: 'op-live', kind: 'agent.message', status: 'running', conversation: c, created_at: new Date().toISOString() });
    fake.activity.set(c, [...fresh.activity, ...scene.activity]);
    fake.emit([{ type: 'message', ...fresh.history[0] }], c);
    await waitFor(() => expect(view.chats()).toHaveLength(3));
    await waitFor(() => expect(view.chats()[2].querySelector('[data-incoming]')?.textContent).toContain('book a table for four'));
    expect(view.chats()[2].querySelector('[data-typing]')).toBeTruthy();
    // The same chat as the turn before it: no header again.
    expect(view.chats()[2].querySelector('[data-chat-header]')).toBeNull();
});

it('a conversation no chat app’s message started reads no activity', async () => {
    const fake = fakeWorkAgent({ histories: { main: [{ id: 'm1', role: 'user', text: 'Hello', created_at: new Date().toISOString(), operation_id: 'op-1' }, { id: 'm2', role: 'assistant', text: 'Hi!', created_at: new Date().toISOString(), operation_id: 'op-1' }] } });
    const view = show(fake, 'main');
    await waitFor(() => expect(view.rows('turn')).toHaveLength(1));
    expect(view.reads()).toBe(0);
    expect(view.chats()).toHaveLength(0);
});

it('pictures a chat its turns’ deliveries didn’t, from what its WhatsApp connection keeps, once', async () => {
    const scene = CHAT_SCENES.burst();
    const c = scene.conversation;
    const kept = { [c]: { name: 'Weekend trek', avatar_url: 'https://files.test/trek.jpg' }, '12025550106@c.us': { avatar_url: 'https://files.test/sana.jpg' } };
    const fake = fakeWorkAgent({ histories: { [c]: scene.history }, activity: { [c]: scene.activity }, triggers: [WHATSAPP_TRIGGER], chatProfiles: { whatsapp: kept } });
    const view = show(fake, c);
    await waitFor(() => expect(view.chats()[0]?.querySelector('[data-chat-header] img[data-avatar]')?.getAttribute('src')).toBe('https://files.test/trek.jpg'));
    const runs = view.chats()[0].querySelectorAll('[data-incoming-run]');
    // Sana's picture beside her message; Arjun has none kept, so his initials stay.
    expect(runs[1].querySelector('img[data-avatar]')!.getAttribute('src')).toBe('https://files.test/sana.jpg');
    expect(runs[0].querySelector('[data-initials]')!.textContent).toBe('A');
    const asked = fake.requests.filter((r) => r.path.endsWith('/chat_profiles'));
    expect(asked).toHaveLength(1);
    expect(asked[0].path).toBe('/v1/connections/whatsapp/chat_profiles');
    expect(asked[0].query.getAll('jid').sort()).toEqual([c, '12025550105@c.us', '12025550106@c.us'].sort());
});

it('a chat whose deliveries carried its pictures reads none', async () => {
    const scene = CHAT_SCENES.contact();
    const c = scene.conversation;
    const activity = scene.activity.map((a) => ({ ...a, chat: { ...(a.chat as object), avatar: 'https://files.test/priya.jpg' } }));
    const fake = fakeWorkAgent({ histories: { [c]: scene.history }, activity: { [c]: activity }, triggers: [WHATSAPP_TRIGGER] });
    const view = show(fake, c);
    await waitFor(() => expect(view.chats()[0]?.querySelector('[data-chat-header] img[data-avatar]')?.getAttribute('src')).toBe('https://files.test/priya.jpg'));
    await new Promise((r) => setTimeout(r, 100));
    expect(fake.requests.filter((r) => r.path.endsWith('/chat_profiles'))).toHaveLength(0);
});
