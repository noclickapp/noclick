// @vitest-environment happy-dom
// Inviting people to your personal space, over the fake /v1: Invite people shares the personal space (once) and opens
// the same invite dialog a team space has, named for your personal space and saying what stays yours. No other space is
// made, and Work stays where it is. An invite that fails says so in the dialog.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { workFixtureClient } from './fixtures/client';
import { WorkClientContext } from './client';
import { fakeWork, type FakeWork } from './fixtures/workApi';
import { WorkLiveContext } from '@/sdk/live';
import { Work } from './Work';
import { MORE_AGENTS } from '@/screens/channels/slots';
import { fill } from '@/slots';

const USER = { email: 'rowan@example.com', display_name: 'Rowan Hale' };
// No agents from Automations in the pickers here (the hosted fill would ask the app's socket).
fill(MORE_AGENTS, null);

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
const listInvite = async () => within(await screen.findByTestId('work-list', {}, { timeout: 5000 })).findByRole('button', { name: 'Invite people' }, { timeout: 5000 });

async function inviteFromDms() {
    fireEvent.click(await listInvite());
    return await screen.findByTestId('invite-dialog', {}, { timeout: 5000 });
}

it('Invite people in the personal space invites into it, through the dialog a team space has', async () => {
    const fake = fakeWork({ empty: true, noclick: true });
    const router = openDms(fake);
    const dialog = await inviteFromDms();

    // The personal space was shared, once, and no space was made to invite people to.
    expect(sent(fake, 'POST', '/v1/me/personal_space')).toHaveLength(1);
    expect(sent(fake, 'POST', '/v1/workspaces')).toHaveLength(0);
    expect(screen.queryByTestId('space-dialog')).toBeNull();
    const [personal] = fake.workspaces.filter((w) => w.personal);
    expect(dialog.textContent).toContain('Invite people to your personal space');
    expect(dialog.textContent).toContain('Your chat with NoClick, your DMs and your settings stay yours.');
    expect(document.body.textContent).not.toContain('Make a space to invite people to');
    // Work stays in the personal space.
    expect(new URLSearchParams(router.state.location.search).get('space')).toBe('home');

    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'asha@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(sent(fake, 'POST', `/v1/workspaces/${String(personal.id)}/invites`)).toHaveLength(1));
    expect(sent(fake, 'POST', `/v1/workspaces/${String(personal.id)}/invites`)[0].body).toEqual({ email: 'asha@example.com', role: 'member' });

    // Shared, its header opens a menu with who's in it; Invite people again shares nothing more.
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(screen.queryByTestId('invite-dialog')).toBeNull());
    expect(await screen.findByTestId('space-menu')).toBeTruthy();
    await inviteFromDms();
    expect(sent(fake, 'POST', '/v1/me/personal_space')).toHaveLength(1);
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

it("when the personal space can't be shared, no dialog opens and nothing is made", async () => {
    const fake = fakeWork({ empty: true, noclick: true });
    fake.fail('/v1/me/personal_space', 'Sharing is down for a moment.', 'POST');
    openDms(fake);
    fireEvent.click(await listInvite());
    await waitFor(() => expect(sent(fake, 'POST', '/v1/me/personal_space')).toHaveLength(1));
    expect(screen.queryByTestId('invite-dialog')).toBeNull();
    expect(fake.workspaces.filter((w) => w.personal)).toHaveLength(0);
    expect(sent(fake, 'POST', '/v1/workspaces')).toHaveLength(0);
});
