// @vitest-environment happy-dom
// Logs' runs open with what failed in the last day, one line per cause with its fix as a button: "See the runs" narrows
// the list to that cause, a cap is raised in place, a disconnected connection gets a new link, and a failed run's
// drawer leads with the same words and fix and the runs stopped the same way.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { Toaster } from 'sonner';
import { afterEach, expect, it } from 'vitest';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import { FIXTURE_NOW_MS, fixtureId, ok, type FixtureRequest, type FixtureRoute } from '@/screens/console/fixtures/core';
import { OperationsView } from './Operations';

afterEach(cleanup);

function open(path = '/developers/logs', routes: FixtureRoute[] = []) {
    render(
        <MemoryRouter initialEntries={[path]}>
            <ConsoleProviders value={fixtureConsole({ routes, now: () => FIXTURE_NOW_MS })}>
                <OperationsView failures />
            </ConsoleProviders>
            <Toaster />
        </MemoryRouter>
    );
}

const failed = () => screen.findByRole('region', { name: 'Failed in the last day' });
// The runs' rows by their text (asking every row for its role is slow over a page this big).
const rows = () => [...document.querySelectorAll('table[aria-label="Runs"] tr')].map((r) => r.textContent ?? '');

it('groups the last day’s failures by cause, and narrows the runs to one', async () => {
    open();
    const groups = await failed();
    const lines = within(groups).getAllByRole('listitem').map((li) => li.querySelector('p')?.textContent);
    expect(lines).toEqual([
        '3 runs stopped at globex’s cap',
        '2 runs stopped: claude is out of credits',
        '1 run couldn’t use gmail: it’s disconnected',
        '1 run was cut off when NoClick restarted',
    ]);
    expect(within(groups).getByText(/globex has used its \$20 cap this month; it resets Oct 1/)).toBeTruthy();
    // No API route anywhere in the words.
    expect(groups.textContent).not.toMatch(/\/v1\/|PATCH|POST/);

    fireEvent.click(within(groups).getByRole('button', { name: 'See the 3 runs' }));
    await waitFor(() => expect(rows().filter((r) => r.includes('Failed')).length).toBe(3));
    expect(rows().some((r) => r.includes('Book a table for four'))).toBe(false);
    expect(rows().join()).toContain('Refund order 88');
    expect(within(groups).getByRole('button', { name: 'Show every run' }).getAttribute('aria-pressed')).toBe('true');
});

it('raises the cap that stopped the runs in place', async () => {
    const patched: unknown[] = [];
    const routes: FixtureRoute[] = [
        {
            method: 'PATCH',
            path: '/v1/users/:id',
            reply: (r: FixtureRequest) => {
                patched.push([r.params.id, r.body]);
                return ok({ object: 'user', id: r.params.id, spend_cap_usd_per_month: (r.body as { spend_cap_usd_per_month: number }).spend_cap_usd_per_month });
            },
        },
    ];
    open('/developers/logs', routes);
    fireEvent.click(within(await failed()).getByRole('button', { name: 'Raise globex’s cap' }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('globex has spent $20.41 of its $20 cap this month');
    expect((within(dialog).getByLabelText('Monthly cap (USD)') as HTMLInputElement).value).toBe('40');
    fireEvent.change(within(dialog).getByLabelText('Monthly cap (USD)'), { target: { value: '60' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(patched).toEqual([['globex', { spend_cap_usd_per_month: 60 }]]));
    expect(await screen.findByText('Raised to $60')).toBeTruthy();
});

it('makes a disconnected connection a new link, as the user whose runs it stopped', async () => {
    const asked: (string | null)[] = [];
    const routes: FixtureRoute[] = [
        {
            method: 'POST',
            path: '/v1/connections/:ref/connect_links',
            reply: (r: FixtureRequest) => {
                asked.push(`${r.params.ref} ${r.headers.get('NoClick-User')}`);
                return ok({ object: 'connect_link', id: 'cl_1', url: 'https://noclick.com/connect/cl_1', operation_id: fixtureId(4, 90), undelivered: [] });
            },
        },
    ];
    open('/developers/logs', routes);
    fireEvent.click(within(await failed()).getByRole('button', { name: 'Reconnect gmail' }));
    const dialog = await screen.findByRole('dialog', { name: 'Reconnect gmail' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create link' }));
    expect(await within(dialog).findByText('https://noclick.com/connect/cl_1')).toBeTruthy();
    expect(asked).toEqual([`${fixtureId(6, 4)} globex`]);
});

it('opens a failed run fix first, with the runs stopped the same way', async () => {
    open(`/developers/logs?op=${fixtureId(4, 5)}`);
    const why = await screen.findByRole('region', { name: 'Why it failed' });
    expect(within(why).getByText('Stopped at globex’s cap')).toBeTruthy();
    expect(within(why).getByRole('button', { name: 'Raise globex’s cap' })).toBeTruthy();
    expect(await within(why).findByText('Refund order 88')).toBeTruthy();
    expect(within(why).getByText('Chase invoice 1051')).toBeTruthy();
});
