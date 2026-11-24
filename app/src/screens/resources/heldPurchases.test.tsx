// @vitest-environment happy-dom
// Buying in a copy of the app on the key NoClick gave it: NoClick holds a purchase for the account's owner (src/sdk/held.ts),
// so Resources' Buy a number and Buy a domain say it was sent to the owner to approve and where, never an error, follow it
// on the approval's frame, and once it's approved settle into what a purchase made at once shows. The first domain, with
// no registrant on file, sends the registrant's details without the acceptance an app's key never gives: the owner
// accepts the agreement on the approval page.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import { createRoutesStub } from 'react-router';
import { Toaster } from 'sonner';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { holding } from '@/sdk/heldFixture';
import { createWorkLive } from '@/sdk/live';
import { ConsoleScope } from '@/screens/console/ConsoleProviders';
import { FIXTURE_NOW_MS } from '@/screens/console/fixtures/core';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import { makeFixtureFetch } from '@/screens/console/fixtures/fixtureFetch';
import { ResourcesContext } from './context';
import { ResourcesView } from './ResourcesPage';
import { ResourcesReads } from './reads';

beforeEach(() => vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

/** Resources at `address` as the app's own key, the purchases held for the owner. */
function open(address: string) {
    const api = holding(makeFixtureFetch({ set: 'populated', actsAs: 'key' }), [
        { method: 'POST', path: '/v1/phone_numbers' },
        // The owner accepts the registration agreement approving it: NoClick stamps when.
        { method: 'POST', path: '/v1/domains', accepted: (body) => ({ ...body, registrant: { ...(body.registrant as object), agreement_accepted_at: '2026-11-23T10:05:00Z' } }) },
    ]);
    const client = new NoClick({ apiKey: 'a-fixture-holds-no-key', baseUrl: DEFAULT_BASE_URL, maxRetries: 0, fetch: api.fetch });
    const live = createWorkLive();
    const Page = () => (
        <ResourcesReads>
            <ResourcesView />
        </ResourcesReads>
    );
    const Stub = createRoutesStub([{ path: '/resources', Component: Page }]);
    render(
        <ClientProvider client={client} ownerAccepts>
            <ConsoleScope value={fixtureConsole({ client, actsAs: 'key', now: () => FIXTURE_NOW_MS, live })}>
                <ResourcesContext.Provider value={{ billing: true }}>
                    <Stub initialEntries={[`/resources${address}`]} />
                </ResourcesContext.Provider>
            </ConsoleScope>
            <Toaster />
        </ClientProvider>
    );
    return { api, live };
}

describe('buying a number', () => {
    it('says it went to the owner to approve, and the number is yours once they do', async () => {
        const { api, live } = open('?kind=numbers&new=1');
        const buy = await screen.findByRole('button', { name: 'Buy +1 415 555 0171' }, { timeout: 5000 });
        fireEvent.click(buy);
        await act(async () => fireEvent.click(await screen.findByRole('button', { name: /^Buy for / })));

        const notice = await screen.findByTestId('held-call');
        expect(notice.textContent).toBe('Buy +1 415 555 0171: waiting for approvalSent to the account’s owner to approve, by email. It goes ahead once they approve it.');
        expect(screen.queryByRole('alert')).toBeNull();
        expect(api.held.map((h) => [h.method, h.path, h.body?.number])).toEqual([['POST', '/v1/phone_numbers', '+14155550171']]);
        // While it waits, the number isn't offered again.
        expect(screen.queryByRole('button', { name: 'Buy +1 415 555 0171' })).toBeNull();

        const frame = await api.approve();
        act(() => live.deliver('platform:resource', frame));
        await waitFor(() => expect(screen.getByText('+1 415 555 0171 is yours')).toBeTruthy());
        expect(screen.queryByTestId('held-call')).toBeNull();
    });

    it('says it wasn’t bought when the owner declines it', async () => {
        const { api, live } = open('?kind=numbers&new=1');
        fireEvent.click(await screen.findByRole('button', { name: 'Buy +1 415 555 0171' }, { timeout: 5000 }));
        await act(async () => fireEvent.click(await screen.findByRole('button', { name: /^Buy for / })));
        await screen.findByTestId('held-call');
        act(() => live.deliver('platform:resource', api.decline()));
        await waitFor(() => expect(screen.getByTestId('held-call').getAttribute('data-phase')).toBe('declined'));
        expect(screen.getByTestId('held-call').textContent).toBe('Buy +1 415 555 0171: not doneThe person declined it.');
    });
});

describe('buying a first domain', () => {
    it('leaves the agreement to the owner, says it went to them, and buys it once they approve', async () => {
        const { api, live } = open('?kind=domains&new=1&name=acme');
        const rows = await screen.findAllByTestId('available-domain', undefined, { timeout: 5000 });
        fireEvent.click(within(rows[0]).getByRole('button', { name: 'Buy' }));
        // No box to tick: the account's owner accepts the agreement approving the purchase.
        await screen.findByTestId('owner-accepts-agreement');
        expect(screen.queryByRole('checkbox')).toBeNull();
        const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
        fill('Full name', 'Ana Silva');
        fill('Email', 'ana@example.com');
        fill('Phone', '+14155550123');
        fill('Street address', '500 Market St');
        fill('City', 'San Francisco');
        fill('State or region', 'CA');
        fill('Postal code', '94105');
        fill('Country (two letters)', 'us');
        const buy = screen.getByRole('button', { name: /^Buy for / });
        await waitFor(() => expect(buy.hasAttribute('disabled')).toBe(false));
        await act(async () => fireEvent.click(buy));

        const notice = await screen.findByTestId('held-call');
        expect(notice.textContent).toContain(': waiting for approvalSent to the account’s owner to approve, by email.');
        const sent = api.held[0].body as { registrant: Record<string, unknown>; accept_claims?: unknown };
        expect(sent.registrant.name).toBe('Ana Silva');
        expect(sent.registrant).not.toHaveProperty('agreement_accepted_at');
        expect(sent).not.toHaveProperty('accept_claims');

        const frame = await api.approve();
        act(() => live.deliver('platform:resource', frame));
        await waitFor(() => expect(screen.queryByTestId('held-call')).toBeNull());
        expect(await screen.findByText(/^Buying /)).toBeTruthy();
    });
});
