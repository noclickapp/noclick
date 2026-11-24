// @vitest-environment happy-dom
// Resources acting as one of the account's keys (as `/resources` does) asks the API for nothing only the signed-in
// owner may have. The fixtures refuse those operations to a key as NoClick's API does (ownerOnly.ts lists them), so a
// page that still asked would show the refusal. This opens the overview, every kind this app lists, every item of each
// and each page for getting one, as a key, and fails on any such request.
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import { createRoutesStub } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConsoleScope } from '@/screens/console/ConsoleProviders';
import { FIXTURE_NOW_MS } from '@/screens/console/fixtures/core';
import { fixtureConsole } from '@/screens/console/fixtures/context';
import { makeFixtureFetch } from '@/screens/console/fixtures/fixtureFetch';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { ResourcesContext } from './context';
import { KINDS } from './kinds';
import { ResourcesView } from './ResourcesPage';
import { ResourcesReads } from './reads';

// A file's preview reads its made-up link: answered here, so nothing reaches the network.
beforeEach(() => vi.stubGlobal('fetch', async () => new Response('A made-up file.', { status: 200 })));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

interface Calls {
    made: string[];
    ownerOnly: string[];
    /** Resolves once nothing is loading on the page and no request has been in flight for a moment. */
    settled(): Promise<void>;
    container: HTMLElement;
}

/** Resources at `address` (its query), acting as a key over the populated fixtures. */
function open(address: string): Calls {
    const answer = makeFixtureFetch({ set: 'populated', actsAs: 'key' });
    const made: string[] = [];
    const ownerOnly: string[] = [];
    let flying = 0;
    let last = Date.now();
    const client = new NoClick({
        apiKey: 'a-fixture-holds-no-key',
        baseUrl: DEFAULT_BASE_URL,
        maxRetries: 0,
        fetch: async (input, init) => {
            const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
            const method = (init?.method ?? 'GET').toUpperCase();
            made.push(`${method} ${url.pathname}`);
            if (isOwnerOnly(method, url.pathname)) ownerOnly.push(`${method} ${url.pathname}`);
            flying += 1;
            try {
                return await answer(input, init);
            } finally {
                flying -= 1;
                last = Date.now();
            }
        },
    });
    const Page = () => (
        <ResourcesReads>
            <ResourcesView />
        </ResourcesReads>
    );
    const Stub = createRoutesStub([{ path: '/resources', Component: Page }]);
    const { container } = render(
        <ConsoleScope value={fixtureConsole({ client, actsAs: 'key', now: () => FIXTURE_NOW_MS })}>
            <ResourcesContext.Provider value={{ billing: true }}>
                <Stub initialEntries={[`/resources${address}`]} />
            </ResourcesContext.Provider>
        </ConsoleScope>
    );
    return {
        made,
        ownerOnly,
        container,
        settled: async () => {
            await waitFor(
                () => {
                    expect(made.length).toBeGreaterThan(0);
                    expect(flying).toBe(0);
                    expect(Date.now() - last).toBeGreaterThan(150);
                    expect(container.querySelectorAll('.animate-pulse').length).toBe(0);
                },
                { interval: 30 }
            );
        },
    };
}

/** The overview, each kind's list and each page for getting one by hand. */
const ADDRESSES = ['', ...KINDS.map((k) => `?kind=${k.id}`), ...KINDS.filter((k) => k.manual).map((k) => `?kind=${k.id}&new=1`)];

describe('Resources acting as a key', () => {
    it.each(ADDRESSES)('asks for nothing only the owner may have at /resources%s', async (address) => {
        const calls = open(address);
        await calls.settled();
        expect(calls.ownerOnly).toEqual([]);
    });

    it.each(KINDS.map((k) => k.id))('asks for nothing only the owner may have on any %s page', async (kind) => {
        const listed = open(`?kind=${kind}`);
        await listed.settled();
        const count = listed.container.querySelectorAll('[data-resource-row]').length;
        // The fixtures hold some of every kind, so each one's pages are opened.
        expect(count).toBeGreaterThan(0);
        cleanup();
        for (let row = 0; row < count; row += 1) {
            const calls = open(`?kind=${kind}`);
            await calls.settled();
            const rows = calls.container.querySelectorAll<HTMLElement>('[data-resource-row]');
            await act(async () => fireEvent.click(rows[row]));
            await calls.settled();
            expect(calls.ownerOnly, `${kind} row ${row}`).toEqual([]);
            cleanup();
        }
        // Every item's page, each opened afresh: a dozen agents' pages take a few seconds.
    });
});
