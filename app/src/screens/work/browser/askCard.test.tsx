// @vitest-environment happy-dom
// A browser task that stopped at a step only a person can do, in Work's agent conversation over the fake /v1 through
// the real SDK. The task was started from another chat of the session (a key's own conversation): its browser carries
// that chat, never the session, and the session still finds it. Its turn draws the ask's card (what the step is, Open
// the browser for the person it asked, Cancel), the conversation scrolls to it as it opens, Open the browser takes the
// browser over (live, yours to drive) and Done hands it back, which finishes the step as Done on the page NoClick
// emailed does; Cancel calls the task off and the card goes. The Agents list says both when a turn runs meanwhile.
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { AgentStateRow } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { WorkProviders } from '../agents/fixtures/providers';
import { entryOf } from '../agents/states';
import { AgentConversation } from '../conversation/AgentConversation';
import { AGENT_ID, fakeWorkAgent } from '../conversation/fixtures/workAgent';

/** No picture streams in a unit test: a live view's socket opens and says nothing. */
class QuietSocket extends EventTarget {
    static readonly OPEN = 1;
    readyState = 0;
    binaryType = 'blob';
    onopen: unknown = null;
    onmessage: unknown = null;
    onclose: unknown = null;
    onerror: unknown = null;
    send() {}
    close() {
        this.readyState = 3;
    }
}

