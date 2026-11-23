// @vitest-environment happy-dom
// The console in a copy of the app on the key NoClick gave it, where NoClick holds what can't be undone for the account's
// owner (src/sdk/held.ts). Its shared confirm (ConfirmAction: releasing or disconnecting a number, deleting a webhook,
// a sandbox, a schedule, a browser profile, a binding, a domain served, closing a card or a channel, clearing a queue,
// cancelling a port) closes and leaves a toast that says the call went to the owner and where, and follows it on the
// approval's frame to done or not; its error panel (every console dialog's) says a held call is waiting, never that it
// failed; and a toast a page shows for its own action (revoking a grant, forgetting a memory, cancelling an operation
// or a deployment, deleting a user, a DNS record) does the same through useReportHeld.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { DEFAULT_BASE_URL, NoClick, PhoneNumber } from 'noclick';
import { Toaster } from 'sonner';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { holding } from '@/sdk/heldFixture';
import { useReportHeld } from '@/sdk/held';
import { createWorkLive } from '@/sdk/live';
import { ClientProvider } from '@/sdk/client';
import { ConsoleScope } from './ConsoleProviders';
import { fixtureConsole } from './fixtures/context';
import { makeFixtureFetch } from './fixtures/fixtureFetch';
import { ConfirmAction } from './pages/resources/shared';
import { ErrorPanel } from './ui/ErrorPanel';

afterEach(cleanup);

/** The console's fixtures as the app's own key, deletions of numbers and users held for the owner. */
function console_() {
    const api = holding(makeFixtureFetch({ set: 'populated', actsAs: 'key' }), [
        { method: 'DELETE', path: /^\/v1\/phone_numbers\/[^/]+$/ },
        { method: 'DELETE', path: /^\/v1\/users\/[^/]+$/ },
    ]);
    const client = new NoClick({ apiKey: 'a-fixture-holds-no-key', baseUrl: DEFAULT_BASE_URL, maxRetries: 0, fetch: api.fetch });
    const live = createWorkLive();
    return { api, client, live, value: fixtureConsole({ client, actsAs: 'key', live }) };
}

describe('the console’s confirm', () => {
    it('closes on a held call and leaves a toast that follows it to done', async () => {
        const { api, client, live, value } = console_();
        const released = vi.fn();
        render(
            <ConsoleScope value={value}>
                <ConfirmAction
                    label="Release number"
                    title="Release +1 415 555 0101?"
                    description="It stops ringing and billing now."
                    confirmLabel="Release"
                    onConfirm={async () => {
                        await PhoneNumber.fromId('pn_1', { client }).release();
                        released();
                    }}
                />
                <Toaster />
            </ConsoleScope>
        );
        fireEvent.click(screen.getByRole('button', { name: 'Release number' }));
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Release' })));

        // The dialog's done: nothing failed, it waits on the owner.
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(screen.queryByRole('alert')).toBeNull();
        expect(released).not.toHaveBeenCalled();
        expect(await screen.findByText('Release +1 415 555 0101: waiting for approval')).toBeTruthy();
        expect(screen.getByText('Sent to the account’s owner to approve, by email. It goes ahead once they approve it.')).toBeTruthy();
        expect(api.held.map((h) => `${h.method} ${h.path}`)).toEqual(['DELETE /v1/phone_numbers/pn_1']);

        const frame = await api.approve();
        act(() => live.deliver('platform:resource', frame));
        expect(await screen.findByText('Release +1 415 555 0101: done')).toBeTruthy();
    });

    it('says the owner declined it, and why', async () => {
        const { api, client, live, value } = console_();
        render(
            <ConsoleScope value={value}>
                <ConfirmAction label="Release number" title="Release +1 415 555 0101?" description="" confirmLabel="Release" onConfirm={async () => void (await PhoneNumber.fromId('pn_1', { client }).release())} />
                <Toaster />
            </ConsoleScope>
        );
        fireEvent.click(screen.getByRole('button', { name: 'Release number' }));
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Release' })));
        await screen.findByText('Release +1 415 555 0101: waiting for approval');
        act(() => live.deliver('platform:resource', api.decline()));
        expect(await screen.findByText('Release +1 415 555 0101: not done')).toBeTruthy();
        expect(screen.getByText('The person declined it.')).toBeTruthy();
    });

    it('still shows any other refusal in the dialog', async () => {
        const { value } = console_();
        render(
            <ConsoleScope value={value}>
                <ConfirmAction
                    label="Release number"
                    title="Release it?"
                    description=""
                    confirmLabel="Release"
                    onConfirm={async () => {
                        throw new Error('Refused.');
                    }}
                />
            </ConsoleScope>
        );
        fireEvent.click(screen.getByRole('button', { name: 'Release number' }));
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Release' })));
        expect((await screen.findByRole('alert')).textContent).toContain('Refused.');
        expect(screen.getByRole('dialog')).toBeTruthy();
    });
});

describe('the console’s error panel', () => {
    it('says a held call waits on the owner, where it went, and follows it', async () => {
        const { api, client, live, value } = console_();
        let error: unknown;
        try {
            await PhoneNumber.fromId('pn_1', { client }).release();
        } catch (e) {
            error = e;
        }
        render(
            <ConsoleScope value={value}>
                <ErrorPanel error={error} />
            </ConsoleScope>
        );
        const notice = await screen.findByTestId('held-call');
        expect(notice.getAttribute('role')).toBe('status');
        expect(notice.textContent).toContain('DELETE /v1/phone_numbers/pn_1: waiting for approval');
        expect(screen.queryByRole('alert')).toBeNull();
        const frame = await api.approve();
        act(() => live.deliver('platform:resource', frame));
        await waitFor(() => expect(screen.getByTestId('held-call').getAttribute('data-phase')).toBe('done'));
    });
});

describe('a page’s own toast', () => {
    it('reports a held call and follows it, and leaves any other error to the page', async () => {
        const { api, client, live } = console_();
        const done = vi.fn();
        const { result } = renderHook(() => useReportHeld({ client, live }), {
            wrapper: ({ children }) => (
                <ClientProvider client={client}>
                    {children}
                    <Toaster />
                </ClientProvider>
            ),
        });
        expect(result.current(new Error('Refused.'), 'Delete acme')).toBe(false);
        let held: unknown;
        try {
            await client.request('DELETE', '/v1/users/acme');
        } catch (e) {
            held = e;
        }
        expect(result.current(held, 'Delete acme', done)).toBe(true);
        expect(await screen.findByText('Delete acme: waiting for approval')).toBeTruthy();
        const frame = await api.approve();
        act(() => live.deliver('platform:resource', frame));
        expect(await screen.findByText('Delete acme: done')).toBeTruthy();
        expect(done).toHaveBeenCalledTimes(1);
    });
});
