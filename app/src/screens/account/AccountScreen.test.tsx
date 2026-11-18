// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NoClick } from 'noclick';
import { afterEach, expect, it } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { AccountScreen } from './AccountScreen';

afterEach(cleanup);

const STATUS = {
    object: 'status',
    account: { id: 'acct_7f3a', name: 'Ana Lima', email: 'ana@example.com', acting_for: null },
    user_id: null,
    plan: { name: 'member' },
    balance: { remaining_usd: 42.5, unlimited: false },
    month: { period_start: '2026-11-01T00:00:00+00:00', resets_at: '2026-12-01T00:00:00+00:00', spent_usd: 7.25 },
};

type Answer = { status: number; body: unknown } | Error;

/** Renders the screen on a client whose fetch answers each call with the next of `answers`, recording the URLs. */
function renderWith(...answers: Answer[]) {
    const urls: string[] = [];
    const client = new NoClick({
        apiKey: 'held-by-this-app-server',
        baseUrl: 'http://app.test/api',
        maxRetries: 0,
        fetch: async (input) => {
            urls.push(String(input));
            const answer = answers.shift();
            if (!answer) throw new Error('no answer left');
            if (answer instanceof Error) throw answer;
            return new Response(JSON.stringify(answer.body), { status: answer.status, headers: { 'content-type': 'application/json' } });
        },
    });
    render(
        <ClientProvider client={client}>
            <AccountScreen />
        </ClientProvider>,
    );
    return urls;
}

it('shows the account the API answered, read through the client it was handed', async () => {
    const urls = renderWith({ status: 200, body: STATUS });
    expect(screen.getByRole('status').textContent).toBe('Reading your NoClick account…');
    expect(await screen.findByRole('heading', { name: 'Ana Lima' })).toBeTruthy();
    expect(urls).toEqual(['http://app.test/api/v1/status']);
    const rows = Object.fromEntries(
        screen.getAllByRole('term').map((term) => [term.textContent, term.nextElementSibling?.textContent]),
    );
    expect(rows).toEqual({ Plan: 'Member', 'Left to spend': '$42.50', 'Spent this month': '$7.25 since November 1' });
    expect(screen.getByText('ana@example.com')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sign out' }).closest('form')?.getAttribute('action')).toBe('/logout');
});

it('says what it can’t read rather than guessing, and names the user a key acts for', async () => {
    renderWith({
        status: 200,
        body: {
            ...STATUS,
            account: { id: null, name: null, email: null, acting_for: { id: 'user_42', name: 'Kai Osei', email: 'kai@example.com' } },
            plan: null,
            balance: { remaining_usd: null, unlimited: false },
        },
    });
    expect(await screen.findByRole('heading', { name: 'Your NoClick account' })).toBeTruthy();
    const rows = Object.fromEntries(
        screen.getAllByRole('term').map((term) => [term.textContent, term.nextElementSibling?.textContent]),
    );
    expect(rows).toEqual({ 'Acting for': 'Kai Osei', 'Left to spend': 'Can’t be read right now', 'Spent this month': '$7.25 since November 1' });
});

it('shows the API’s own words when it refuses, and tries again on request', async () => {
    renderWith(
        { status: 401, body: { error: { type: 'unauthenticated', message: 'This API key was revoked.', next_step: 'Create a new key and set NOCLICK_API_KEY.' } } },
        { status: 200, body: STATUS },
    );
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Couldn’t read your account');
    expect(alert.textContent).toContain('This API key was revoked.');
    expect(alert.textContent).toContain('Create a new key and set NOCLICK_API_KEY.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Ana Lima' })).toBeTruthy();
});

it('says the app’s server couldn’t be reached, and when the app’s session ended, how to sign in again', async () => {
    renderWith(new TypeError('Failed to fetch'));
    expect((await screen.findByRole('alert')).textContent).toContain('This page couldn’t reach the app’s server.');
    cleanup();

    renderWith({
        status: 401,
        body: { error: { type: 'unauthenticated', message: 'You’re signed out of this app.', next_step: 'Open the app and sign in.', reason: 'signed_out' } },
    });
    expect((await screen.findByRole('alert')).textContent).toContain('You’re signed out of this app.');
    expect(screen.getByRole('link', { name: 'Sign in again' }).getAttribute('href')).toBe('/login');
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
});

it('shows the proxy’s plain words when NoClick’s API is out of reach', async () => {
    renderWith({
        status: 502,
        body: { error: { type: 'upstream_error', message: 'This app’s server couldn’t reach NoClick’s API.', next_step: 'Check NOCLICK_API_URL and the server’s network connection, then try again.' } },
    });
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('This app’s server couldn’t reach NoClick’s API.');
});