const scrolled: Element[] = [];
beforeEach(() => {
    vi.stubGlobal('fetch', async () => new Response(null, { status: 404 }));
    vi.stubGlobal('WebSocket', QuietSocket);
    scrolled.length = 0;
    Element.prototype.scrollIntoView = function (this: Element) {
        scrolled.push(this);
    };
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

const BROWSER = '9b1e7a2b-9d3f-4e6a-8b5c-2f1d0e9a7b63';
const ACT = '2e2d4f1a-3b5c-4d6e-9f8a-1b2c3d4e5f60';
const TURN = 'op-turn';
const CHAT = 'signin-test';
const STEP = 'Sign in to developers.example.com.';
const at = (s: number) => new Date(Date.parse('2026-11-28T12:13:00Z') + s * 1000).toISOString();

function world() {
    const browser = {
        object: 'browser', id: BROWSER, status: 'parked', agent_id: AGENT_ID, conversation: CHAT, region: 'us-east',
        url: 'https://developers.example.com/login', title: 'Sign in', act_id: ACT, acting: false, held: false,
        waiting_on: { person: STEP, for_you: true }, steps: [{ action: 'click', target: 'Sign In', at: at(50) }, { action: 'ask', target: null, at: at(60) }],
        created_at: at(5), started_at: at(6),
    };
    const actCall = {
        tool: 'browser__act', arguments: { instruction: 'Sign in to the developer portal', max_steps: 25 }, is_error: false, created_at: at(60),
        result: JSON.stringify({ success: true, operation_id: ACT, status: 'working', message: 'The task is still running after 50 seconds.' }),
    };
    const fake = fakeWorkAgent({
        histories: {
            main: [
                { id: 'm0', role: 'user', text: 'Sign in to the developer portal.', created_at: at(0), operation_id: TURN, chat: CHAT },
                { id: 'm1', role: 'assistant', text: 'The sign-in is still running; I’ll tell you when it’s done.', created_at: at(62), operation_id: TURN, tool_calls: [actCall] },
            ],
        },
        operations: [
            { object: 'operation', id: TURN, kind: 'agent.message', status: 'succeeded', conversation: CHAT, created_at: at(0), updated_at: at(62) },
            { object: 'operation', id: ACT, kind: 'browser.act', status: 'awaiting_human', step: 'awaiting_human', agent_id: AGENT_ID, created_at: at(10), updated_at: at(60), started_at: at(10), waiting_on: { person: STEP, sent_to: ['email'] } },
        ],
        browsers: [browser],
    });
    return { fake, browser };
}

function show(fake: ReturnType<typeof fakeWorkAgent>) {
    const view = render(
        <WorkProviders client={fake.client}>
            <AgentConversation agentId={AGENT_ID} conversation="main" onOpenProfile={() => undefined} onOpenMachine={() => undefined} />
        </WorkProviders>
    );
    const card = () => view.container.querySelector<HTMLElement>('[data-testid="browser-ask"]');
    const button = (label: string) => [...(card()?.querySelectorAll('button') ?? [])].find((b) => b.textContent === label) ?? null;
    /** The backend's frame about the agent's browser: what reads it reads again. */
    const moved = () => invalidateV1(`work:browser:${AGENT_ID}:main`);
    return { view, card, button, moved };
}

it('draws the step a browser task asks of you in its turn, and scrolls to it as the conversation opens', async () => {
    const { fake } = world();
    const { card, button } = show(fake);
    await waitFor(() => expect(card()?.querySelector('[data-testid="browser-ask-step"]')?.textContent).toBe(STEP));
    expect(card()!.textContent).toContain('Open the browser, finish it there, then tap Done.');
    expect(button('Open the browser')).not.toBeNull();
    expect(button('Cancel')).not.toBeNull();
    // The session read the agent's browsers whatever chat they're in, and took the one of a chat it shows.
    expect(fake.requests.some((r) => r.path === '/v1/browsers' && r.query.get('agent_id') === AGENT_ID && !r.query.get('conversation'))).toBe(true);
    await waitFor(() => expect(scrolled).toContain(card()));
});

it('opens the browser for you to finish the step, and Done hands it back', async () => {
    const { fake, browser } = world();
    const { card, button, moved } = show(fake);
    await waitFor(() => expect(button('Open the browser')).not.toBeNull());

    fireEvent.click(button('Open the browser')!);
    await waitFor(() => expect(fake.requests.some((r) => r.method === 'POST' && r.path === `/v1/browsers/${BROWSER}/take_over`)).toBe(true));
    // Yours to drive, and the card's one action is Done.
    await waitFor(() => expect(button('Done')).not.toBeNull());
    expect(browser.held).toBe(true);
    expect(card()!.textContent).toContain('You’re in control.');

    fireEvent.click(button('Done')!);
    await waitFor(() => expect(fake.requests.some((r) => r.method === 'POST' && r.path === `/v1/browsers/${BROWSER}/hand_back`)).toBe(true));
    // The step is finished (as Done on the emailed page finishes it): nothing waits on you, and the card goes.
    fake.settle(ACT, 'succeeded', { result: { done: true, summary: 'Signed in.', steps: [], url: browser.url, downloads: [] }, finished_at: at(90) });
    moved();
    await waitFor(() => expect(card()).toBeNull());
});

it('calls the task off from the card, and the ask goes with it', async () => {
    const { fake } = world();
    const { card, button } = show(fake);
    await waitFor(() => expect(button('Cancel')).not.toBeNull());
    fireEvent.click(button('Cancel')!);
    await waitFor(() => expect(fake.requests.some((r) => r.method === 'POST' && r.path === `/v1/operations/${ACT}/cancel`)).toBe(true));
    expect(fake.operations.get(ACT)?.status).toBe('canceled');
    await waitFor(() => expect(card()).toBeNull());
});

it('says both in the Agents list when a turn runs while a step waits on you', () => {
    const row = (now: AgentStateRow['now']): AgentStateRow => ({
        agentId: AGENT_ID, name: 'oauth-registrar', harness: 'claude_code', state: 'needs_you', conversation: CHAT, now,
        waiting: { asks: 1, heldCalls: 0, requests: 0, total: 1 }, turnStartedAt: new Date(at(70)), lastActiveAt: new Date(at(70)), failed: null, waking: null, raw: {},
    });
    const running = { tool: 'browser__goto', kind: 'tool', line: 'browser__goto', since: new Date(at(70)), running: true, label: null, category: null, summary: null } as const;
    expect(entryOf(row(null), undefined, Date.parse(at(80))).line).toBe('Waiting on you');
    expect(entryOf(row(running), undefined, Date.parse(at(80))).line).toMatch(/ · needs you$/);
    expect(entryOf(row(running), undefined, Date.parse(at(80))).status).toBe('needs');
});
