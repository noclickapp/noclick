// @vitest-environment happy-dom
// Work's agent conversation over the fake /v1, through the real SDK: a turn no one on this page started (a wake-up)
// stops working when the stream says it ended, even when it saved no reply, so the box sends again rather than
// steering into a finished turn and the header stops saying it's working. Its Stop is the one every box shares.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { recordingNav, WorkProviders } from '../agents/fixtures/providers';
import { AgentConversation } from './AgentConversation';
import { AGENT_ID, fakeWorkAgent } from './fixtures/workAgent';

// Nothing real is called: the reads beside the conversation (the session, the instance's capabilities) find nothing.
beforeEach(() => vi.stubGlobal('fetch', async () => new Response(null, { status: 404 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

const WAKE = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a02';
const at = (s: number) => new Date(Date.parse('2026-11-14T09:00:00Z') + s * 1000).toISOString();

function show(fake: ReturnType<typeof fakeWorkAgent>) {
    const view = render(
        <WorkProviders client={fake.client}>
            <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} />
        </WorkProviders>
    );
    const q = <T extends HTMLElement>(selector: string) => view.container.querySelector<T>(selector);
    return {
        primary: () => q('[data-primary]')?.dataset.primary,
        button: () => q<HTMLButtonElement>('[data-primary]')!,
        status: () => q('[data-testid="turn-status"]')?.textContent ?? '',
        /** The newest turn's status. */
        turn: () => [...view.container.querySelectorAll<HTMLElement>('[data-row="turn"]')].at(-1)?.dataset.status,
    };
}

it('stops working when a wake-up that worked and said nothing ends', async () => {
    const fake = fakeWorkAgent({
        histories: { main: [{ id: 'm0', role: 'user', text: 'Keep an eye on the deploys.', created_at: at(-600), operation_id: 'op-earlier' }, { id: 'm1', role: 'assistant', text: 'Will do.', created_at: at(-590), operation_id: 'op-earlier' }] },
        operations: [{ object: 'operation', id: WAKE, kind: 'agent.message', status: 'running', conversation: 'main', created_at: at(60) }],
    });
    const view = show(fake);
    await waitFor(() => expect(fake.watching()).toBe(1));

    fake.emit([
        { type: 'message', id: '2', role: 'user', text: 'The deployment finished. Read its result.', created_at: at(60), trigger: { kind: 'wakeup', id: 'wk-1', title: 'The deployment finished' }, operation_id: WAKE },
        { type: 'tool_call', id: 'toolu_01', tool: 'shell', source: 'harness', arguments: { command: 'gh run view 42', cwd: '/workspace' }, kind: 'command', command: 'gh run view 42', operation_id: WAKE },
        { type: 'output', id: 'toolu_01', text: '✓ deploy 42\n', operation_id: WAKE },
    ]);
    await waitFor(() => expect(view.status()).toContain('Running gh run view 42'));
    expect(view.turn()).toBe('running');
    // Where it is now is the turn's last line, under its latest step, so a long turn never scrolls it away.
    const turn = document.querySelector('[data-row="turn"][data-status="running"]')!;
    const line = turn.querySelector('[data-testid="working-line"]')!;
    const step = [...turn.querySelectorAll('*')].find((el) => el.children.length === 0 && el.textContent?.includes('gh run view 42'))!;
    expect(step.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // While it works, an empty box stops it and a typed one would steer into it.
    expect(view.primary()).toBe('stop');
    // The Stop every box shares (the Chat page's too): the primary circle with a filled square, never red.
    const stop = view.button();
    expect(stop.getAttribute('aria-label')).toBe('Stop');
    expect(stop.className).toMatch(/\bbg-primary\b/);
    expect(stop.className).toMatch(/\btext-primary-foreground\b/);
    expect(stop.querySelector('[data-stop-square]')).toBeTruthy();
    expect(stop.outerHTML).not.toMatch(/red-/);

    fake.emit([{ type: 'tool_result', id: 'toolu_01', tool: 'shell', source: 'harness', is_error: false, exit_code: 0, kind: 'command', operation_id: WAKE }]);
    await waitFor(() => expect(view.status()).toContain('Working'));

    // It had nothing to say: no reply is saved, and its operation's settle is the stream's turn_end.
    fake.settle(WAKE, 'succeeded', { result: { text: '', conversation: 'main', tool_calls: [], operation_id: WAKE } });
    await waitFor(() => expect(view.turn()).toBe('done'));
    expect(view.status()).toBe('');
    expect(view.primary()).toBe('send');
});

it('renames the agent with /rename, says so in the timeline, and never sends it to the model', async () => {
    const fake = fakeWorkAgent();
    const view = render(
        <WorkProviders client={fake.client}>
            <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} />
        </WorkProviders>
    );
    const box = () => view.getByRole('textbox', { name: /^Message / }) as HTMLTextAreaElement;
    const say = (text: string) => {
        fireEvent.change(box(), { target: { value: text } });
        fireEvent.keyDown(box(), { key: 'Escape' }); // the / menu, open over a typed command
        fireEvent.keyDown(box(), { key: 'Enter' });
    };
    await waitFor(() => expect(box().getAttribute('aria-label')).toBe('Message Wirefern'));

    say('/rename Bakery helper');
    // The line in its timeline, as the conversation keeps it (the agent reads it at its next turn).
    await waitFor(() => expect(view.getByTestId('timeline').textContent).toContain('Renamed to Bakery helper'));
    expect(fake.requests.filter((r) => r.method === 'PATCH' && r.path === `/v1/agents/${AGENT_ID}`).map((r) => r.body)).toEqual([{ name: 'Bakery helper' }]);
    expect(fake.requests.some((r) => r.method === 'POST' && r.path.endsWith('/messages'))).toBe(false);
    // The box calls it by its new name once the agents are read again.
    await waitFor(() => expect(box().getAttribute('aria-label')).toBe('Message Bakery helper'));

    // A name another agent went by is refused: the rename opens in the box with why.
    say('/rename Marketing');
    const field = (await screen.findByRole('textbox', { name: 'New name' })) as HTMLInputElement;
    expect(field.value).toBe('Marketing');
    expect(screen.getByRole('alert').textContent).toBe("'Marketing' was the name of the agent now called 'Growth', and stays reserved for it so anything still using the old name reaches it. Pick another name.");
    fireEvent.keyDown(field, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'New name' })).toBeNull());

    // Alone, /rename opens it in place, with its name now.
    say('/rename');
    expect(((await screen.findByRole('textbox', { name: 'New name' })) as HTMLInputElement).value).toBe('Bakery helper');
});

