// @vitest-environment happy-dom
// An app's previews are made private from its page: the choice is saved at once, saying what the API adds to it,
// and a private preview's link is made when asked and shown to copy, from the Overview and from the preview's own
// deployment; every link made so far can be stopped beside it, which puts away the one shown.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it } from 'vitest';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import { ok, type FixtureRequest } from '@/screens/console/fixtures/core';
import { BOOKING_APP_ID, PROJECTS } from '@/screens/console/fixtures/pages/e_build';
import { AppPage } from './AppPage';

afterEach(cleanup);

const NOT_YET = 'Its previews stay public until NoClick’s front door is updated.';
const STOPPED = 'Every link to its previews made before now stops opening them within 30 seconds.';

function open(patched: Record<string, unknown>[], revoked: string[] = []) {
    const booking = PROJECTS.find((p) => p.id === BOOKING_APP_ID)!;
    const routes = [
        {
            method: 'POST' as const,
            path: '/v1/projects/:id/previews/links/revoke',
            reply: (r: FixtureRequest) => {
                revoked.push(r.params.id!);
                return ok({ ...booking, preview_access: 'link', notes: [STOPPED] });
            },
        },
        {
            method: 'PATCH' as const,
            path: '/v1/projects/:id',
            reply: (r: FixtureRequest) => {
                patched.push(r.body as Record<string, unknown>);
                return ok({ ...booking, ...(r.body as object), notes: [NOT_YET] });
            },
        },
        // Read again after the change, as the API answers it then.
        { method: 'GET' as const, path: `/v1/projects/${BOOKING_APP_ID}`, reply: () => ok({ ...booking, preview_access: patched.length ? 'link' : 'public' }) },
    ];
    render(
        <MemoryRouter initialEntries={[`/resources/apps/${BOOKING_APP_ID}`]}>
            <ConsoleProviders value={fixtureConsole({ routes })}>
                <AppPage id={BOOKING_APP_ID} />
            </ConsoleProviders>
        </MemoryRouter>
    );
}

it('keeps previews to a link, and makes one to copy', async () => {
    const patched: Record<string, unknown>[] = [];
    open(patched);
    const previews = await screen.findByRole('group', { name: 'Previews' });
    expect(previews.textContent).toContain('Anyone with the URL');
    fireEvent.click(await screen.findByRole('button', { name: 'Link only' }));
    await waitFor(() => expect(patched).toEqual([{ preview_access: 'link' }]));
    fireEvent.click(await screen.findByRole('button', { name: 'Make a preview link' }));
    const link = await screen.findByText(/^https:\/\/new-form--booking\.noclick\.site\/\?preview=p2~/);
    expect(link).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy the link' })).toBeTruthy();
    expect(screen.getByText(/Opens the new-form preview until/)).toBeTruthy();
});

it('stops every link made so far, once confirmed, and puts away the one shown', async () => {
    const patched: Record<string, unknown>[] = [];
    const revoked: string[] = [];
    open(patched, revoked);
    fireEvent.click(await screen.findByRole('button', { name: 'Link only' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Make a preview link' }));
    await screen.findByText(/^https:\/\/new-form--booking\.noclick\.site\/\?preview=p2~/);
    fireEvent.click(screen.getByRole('button', { name: 'Stop all preview links' }));
    expect(revoked).toEqual([]); // nothing stops until it's confirmed
    fireEvent.click(await screen.findByRole('button', { name: 'Stop all links' }));
    await waitFor(() => expect(revoked).toEqual([BOOKING_APP_ID]));
    expect(await screen.findByRole('button', { name: 'Make a preview link' })).toBeTruthy();
    expect(screen.queryByText(/\?preview=p2~/)).toBeNull();
});
