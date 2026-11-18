// @vitest-environment happy-dom
// A console acting as a key reads the account as the API gives it to a key. Where the API won't (one from before a
// key could read the account), the console says so in place of its pages; the owner's console is left as it was.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ConsoleProviders } from './ConsoleProviders';
import { fixtureConsole } from './fixtures/context';
import type { FixtureRoute } from './fixtures/core';
import { OWNER_ONLY_REFUSAL } from './fixtures/fixtureFetch';

afterEach(cleanup);

/** An API from before a key could read the account: only the signed-in owner may. */
const REFUSED: FixtureRoute = { method: 'GET', path: '/v1/account', reply: () => OWNER_ONLY_REFUSAL };

it('reads the account the API gives a key, and renders', async () => {
    render(
        <ConsoleProviders value={fixtureConsole({ actsAs: 'key' })}>
            <p>The console</p>
        </ConsoleProviders>,
    );
    expect(await screen.findByText('The console')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
});

it('says the API won’t read the account to its key, in place of its pages', async () => {
    render(
        <ConsoleProviders value={fixtureConsole({ actsAs: 'key', routes: [REFUSED] })}>
            <p>The console</p>
        </ConsoleProviders>,
    );
    const said = await screen.findByRole('alert');
    expect(said.textContent).toContain("This API doesn't read the account to this key");
    expect(said.textContent).toContain('This call is for the signed-in account owner, not an API key.');
    expect(screen.queryByText('The console')).toBeNull();
});

it('as the owner, leaves a refused account read to the pages, as before', async () => {
    render(
        <ConsoleProviders value={fixtureConsole({ routes: [REFUSED] })}>
            <p>The console</p>
        </ConsoleProviders>,
    );
    expect(await screen.findByText('The console')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
});