it('draws app testing’s switches as one quiet line each, with no row for NoClick’s turn on the switch', async () => {
    const on = { state: 'on', lead: 'Wirefern turned on app testing for this task', detail: 'about $0.44/hour while it works', reason: 'run the retry tests against Postgres' };
    const off = { state: 'off', lead: 'Wirefern turned app testing off', detail: 'ran 18 min, $0.13', reason: on.reason };
    const fake = fakeWorkAgent({
        histories: {
            main: [
                { id: 'm0', role: 'user', text: 'The retry tests fail on main. Can you fix them?', created_at: at(0), operation_id: 'op-1' },
                { id: 'm1', role: 'assistant', text: 'Found it. Running the tests against a real database now.', created_at: at(30), operation_id: 'op-1' },
                { id: 'm2', role: 'note', text: `${on.lead} · ${on.detail}`, data: { app_testing: on }, created_at: at(31) },
                { id: 'm3', role: 'user', text: 'App testing is on: you’re on a bigger computer with Docker running.', trigger: { kind: 'app_testing', id: 'wk-1' }, created_at: at(40), operation_id: 'op-2' },
                { id: 'm4', role: 'note', text: `${off.lead} · ${off.detail}`, data: { app_testing: off }, created_at: at(1100) },
                { id: 'm5', role: 'assistant', text: 'All 214 tests pass against a real database.', created_at: at(1110), operation_id: 'op-2' },
            ],
        },
    });
    const { went, nav } = recordingNav();
    const view = render(
        <WorkProviders client={fake.client} nav={nav}>
            <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} />
        </WorkProviders>
    );
    await waitFor(() => expect(view.getByTestId('timeline').textContent).toContain('All 214 tests pass'));
    const lines = [...view.container.querySelectorAll('[data-row="app-testing"]')].map((row) => row.textContent);
    expect(lines).toEqual([
        'Wirefern turned on app testing for this task · about $0.44/hour while it worksWhat’s this? · Change in Wirefern’s profile',
        'Wirefern turned app testing off · ran 18 min, $0.13',
    ]);
    const timeline = view.getByTestId('timeline').textContent ?? '';
    expect(timeline).not.toContain('you’re on a bigger computer');
    expect(timeline).not.toContain('Triggered by');
    fireEvent.click(view.getByRole('button', { name: 'Change in Wirefern’s profile' }));
    expect(went.filter((w) => w.to === 'openProfile').map((w) => w.args)).toEqual([[AGENT_ID]]);
});
