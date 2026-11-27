// @vitest-environment happy-dom
// An app opens on a page of its own, from its list and from every address that opened its drawer: what the drawer's
// tabs held reads as the page's sections, and a deployment opens in a drawer on it.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import { MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router';
import { afterEach, expect, it } from 'vitest';
import { DeveloperConsole } from '../../DeveloperConsole';
import { FIXTURE_NOW_MS, FIXTURE_USER } from '../../fixtures/core';
import { makeFixtureFetch } from '../../fixtures/fixtureFetch';
import { BOOKING_APP_ID, buildId } from '../../fixtures/pages/e_build';

afterEach(cleanup);

const BASE = '/developers';
const PAGE = `${BASE}/resources/apps/${BOOKING_APP_ID}`;
/** Booking's failed deploy of main, which a push started. */
const FAILED_DEPLOY = buildId(305);

let at = { pathname: '', search: '', hash: '' };

function open(address: string) {
    const client = new NoClick({ apiKey: 'a-fixture-holds-no-key', baseUrl: DEFAULT_BASE_URL, maxRetries: 0, fetch: makeFixtureFetch({ set: 'populated' }) });
    function Mounted() {
        at = useLocation();
        return (
            <DeveloperConsole
                section={useParams()['*']}
                client={client}
                actsAs="owner"
                basePath={BASE}
                apiUrl="https://api.noclick.com"
                site="https://noclick.com"
                home="/"
                user={FIXTURE_USER}
                now={() => FIXTURE_NOW_MS}
                onSignOut={() => undefined}
                live={null}
            />
        );
    }
    render(
        <MemoryRouter initialEntries={[`${BASE}/${address}`]}>
            <Routes>
                <Route path={`${BASE}/*`} element={<Mounted />} />
            </Routes>
        </MemoryRouter>
    );
}

it('opens an app from its list on its own page, with its drawer’s tabs as sections', async () => {
    open('resources/apps');
    fireEvent.click(await screen.findByText('booking'));
    await waitFor(() => expect(at.pathname).toBe(PAGE));
    expect(await screen.findByRole('heading', { level: 1, name: 'booking' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Deploy main' })).toBeTruthy();
    for (const section of ['This month', 'Recent deploys', 'Domains', 'What it printed', 'Bindings', 'Environment', 'Schedules', 'Email, payments and sign-in', 'How it deploys', 'About']) {
        expect(screen.getByRole('region', { name: section })).toBeTruthy();
    }
    // What stops its paid calls leads, with its fix.
    expect(screen.getByText(/Paid calls stopped/)).toBeTruthy();
});

it.each([
    [`resources/apps?app=${BOOKING_APP_ID}&tab=deployments&deployment=${FAILED_DEPLOY}`, `?deployment=${FAILED_DEPLOY}`, '#deploys'],
    [`resources/apps?app=${BOOKING_APP_ID}&tab=bindings`, '', '#bindings'],
    [`resources?kind=apps&resource=${BOOKING_APP_ID}`, '', ''],
])('opens /%s, an address of the drawer, on the app’s page', async (address, search, hash) => {
    open(address);
    await waitFor(() => expect(at.pathname).toBe(PAGE));
    expect(at.search).toBe(search);
    expect(at.hash).toBe(hash);
    // An open drawer hides the page behind it from the accessibility tree.
    expect(await screen.findByRole('heading', { level: 1, name: 'booking', hidden: !!search })).toBeTruthy();
    if (search) {
        const drawer = await screen.findByRole('dialog', { name: 'Deployment' });
        expect(drawer.textContent).toContain('It didn’t deploy');
        expect(drawer.textContent).toContain('budget');
    }
});
