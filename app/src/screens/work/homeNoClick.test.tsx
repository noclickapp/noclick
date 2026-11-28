// @vitest-environment happy-dom
// A new account's first open of Work, over the fake /v1 at a network's pace: its personal space's #noclick is made
// then, with NoClick's own agent in it, and Home's list is never drawn empty on the way (no "No channels here yet",
// no "Nothing in … yet"): it waits as loading, then shows #noclick the moment the make answers, its frame or not.
import { cleanup, render, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { workFixtureClient } from './fixtures/client';
import { WorkClientContext } from './client';
import { COORDINATOR, fakeWork, PERSONAL, type FakeWork } from './fixtures/workApi';
import { HOME_NOCLICK_CHANNEL_TOPIC, NOCLICK_CHANNEL, NOCLICK_CHANNEL_TOPIC, noclickChannelTopic } from './intro';
import { createWorkLive, WorkLiveContext, type WorkLive } from '@/sdk/live';
import { Work } from './Work';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };
/** Each request's round trip, as a network's: long enough that every state between them is drawn. */
const ROUND_TRIP_MS = 25;

beforeEach(() => localStorage.clear());
afterEach(cleanup);

/** Work opened on the fake (`live`: where its frames go; another one loses them), every state it draws recorded. */
function openWork(fake: FakeWork, live: WorkLive = fake.live) {
    const fetch: typeof globalThis.fetch = async (input, init) => {
        await new Promise((resolve) => setTimeout(resolve, ROUND_TRIP_MS));
        return fake.fetch(input, init);
    };
    const client = workFixtureClient(fetch);
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={USER} /> }], { initialEntries: ['/dashboard?tab=work'] });
    const view = render(
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={live}>
                    <RouterProvider router={router} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
    const listed = () => [...view.container.querySelectorAll('[data-testid="home-channels"] li')].map((li) => li.textContent?.trim());
    // Every state drawn, as it's drawn: an empty Home is one with nothing in its list, or saying it has nothing.
    const empties: string[] = [];
    const look = () => {
        const text = view.container.textContent ?? '';
        const list = view.container.querySelector('[data-testid="home-channels"]');
        if (/No channels here yet/.test(text) || /Nothing in .* yet/.test(text) || (list && !list.querySelector('li'))) empties.push(text.slice(0, 120));
    };
    const watching = new MutationObserver(look);
    watching.observe(view.container, { childList: true, subtree: true, characterData: true });
    look();
    return { view, listed, empties, stop: () => watching.disconnect() };
}

const homeNoClicks = (fake: FakeWork) => fake.channels.filter((c) => c.name === NOCLICK_CHANNEL && c.workspace_id === PERSONAL);

it("a new account's first open shows #noclick, made then, and never an empty Home before it", async () => {
    const fake = fakeWork({ empty: true, noclick: true });
    const work = openWork(fake);
    await waitFor(() => expect(work.listed()).toEqual([NOCLICK_CHANNEL]));
    work.stop();
    expect(work.empties).toEqual([]);
    expect(homeNoClicks(fake)).toHaveLength(1);
    expect((homeNoClicks(fake)[0].members as { agent_id?: string }[]).map((m) => m.agent_id)).toEqual([COORDINATOR.id]);
    // It says whose NoClick answers there: yours, the one assistant across your spaces and your phone.
    expect(homeNoClicks(fake)[0].topic).toBe(HOME_NOCLICK_CHANNEL_TOPIC);
    expect(HOME_NOCLICK_CHANNEL_TOPIC).toBe('Your assistant everywhere, across all your spaces and your phone. Tell it what you need.');
});

it("shows a personal #noclick made with a space's topic as yours, and leaves a space's and a topic someone set alone", () => {
    expect(noclickChannelTopic({ topic: NOCLICK_CHANNEL_TOPIC }, true)).toBe(HOME_NOCLICK_CHANNEL_TOPIC);
    expect(noclickChannelTopic({ topic: NOCLICK_CHANNEL_TOPIC }, false)).toBe(NOCLICK_CHANNEL_TOPIC);
    expect(noclickChannelTopic({ topic: 'Where I plan the week' }, true)).toBe('Where I plan the week');
});

it('lists #noclick from the make itself, when the frame after it never arrives', async () => {
    const fake = fakeWork({ empty: true, noclick: true });
    const work = openWork(fake, createWorkLive());
    await waitFor(() => expect(work.listed()).toEqual([NOCLICK_CHANNEL]));
    work.stop();
    expect(work.empties).toEqual([]);
    expect(homeNoClicks(fake)).toHaveLength(1);
});

it('a Home that already holds #noclick shows it at once, making none', async () => {
    const fake = fakeWork({ empty: true, noclick: true });
    const first = openWork(fake);
    await waitFor(() => expect(first.listed()).toEqual([NOCLICK_CHANNEL]));
    first.stop();
    cleanup();
    const posts = () => fake.requests.filter((r) => r.method === 'POST' && r.path === '/v1/channels').length;
    const before = posts();
    const again = openWork(fake);
    await waitFor(() => expect(again.listed()).toEqual([NOCLICK_CHANNEL]));
    again.stop();
    expect(again.empties).toEqual([]);
    expect(posts()).toBe(before);
    expect(homeNoClicks(fake)).toHaveLength(1);
});

it("when #noclick can't be made, Home stops waiting and says it has nothing yet", async () => {
    const fake = fakeWork({ empty: true, noclick: true });
    fake.fail('/v1/channels', 'Channels are down for a moment.', 'POST');
    const work = openWork(fake);
    const made = () => fake.requests.filter((r) => r.method === 'POST' && r.path === '/v1/channels').length;
    let triedWhenSaid = -1;
    await waitFor(
        () => {
            expect(work.view.container.textContent).toMatch(/No channels here yet/);
            if (triedWhenSaid < 0) triedWhenSaid = made();
        }
    );
    work.stop();
    // Said only once the make had failed: never while it was still on its way.
    expect(triedWhenSaid).toBe(1);
    expect(work.view.container.querySelector('[data-testid="home-channels-loading"]')).toBeNull();
    expect(homeNoClicks(fake)).toHaveLength(0);
});
