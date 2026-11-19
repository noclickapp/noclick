// @vitest-environment happy-dom
// An agent in Work is one terminal window with Claude: one timeline of its one session, over the fake /v1 through the
// real SDK. Two WhatsApp chats and a group draw each as its own chat, a channel's post carries a chip naming the
// channel, and the owner's own message is a plain bubble, all in one view; clearing for everyone (the session menu or
// /clear) starts a new session after a confirm, resuming an earlier one switches back, a divider marks where each
// picks up, and neither runs while a turn does.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { WorkProviders } from './agents/fixtures/providers';
import { AgentConversation } from './conversation/AgentConversation';
import { CHAT_SCENES, WHATSAPP_TRIGGER } from './conversation/fixtures/chatScenes';
import { AGENT_ID, fakeWorkAgent } from './conversation/fixtures/workAgent';
import { useActiveSession } from './conversation/sessions';

beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

const CHANNEL = '6f1c2b8e-3d4a-4e5f-9a7b-1c2d3e4f5a6b';
const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

/** Every chat's turns in the agent's one session, oldest first, each user message naming the chat it came from. */
function oneSession() {
    const scenes = [CHAT_SCENES.contact(), CHAT_SCENES.voice(), CHAT_SCENES.group()];
    const tagged = scenes.flatMap((s) => s.history.map((m) => (m.role === 'user' ? { ...m, chat: s.conversation } : m)));
    const posted = [
        { id: 'post-in', role: 'user', text: 'Can someone check the launch checklist?', created_at: ago(7), operation_id: 'op-post', author: { type: 'user', id: 'usr_asha', name: 'Asha' }, chat: `channel:${CHANNEL}` },
        { id: 'post-out', role: 'assistant', text: 'Checked: two items left.', created_at: ago(6.9), operation_id: 'op-post' },
        { id: 'own-in', role: 'user', text: 'What did Priya want?', created_at: ago(2), operation_id: 'op-own', author: { type: 'account', id: null, name: 'Rowan Hale' } },
        { id: 'own-out', role: 'assistant', text: 'A table on Thursday at 6:30.', created_at: ago(1.9), operation_id: 'op-own' },
    ];
    const history = [...tagged, ...posted].sort((a, b) => Date.parse(String(a.created_at)) - Date.parse(String(b.created_at)));
    return { history, activity: scenes.flatMap((s) => s.activity) };
}

/** Work's agent pane: the agent opened on its session, as Work.tsx mounts it, moving when the session does. */
function Pane() {
    const session = useActiveSession(AGENT_ID);
    return session ? <AgentConversation key={session} agentId={AGENT_ID} conversation={session} onOpenProfile={() => undefined} onOpenMachine={() => undefined} /> : null;
}

function show(fake: ReturnType<typeof fakeWorkAgent>) {
    const view = render(
        <WorkProviders client={fake.client}>
            <Pane />
        </WorkProviders>
    );
    return {
        chats: () => [...view.container.querySelectorAll<HTMLElement>('[data-row="chat-turn"]')],
        dividers: () => [...view.container.querySelectorAll('[data-testid="timeline"]')].map((t) => t.textContent ?? '').join(''),
    };
}

async function openSessionMenu() {
    const trigger = await screen.findByLabelText('Its session', {}, { timeout: 5000 });
    fireEvent.keyDown(trigger, { key: 'Enter' });
}

it('draws two chats, a group, a channel post and the owner’s message in one timeline', async () => {
    const { history, activity } = oneSession();
    const fake = fakeWorkAgent({ agent: { name: 'WhatsApp' }, histories: { main: history }, activity: { main: activity }, triggers: [WHATSAPP_TRIGGER], channels: [{ object: 'channel', id: CHANNEL, name: 'launch', kind: 'channel', status: 'open', members: [] }] });
    const view = show(fake);
    // Priya twice (one header for the run), then the group, then Mom: each turn as its own chat.
    await waitFor(() => expect(view.chats()).toHaveLength(4), { timeout: 5000 });
    expect(view.chats().map((c) => !!c.querySelector('[data-chat-header]'))).toEqual([true, false, true, true]);
    expect(view.chats()[2].textContent).toContain('Weekend trek');
    expect(view.chats()[3].textContent).toContain('Mom');
    // The channel's post names its channel, which opens from the chip; the owner's own message carries none.
    const chip = await waitFor(() => {
        const found = document.querySelector<HTMLElement>('[data-source="channel"]');
        expect(found?.textContent).toBe('launch');
        return found!;
    });
    expect(chip.closest('[data-row="user"]')?.textContent).toContain('Can someone check the launch checklist?');
    const own = [...document.querySelectorAll('[data-row="user"]')].find((r) => r.textContent?.includes('What did Priya want?'));
    expect(own?.querySelector('[data-source]')).toBeNull();
    // Only the one session was read: the chats' turns came with it.
    expect(fake.requests.filter((r) => r.method === 'GET' && /\/conversations\/[^/]+$/.test(r.path)).map((r) => r.path)).toEqual([`/v1/agents/${AGENT_ID}/conversations/main`]);
});

