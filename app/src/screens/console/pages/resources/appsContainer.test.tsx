// @vitest-environment happy-dom
// An app's container settings are shown in its drawer with what its warm instances cost idle, and changed in a dialog
// that sends only what changed: a refusal shows under the setting it names, a saved change reads back priced, and
// the settings go back to their defaults when asked.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { ALL_USERS } from 'noclick';
import { afterEach, expect, it } from 'vitest';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import { list, type FixtureRequest } from '@/screens/console/fixtures/core';
import { BOOKING_APP_ID, PROJECTS, patchApp } from '@/screens/console/fixtures/pages/e_build';
import { AppsPanel } from './AppsPanel';

afterEach(cleanup);

/** The booking app run in a container, as the API answers it after each change the test makes. */
function open(patched: unknown[]) {
    let app = { ...PROJECTS.find((p) => p.id === BOOKING_APP_ID)!, runtime: 'container', framework: 'docker' };
    const routes = [
        { method: 'GET' as const, path: '/v1/projects', reply: () => list([app]) },
        {
            method: 'PATCH' as const,
            path: '/v1/projects/:id',
            reply: (r: FixtureRequest) => {
                patched.push(r.body);
                const reply = patchApp(app, r.body as Record<string, unknown>);
                if (reply.status === 200) app = reply.body as typeof app;
                return reply;
            },
        },
    ];
    render(
        <MemoryRouter initialEntries={[`/resources/apps?app=${BOOKING_APP_ID}`]}>
            <ConsoleProviders value={fixtureConsole({ routes })}>
                <AppsPanel user={ALL_USERS} setUser={() => undefined} />
            </ConsoleProviders>
        </MemoryRouter>
    );
}

const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const save = () => fireEvent.click(within(screen.getByRole('dialog', { name: 'Container settings' })).getByRole('button', { name: 'Save' }));

it('shows what each instance gets, and refuses a change by the setting it names', async () => {
    const patched: unknown[] = [];
    open(patched);
    const change = await screen.findByRole('button', { name: 'Change container settings' });
    const shown = screen.getByLabelText('Container settings');
    expect(shown.textContent).toContain('1 vCPU, 512 MiB');
    expect(shown.textContent).toContain('None: one starts when a request comes');
    expect(shown.textContent).toContain('5 minutes');

    fireEvent.click(change);
    await screen.findByRole('dialog', { name: 'Container settings' });
    type('Memory (MiB)', '8192');
    save();
    expect(await screen.findByText(/1 vCPU takes 512 to 4096 MiB of memory, not 8192/)).toBeTruthy();
    expect(patched).toEqual([{ container: { memory: 8192 } }]);
    expect(screen.getByLabelText('Memory (MiB)').getAttribute('aria-invalid')).toBe('true');

    // Warm instances whose idle cost alone passes the app's $25 budget are refused under Kept warm.
    type('Memory (MiB)', '2048');
    type('Kept warm', '1');
    fireEvent.click(screen.getByRole('button', { name: 'Always on' }));
    save();
    expect(await screen.findByText(/Keeping 1 instance warm costs about \$57\.82 a month/)).toBeTruthy();
    expect(patched.at(-1)).toEqual({ container: { memory: 2048, min_instances: 1, cpu_always: true } });
    expect(screen.getByLabelText('Kept warm').getAttribute('aria-invalid')).toBe('true');
    expect(screen.getByLabelText('Memory (MiB)').getAttribute('aria-invalid')).toBeNull();
});

it('saves only what changed, reads it back priced, and puts every setting back', async () => {
    const patched: unknown[] = [];
    open(patched);
    fireEvent.click(await screen.findByRole('button', { name: 'Change container settings' }));
    await screen.findByRole('dialog', { name: 'Container settings' });
    type('Memory (MiB)', '2048');
    type('Kept warm', '1');
    save();
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Container settings' })).toBeNull());
    expect(patched).toEqual([{ container: { memory: 2048, min_instances: 1 } }]);
    const shown = screen.getByLabelText('Container settings');
    expect(shown.textContent).toContain('1 vCPU, 2,048 MiB');
    expect(shown.textContent).toContain('$19.71 a month');
    expect(screen.getByText('1 instance kept warm while production serves it: about $19.71 a month even with nothing calling it.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Change container settings' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Reset to defaults' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Container settings' })).toBeNull());
    expect(patched.at(-1)).toEqual({ container: null });
    expect(screen.getByLabelText('Container settings').textContent).toContain('Nothing with none kept warm');
});
