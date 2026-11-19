// @vitest-environment happy-dom
// A resource page's Delete works from the moment the page is drawn: clicked before the page's effects have run (React
// runs them in a later task once a page that arrived with its data is drawn), it still opens its panel and asks the
// API what the delete would do. And another item's page starts without the last one's delete.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createRoutesStub, useNavigate, type NavigateFunction } from 'react-router';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { ConsoleScope } from '@/screens/console/ConsoleProviders';
import { fixtureClient } from '@/screens/console/fixtures/client';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import type { FixtureRequest } from '@/screens/console/fixtures/core';
import { ACCOUNT_FILES } from '@/screens/console/fixtures/pages/q_workflow_files';
import { ClientProvider } from '@/sdk/client';
import { clickAsDrawn } from '@/lib/clickAsDrawn';
import { ResourcesView } from './ResourcesPage';
import { ResourcesReads } from './reads';

const requests: FixtureRequest[] = [];
let navigate: NavigateFunction;

beforeEach(() => {
    requests.length = 0;
});
afterEach(cleanup);

const fileAddress = (id: string) => `/resources?kind=files&resource=${id}`;

function page(address: string) {
    const client = fixtureClient({ set: 'populated', onRequest: (request) => requests.push(request) }, { maxRetries: 0 });
    const Page = () => {
        navigate = useNavigate();
        return (
            <ResourcesReads>
                <ResourcesView />
            </ResourcesReads>
        );
    };
    const Stub = createRoutesStub([{ path: '/resources', Component: Page }]);
    return render(
        <ConsoleScope value={fixtureConsole({ client })}>
            <ClientProvider client={client}>
                <Stub initialEntries={[address]} />
            </ClientProvider>
        </ConsoleScope>
    );
}

const previewed = () => requests.some((r) => r.method === 'POST' && r.path === '/v1/delete_previews');

it('opens its delete when Delete is clicked as soon as the page is drawn', async () => {
    const click = clickAsDrawn(() => screen.queryByRole('button', { name: 'Delete' }));
    try {
        page(fileAddress(ACCOUNT_FILES[0].id));
        await waitFor(() => expect(click.clicked()).toBe(true), { timeout: 5000 });
    } finally {
        click.stop();
    }
    expect(screen.getByTestId('removal-panel')).toBeTruthy();
    await waitFor(() => expect(previewed()).toBe(true), { timeout: 5000 });
    await screen.findByText("Deletes the file 'Q3 summary.pdf' from the account's files for good.", undefined, { timeout: 5000 });
});

it("opens another file's page without the last one's delete", async () => {
    page(fileAddress(ACCOUNT_FILES[0].id));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }, { timeout: 5000 }));
    await screen.findByText("Deletes the file 'Q3 summary.pdf' from the account's files for good.", undefined, { timeout: 5000 });
    act(() => void navigate(fileAddress(ACCOUNT_FILES[1].id)));
    await screen.findByRole('heading', { name: ACCOUNT_FILES[1].name }, { timeout: 5000 });
    expect(screen.queryByTestId('removal-panel')).toBeNull();
    expect(screen.getByRole('button', { name: 'Delete' })).toBeTruthy();
});