it('clears for everyone after a confirm, and resumes the earlier session', async () => {
    const fake = fakeWorkAgent({ agent: { name: 'WhatsApp' }, histories: { main: [{ id: 'm1', role: 'user', text: 'Remember the tasting is Thursday.', created_at: ago(30), operation_id: 'op-1', author: { type: 'account', id: null, name: 'Rowan Hale' } }, { id: 'm2', role: 'assistant', text: 'Noted.', created_at: ago(29), operation_id: 'op-1' }] } });
    const view = show(fake);
    await screen.findByText('Noted.', {}, { timeout: 5000 });

    await openSessionMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: /Clear for everyone/ }));
    const confirm = await screen.findByRole('dialog', { name: 'Start WhatsApp fresh for everyone?' });
    expect(confirm.textContent).toContain('Its files stay. This session is kept under Earlier sessions.');
    fireEvent.click(within(confirm).getByRole('button', { name: 'Clear for everyone' }));
    // The new session opens, empty but for where it picks up.
    await waitFor(() => expect(view.dividers()).toContain('New session · cleared by you'), { timeout: 5000 });
    expect(screen.queryByText('Noted.')).toBeNull();
    expect(fake.requests.some((r) => r.method === 'POST' && r.path === `/v1/agents/${AGENT_ID}/conversations`)).toBe(true);

    // /resume opens the earlier sessions; picking one confirms, and everyone is back there.
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '/resume' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    const list = await screen.findByRole('dialog', { name: 'Resume an earlier session' });
    // Listed by its words (the fake's preview is its newest), the session it's in checked and not to pick.
    expect(within(list).getAllByRole('button').filter((b) => b.getAttribute('aria-current'))).toHaveLength(1);
    fireEvent.click(within(list).getByRole('button', { name: /Noted\./ }));
    const back = await screen.findByRole('dialog', { name: 'Switch WhatsApp back to this session for everyone talking to it?' });
    fireEvent.click(within(back).getByRole('button', { name: 'Switch back' }));
    await screen.findByText('Noted.', {}, { timeout: 5000 });
    await waitFor(() => expect(view.dividers()).toContain('Resumed this session · by you'));
});

it('/clear opens the same confirm, and neither runs while a turn does', async () => {
    const fake = fakeWorkAgent({
        agent: { name: 'WhatsApp' },
        histories: { main: [{ id: 'm1', role: 'user', text: 'Build the report.', created_at: ago(1), operation_id: 'op-live', author: { type: 'account', id: null, name: 'Rowan Hale' } }] },
        operations: [{ object: 'operation', id: 'op-live', kind: 'agent.message', status: 'running', conversation: 'main', created_at: ago(1) }],
    });
    show(fake);
    await screen.findByText('Build the report.', {}, { timeout: 5000 });
    await openSessionMenu();
    const clear = await screen.findByRole('menuitem', { name: /Clear for everyone/ });
    expect(clear.getAttribute('aria-disabled')).toBe('true');
    expect(clear.textContent).toContain('Stop it first');
    fireEvent.keyDown(clear, { key: 'Escape' });

    // Settled, /clear asks the same question the menu does.
    fake.reply('op-live', 'Done.');
    await screen.findByText('Done.', {}, { timeout: 5000 });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '/clear' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(await screen.findByRole('dialog', { name: 'Start WhatsApp fresh for everyone?' })).toBeTruthy();
});
