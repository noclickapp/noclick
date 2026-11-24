// @vitest-environment happy-dom
// Work's list on a laptop, over the fake /v1 with Work's pane measured at a set width: Agents' and DMs' list folds to
// its rail where what's open needs the room, and where you folded it ("Hide agents", remembered on this device). Home's
// never folds, for either reason, and offers no way to; a fold chosen in Agents waits there across a visit to Home.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { workFixtureClient } from './fixtures/client';
import { WorkClientContext } from './client';
import { fakeWork } from './fixtures/workApi';
import { LIST_OPENS, LIST_ROOM } from './listRail';
import { WorkLiveContext } from '@/sdk/live';
import { Work } from './Work';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };
const FOLDED_KEY = 'nc-work-list-folded';

beforeEach(() => localStorage.clear());
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

/** Work opened on Home, its pane (what's beside the list) measured `pane` wide. */
function openWork(pane: number) {
    const measure = HTMLElement.prototype.getBoundingClientRect;
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
        return this.previousElementSibling?.matches('[data-testid="work-list"]') ? DOMRect.fromRect({ width: pane, height: 800 }) : measure.call(this);
    });
    const fake = fakeWork();
    const client = workFixtureClient(fake.fetch);
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={USER} /> }], { initialEntries: ['/dashboard?tab=work'] });
    render(
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={fake.live}>
                    <RouterProvider router={router} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
}

const list = () => screen.getByRole('navigation', { name: 'The list' });
/** Folded to the rail (true), or the full list docked beside what's open. */
const folded = () => list().getAttribute('data-docked') === 'false';
/** The list's fold and show buttons. */
const foldControls = () => within(list()).queryAllByRole('button', { name: /^(Hide|Show) / });

async function show(view: 'Home' | 'Agents' | 'DMs', testId: string) {
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Views' })).getByRole('button', { name: new RegExp(`${view}$`) }));
    await screen.findByTestId(testId);
}

it('Home keeps its list where a narrow pane folds Agents’ and DMs’, and offers no fold', async () => {
    openWork(LIST_ROOM - 200);
    await screen.findByTestId('home-channels');
    expect(folded()).toBe(false);
    expect(foldControls()).toEqual([]);

    await show('Agents', 'agents-list');
    await waitFor(() => expect(folded()).toBe(true));
    await show('DMs', 'dms-list');
    await waitFor(() => expect(folded()).toBe(true));

    await show('Home', 'home-channels');
    expect(folded()).toBe(false);
    expect(foldControls()).toEqual([]);
});

it('a fold chosen in Agents passes over Home, and Agents and DMs are folded again after it', async () => {
    openWork(LIST_OPENS + 400);
    await screen.findByTestId('home-channels');
    await show('Agents', 'agents-list');
    expect(folded()).toBe(false);
    fireEvent.click(within(list()).getByRole('button', { name: 'Hide agents' }));
    expect(folded()).toBe(true);
    expect(localStorage.getItem(FOLDED_KEY)).toBe('1');

    await show('Home', 'home-channels');
    expect(folded()).toBe(false);
    expect(foldControls()).toEqual([]);
    // Home only passed over the choice: it's still remembered.
    expect(localStorage.getItem(FOLDED_KEY)).toBe('1');

    await show('Agents', 'agents-list');
    expect(folded()).toBe(true);
    await show('DMs', 'dms-list');
    expect(folded()).toBe(true);
    // Shown again where there's room, it docks and the choice is cleared.
    fireEvent.click(within(list()).getByRole('button', { name: 'Show people' }));
    expect(folded()).toBe(false);
    expect(localStorage.getItem(FOLDED_KEY)).toBeNull();
});

it('Home opened with a fold remembered on this device keeps its list', async () => {
    localStorage.setItem(FOLDED_KEY, '1');
    openWork(LIST_OPENS + 400);
    await screen.findByTestId('home-channels');
    expect(folded()).toBe(false);
    expect(foldControls()).toEqual([]);
    await show('Agents', 'agents-list');
    expect(folded()).toBe(true);
});
