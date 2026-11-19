// @vitest-environment happy-dom
// A NoClick is shown as NoClick, never by the name it's found by: a space's is made as `noclick-<the space's id>`, and
// the platform flags every NoClick (`noclick`) wherever it lists agents. Work reads that flag, not the spaces it knows
// of, so a NoClick of a space it doesn't list (one just archived, whose agent its list still holds) is never offered
// or shown by that name: a space's #noclick once suggested adding one to a channel (2026-11-14).
import { cleanup, render, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { WorkClientContext } from './client';
import { fakeWork, type FakeWork } from './fixtures/workApi';
import { NOCLICK_CHANNEL, NOCLICK_CHANNEL_TOPIC } from './intro';
import { WorkLiveContext } from '@/sdk/live';
import { Work } from './Work';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };
const SPACE = 'ws_noclick';
const RAW_NAME = /noclick-[0-9a-f]{32}/;
const WAIT_MS = 8000;
const TEST_MS = 30_000;

beforeEach(() => localStorage.clear());
afterEach(cleanup);

/** The account as the platform lists it after a space was archived: that space's NoClick still first among its agents
 *  (its list read before the archive), this space's own NoClick made, and a #noclick here with nothing said in it. */
async function setUp(fake: FakeWork) {
    fake.agents.unshift({ object: 'agent', id: 'agt_nc_gone', name: 'noclick-0123456789abcdef0123456789abcdef', role: 'This space’s NoClick: changes the space when asked', harness: 'sdk', status: 'active', model: 'openrouter/openai/gpt-luna', instructions: '', user_id: null, noclick: true });
    const ours = await fake.client.request<{ agent_id: string }>('GET', `/v1/workspaces/${SPACE}/noclick`, { user: null });
    const member = { object: 'channel_member', id: 'mem_nc', type: 'agent', agent_id: ours.agent_id, name: 'NoClick', noclick: true, busy: false };
    fake.channels.push({ object: 'channel', id: 'ch_nc', name: NOCLICK_CHANNEL, topic: NOCLICK_CHANNEL_TOPIC, mode: 'all', status: 'open', halt_reason: null, unread_count: 0, user_id: null, workspace_id: SPACE, kind: 'channel', members: [member], created_at: new Date().toISOString() });
    fake.messages.set('ch_nc', []);
}

function openWork(fake: FakeWork, search: string) {
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={USER} /> }], { initialEntries: [`/dashboard?tab=work&${search}`] });
    return render(
        <WorkClientContext.Provider value={fake.client}>
            <WorkLiveContext.Provider value={fake.live}>
                    <RouterProvider router={router} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
}

async function asksIn(fake: FakeWork): Promise<string[]> {
    const view = openWork(fake, `space=${SPACE}&channel=ch_nc`);
    const asks = () => [...view.container.querySelectorAll('[data-testid="noclick-channel-asks"] button')].map((b) => b.textContent ?? '');
    // The agents read too: the ask naming one is added once they're in.
    await waitFor(() => expect(asks().length).toBeGreaterThan(0), { timeout: WAIT_MS });
    await waitFor(() => expect(fake.requests.some((r) => r.path === '/v1/agents')).toBe(true), { timeout: WAIT_MS });
    await new Promise((resolve) => setTimeout(resolve, 200));
    return asks();
}

describe('the NoClicks, as Work shows them', () => {
    it(
        "a space's #noclick suggests adding one of your own agents by its name, never a NoClick",
        async () => {
            const fake = fakeWork();
            await setUp(fake);
            const asks = await asksIn(fake);
            expect(asks).toEqual(['Add a channel for launch plans', 'Add Support to #launch-plans', 'Invite a teammate to this space']);
            expect(asks.join(' ')).not.toMatch(/NoClick|coordinator|noclick-/);
        },
        TEST_MS
    );

    it(
        'leaves the agent suggestion out when every agent listed is a NoClick',
        async () => {
            const fake = fakeWork();
            fake.agents.splice(0);
            await setUp(fake);
            expect(await asksIn(fake)).toEqual(['Add a channel for launch plans', 'Invite a teammate to this space']);
        },
        TEST_MS
    );

    it.each([
        ['your agents', 'space=home&show=agents', '[data-agent]'],
        ["the space's agents", `space=${SPACE}&show=agents`, '[data-agent]'],
        ["the space's members", `space=${SPACE}&panel=agents`, '[data-testid="members-panel"]'],
        ["the #noclick channel's members", `space=${SPACE}&channel=ch_nc`, '[data-testid="channel-intro-members"]'],
    ])(
        'never lists a NoClick by its name in %s',
        async (_, search, drawn) => {
            const fake = fakeWork();
            await setUp(fake);
            const view = openWork(fake, search);
            await waitFor(() => expect(view.container.querySelector(drawn)).toBeTruthy(), { timeout: WAIT_MS });
            await waitFor(() => expect(fake.requests.some((r) => r.path === '/v1/agents')).toBe(true), { timeout: WAIT_MS });
            await new Promise((resolve) => setTimeout(resolve, 300));
            expect(view.container.textContent).not.toMatch(RAW_NAME);
            expect(view.container.textContent).not.toMatch(/\bcoordinator\b/);
        },
        TEST_MS
    );
});
