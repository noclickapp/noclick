// @vitest-environment happy-dom
// Inviting people to your personal space, over the fake /v1: it's a space like any other, so Invite people opens the
// invite dialog a team space has, named for your personal space and saying what stays yours. Nothing is shared or made
// first, and Work stays where it is. An invite that fails says so in the dialog.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { workFixtureClient } from './fixtures/client';
import { WorkClientContext } from './client';
import { fakeWork, type FakeWork } from './fixtures/workApi';
import { WorkLiveContext } from '@/sdk/live';
import { Work } from './Work';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };

beforeEach(() => localStorage.clear());
afterEach(cleanup);

/** Work opened on the personal space's DMs, of an account with nothing in it but its #noclick. */
function openDms(fake: FakeWork) {
    const client = workFixtureClient(fake.fetch);
    const router = createMemoryRouter([{ path: '/dashboard', element: <Work user={USER} /> }], { initialEntries: ['/dashboard?tab=work&space=home&show=dms'] });
    render(
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={fake.live}>
                    <RouterProvider router={router} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
    return router;
}

const sent = (fake: FakeWork, method: string, path: string) => fake.requests.filter((r) => r.method === method && r.path === path);

/** The DMs list's Invite people (the pane beside it, with no one to message, offers it too). */
const listInvite = async () => within(await screen.findByTestId('work-list')).findByRole('button', { name: 'Invite people' });

async function inviteFromDms() {
    fireEvent.click(await listInvite());
    return await screen.findByTestId('invite-dialog');
}

it('Invite people in the personal space invites into it, through the dialog a team space has', async () => {
    const fake = fakeWork({ empty: true, noclick: true });
    const router = openDms(fake);
    const dialog = await inviteFromDms();
    const [personal] = fake.workspaces.filter((w) => w.personal);

    // Nothing was shared or made to invite people to.
    expect(sent(fake, 'POST', '/v1/me/personal_space')).toHaveLength(0);
    expect(sent(fake, 'POST', '/v1/workspaces')).toHaveLength(0);
    expect(screen.queryByTestId('space-dialog')).toBeNull();
    expect(dialog.textContent).toContain('Invite people to your personal space');
    expect(dialog.textContent).toContain('Your chat with NoClick, your DMs and your settings stay yours.');
    // Work stays in the personal space, named by its id.
    expect(new URLSearchParams(router.state.location.search).get('space')).toBe(personal.id);

    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'asha@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(sent(fake, 'POST', `/v1/workspaces/${String(personal.id)}/invites`)).toHaveLength(1));
    expect(sent(fake, 'POST', `/v1/workspaces/${String(personal.id)}/invites`)[0].body).toEqual({ email: 'asha@example.com', role: 'member' });

    // Its header opens the menu every space has.
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(screen.queryByTestId('invite-dialog')).toBeNull());
    expect(await screen.findByTestId('space-menu')).toBeTruthy();
});

it('an invite that fails says why in the dialog, which stays open with what was typed', async () => {
    const fake = fakeWork({ empty: true, noclick: true });
    openDms(fake);
    await inviteFromDms();
    const [personal] = fake.workspaces.filter((w) => w.personal);
    fake.fail(`/v1/workspaces/${String(personal.id)}/invites`, 'Invites are paused on this account.', 'POST');

    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'asha@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Invites are paused on this account.');
    expect(screen.getByTestId('invite-dialog')).toBeTruthy();
    expect((screen.getByLabelText('Email address') as HTMLInputElement).value).toBe('asha@example.com');
});
