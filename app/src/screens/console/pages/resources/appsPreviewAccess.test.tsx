// @vitest-environment happy-dom
// An app's previews are made private from its drawer: the choice is saved at once, saying what the API adds to it,
// and a private preview's link is made when asked and shown to copy, from the Overview and from the preview's own
// deployment.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { ALL_USERS } from 'noclick';
import { afterEach, expect, it } from 'vitest';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import { ok, type FixtureRequest } from '@/screens/console/fixtures/core';
import { BOOKING_APP_ID, PROJECTS } from '@/screens/console/fixtures/pages/e_build';
import { AppsPanel } from './AppsPanel';

afterEach(cleanup);

const NOT_YET = 'Its previews stay public until NoClick’s front door is updated.';

function open(path: string, patched: Record<string, unknown>[]) {
    const booking = PROJECTS.find((p) => p.id === BOOKING_APP_ID)!;
    const routes = [
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
        <MemoryRouter initialEntries={[path]}>
            <ConsoleProviders value={fixtureConsole({ routes })}>
                <AppsPanel user={ALL_USERS} setUser={() => undefined} />
            </ConsoleProviders>
        </MemoryRouter>
    );
}

it('keeps previews to a link, and makes one to copy', async () => {
    const patched: Record<string, unknown>[] = [];
    open(`/resources/apps?app=${BOOKING_APP_ID}`, patched);
    const previews = await screen.findByRole('group', { name: 'Previews' });
    expect(previews.textContent).toContain('Anyone with the URL');
    fireEvent.click(await screen.findByRole('button', { name: 'Link only' }));
    await waitFor(() => expect(patched).toEqual([{ preview_access: 'link' }]));
    fireEvent.click(await screen.findByRole('button', { name: 'Make a preview link' }));
    const link = await screen.findByText(/^https:\/\/new-form--booking\.noclick\.site\/\?preview=p1~/);
    expect(link).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy the link' })).toBeTruthy();
    expect(screen.getByText(/Opens the new-form preview until/)).toBeTruthy();
});
