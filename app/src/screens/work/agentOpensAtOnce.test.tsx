// @vitest-environment happy-dom
// A tap on an agent opens its screen at once, as a phone app's does: its face, its loading lines and its box are there
// while Work reads which session it's in, and its conversation takes their place once that's read. Before, the list
// stayed under the finger until the read came back (half a second to a second on a phone).
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { PhoneBarSlotProvider } from '@/ui/phoneBar';
import { WorkLiveContext } from '@/sdk/live';
import { WorkClientContext } from './client';
import { workFixtureClient } from './fixtures/client';
import { fakeWork } from './fixtures/workApi';
import { Work } from './Work';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };

beforeEach(() => localStorage.clear());
afterEach(cleanup);

it('a phone shows the agent’s screen the moment it’s tapped, before its session is read', async () => {
    const fake = fakeWork();
    let release = () => undefined as void;
    const held = new Promise<void>((done) => (release = done));
    const sessionsOf = /\/v1\/agents\/agt_growth\/conversations(\?|$)/;
    const client = workFixtureClient(async (input, init) => {
        if (sessionsOf.test(String(input instanceof Request ? input.url : input))) await held;
        return fake.fetch(input, init);
    });
    const lead = document.createElement('div');
    document.body.append(lead);
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={USER} /> }], { initialEntries: ['/dashboard?tab=work&space=home&show=agents'] });
    render(
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={fake.live}>
                <PhoneBarSlotProvider slot={null} lead={lead} setLeadTaken={() => undefined}>
                    <RouterProvider router={router} />
                </PhoneBarSlotProvider>
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );

    const row = await waitFor(() => {
        const found = document.querySelector<HTMLButtonElement>('li[data-agent="agt_growth"] > button');
        expect(found).toBeTruthy();
        return found!;
    });
    fireEvent.pointerDown(row);
    fireEvent.click(row);

    // Its screen, with the way back to the list, while the read is still out: no list under the finger.
    const opening = await screen.findByTestId('agent-opening');
    expect(screen.queryByTestId('agents-list')).toBeNull();
    expect(within(lead).getByRole('button', { name: 'Agents' })).toBeTruthy();
    // Nothing to type into yet: words typed there would be lost when its session's box takes its place.
    expect(within(opening).queryByRole('textbox')).toBeNull();

    release();
    expect(await screen.findByTestId('agent-conversation')).toBeTruthy();
    expect(screen.queryByTestId('agent-opening')).toBeNull();
    lead.remove();
});
