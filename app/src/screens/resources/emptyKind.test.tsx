// @vitest-environment happy-dom
// An empty Resources kind page says what the kind is once, in the page's own line: the empty state under it names
// what's missing and the ways to get one, without repeating that line. Over every kind this app lists, read from an
// account that holds nothing.
import { cleanup, render, screen } from '@testing-library/react';
import { createRoutesStub } from 'react-router';
import { afterEach, expect, it } from 'vitest';
import { ConsoleScope } from '@/screens/console/ConsoleProviders';
import { fixtureClient } from '@/screens/console/fixtures/client';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import { ClientProvider } from '@/sdk/client';
import { KINDS } from './kinds';
import { ResourcesView } from './ResourcesPage';
import { ResourcesReads } from './reads';

afterEach(cleanup);

it.each(KINDS.map((k) => [k.label, k] as const))('%s, empty, says what it is once', async (_, kind) => {
    const client = fixtureClient({ set: 'empty' }, { maxRetries: 0 });
    const Page = () => (
        <ResourcesReads>
            <ResourcesView />
        </ResourcesReads>
    );
    const Stub = createRoutesStub([{ path: '/resources', Component: Page }]);
    const view = render(
        <ConsoleScope value={fixtureConsole({ client })}>
            <ClientProvider client={client}>
                <Stub initialEntries={[`/resources?kind=${kind.id}`]} />
            </ClientProvider>
        </ConsoleScope>
    );
    await screen.findByText(`No ${kind.label.toLowerCase()} yet`);
    expect(view.container.textContent!.split(kind.empty)).toHaveLength(2);
    expect(screen.getByRole('heading', { name: kind.label }).nextElementSibling!.textContent).toContain(kind.empty);
});
