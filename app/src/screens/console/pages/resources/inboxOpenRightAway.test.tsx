// @vitest-environment happy-dom
// An inbox's message opens when it's clicked the moment the inbox's mail is drawn. The drawer started over (nothing
// open) in an effect keyed on that mail, which React runs a task after a read lands: a message clicked in between
// opened and closed in one render.
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { ALL_USERS } from 'noclick';
import { afterEach, expect, it } from 'vitest';
import { clickAsDrawn } from '@/lib/clickAsDrawn';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import { INBOXES } from '@/screens/console/fixtures/pages/c';
import { InboxesPanel } from './InboxesPanel';

afterEach(cleanup);

it('opens a message clicked as the inbox’s mail is drawn', async () => {
    const click = clickAsDrawn(() => screen.queryByRole('button', { name: /Refund for order 1182/ }));
    render(
        <MemoryRouter initialEntries={[`/resources/inboxes?inbox=${INBOXES[0].id}`]}>
            <ConsoleProviders value={fixtureConsole()}>
                <InboxesPanel user={ALL_USERS} setUser={() => undefined} />
            </ConsoleProviders>
        </MemoryRouter>
    );
    await waitFor(() => expect(click.clicked()).toBe(true), { timeout: 4000 });
    // The message, not the inbox's list: its way back to the list.
    expect(await screen.findByRole('button', { name: 'All messages' })).toBeTruthy();
});
