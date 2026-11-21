// @vitest-environment happy-dom
// The app's pages in the shell's frame, as its routes draw it (routes.ts: the home, the chat, Work and Resources in
// one layout, the developer console outside it). The sidebar goes to each page and to Resources' kinds by their
// routes and marks the one open, the account's name leads home, search opens the palette, and the account menu offers
// the console (with a sidebar of its own) and signing out. On a phone: the page's name in the bar and the pages as a sheet
// that closes as it goes. All of it reads only the account's status, which a key may.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { NoClick } from 'noclick';
import { createMemoryRouter, RouterProvider, useLocation } from 'react-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { ClientProvider } from '@/sdk/client';
import Shell from './shell';

const STATUS = {
    object: 'status',
    account: { id: 'acct_7f3a', name: 'Ada Lovelace', email: 'ada@example.test', acting_for: null },
    user_id: null,
    plan: { name: 'member' },
    balance: { remaining_usd: 42.5, unlimited: false },
    month: { period_start: '2026-11-01T00:00:00+00:00', resets_at: '2026-12-01T00:00:00+00:00', spent_usd: 7.25 },
};

/** Every call the frame made, as `METHOD /v1/path`. */
let calls: string[] = [];

const client = new NoClick({
    apiKey: 'held-by-this-app-server',
    baseUrl: 'http://app.test/api',
    maxRetries: 0,
    fetch: async (input, init) => {
        calls.push(`${init?.method ?? 'GET'} ${new URL(String(input)).pathname.replace(/^\/api/, '')}`);
        return new Response(JSON.stringify(STATUS), { status: 200, headers: { 'content-type': 'application/json' } });
    },
});

/** The page, saying where the app is. */
function Where() {
    const { pathname, search } = useLocation();
    return <div data-testid="where">{pathname + search}</div>;
}

function open(address: string) {
    const page = { element: <Where /> };
    const router = createMemoryRouter(
        [
            {
                path: '/',
                element: <Shell />,
                children: [{ index: true, ...page }, { path: 'chat', ...page }, { path: 'work', ...page }, { path: 'connections', ...page }, { path: 'resources', ...page }],
            },
            { path: '/developers/*', ...page },
        ],
        { initialEntries: [address] }
    );
    render(
        <ClientProvider client={client}>
            <RouterProvider router={router} />
        </ClientProvider>
    );
}

const where = () => screen.getByTestId('where').textContent;
const nav = () => within(screen.getByRole('navigation', { name: 'Main' }));
const current = () => nav().queryAllByRole('button').filter((b) => b.getAttribute('aria-current') === 'page').map((b) => b.textContent);

async function openAccountMenu() {
    const trigger = document.querySelector<HTMLElement>('[data-onboarding="user-menu"]')!;
    act(() => {
        trigger.focus();
        fireEvent.keyDown(trigger, { key: 'Enter' });
    });
    return screen.findByRole('menu');
}

/** A phone's width: every max-width query matches. */
function asPhone() {
    vi.spyOn(window, 'matchMedia').mockImplementation(
        (query: string) =>
            ({ matches: /max-width/.test(query), media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, dispatchEvent: () => false }) as unknown as MediaQueryList
    );
}

beforeAll(() => {
    Element.prototype.scrollIntoView ??= () => undefined;
});
beforeEach(() => {
    window.localStorage.clear();
    calls = [];
});
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

describe('the frame on a laptop', () => {
    it('lists the pages the app serves, marks the one open, and goes to each by its route', async () => {
        open('/');
        expect(nav().getAllByRole('button').map((b) => b.textContent)).toEqual(['Chat', 'Work', 'Connections', 'Resources']);
        expect(current()).toEqual([]);
        fireEvent.click(nav().getByRole('button', { name: 'Work' }));
        expect(where()).toBe('/work');
        expect(current()).toEqual(['Work']);
        fireEvent.click(nav().getByRole('button', { name: 'Connections' }));
        expect(where()).toBe('/connections');
        expect(current()).toEqual(['Connections']);
        fireEvent.click(nav().getByRole('button', { name: 'Chat' }));
        expect(where()).toBe('/chat');
        expect(current()).toEqual(['Chat']);
    });

    it('opens Resources onto its kinds and goes to a kind’s route', () => {
        open('/work');
        fireEvent.click(nav().getByRole('button', { name: 'Resources' }));
        expect(where()).toBe('/resources');
        fireEvent.click(within(screen.getByRole('group', { name: 'Resource kinds' })).getByRole('button', { name: 'Domains' }));
        expect(where()).toBe('/resources?kind=domains');
        expect(within(screen.getByRole('group', { name: 'Resource kinds' })).getByRole('button', { name: 'Domains' }).getAttribute('aria-current')).toBe('page');
    });

    it('leads home from the account’s name, as the API names the account', async () => {
        open('/chat');
        const home = await screen.findByRole('link', { name: /Ada Lovelace/ });
        fireEvent.click(home);
        expect(where()).toBe('/');
    });

    it('opens the palette from search and goes to a page from it', () => {
        open('/');
        fireEvent.click(screen.getByRole('button', { name: 'Search' }));
        const palette = screen.getByTestId('command-palette');
        fireEvent.change(within(palette).getByRole('textbox'), { target: { value: 'resources' } });
        fireEvent.keyDown(palette, { key: 'Enter' });
        expect(where()).toBe('/resources');
        expect(screen.queryByTestId('command-palette')).toBeNull();
    });

    it('signs out from the account menu, as the app’s own sign-out does', async () => {
        const submitted: { method: string; action: string }[] = [];
        vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(function (this: HTMLFormElement) {
            submitted.push({ method: this.method, action: new URL(this.action, 'http://app.test').pathname });
        });
        open('/work');
        await waitFor(() => expect(screen.getByText('Member plan')).toBeTruthy());
        fireEvent.click(within(await openAccountMenu()).getByText('Log out'));
        await waitFor(() => expect(submitted).toEqual([{ method: 'post', action: '/logout' }]));
    });

    it('offers the console in the account menu, which has a sidebar of its own', async () => {
        open('/work');
        const menu = await openAccountMenu();
        fireEvent.click(within(menu).getByText('Developers'));
        expect(where()).toBe('/developers');
        expect(screen.queryByTestId('app-sidebar')).toBeNull();
        expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull();
    });

    it('reads only the account’s status, which a key may', async () => {
        open('/resources');
        await waitFor(() => expect(screen.getByText('Member plan')).toBeTruthy());
        await openAccountMenu();
        act(() => {
            window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }));
        });
        expect(calls.length).toBeGreaterThan(0);
        expect([...new Set(calls)]).toEqual(['GET /v1/status']);
        expect(calls.filter((call) => isOwnerOnly(...(call.split(' ') as [string, string])))).toEqual([]);
    });
});

describe('the frame on a phone', () => {
    it('names the page in the bar, the chat going unnamed, and opens the pages as a sheet that closes as it goes', async () => {
        asPhone();
        open('/work');
        const bar = () => screen.getByRole('banner');
        await waitFor(() => expect(within(bar()).getByText('Work')).toBeTruthy());
        fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
        const sheet = await screen.findByRole('dialog');
        fireEvent.click(within(sheet).getByRole('button', { name: 'Chat' }));
        expect(where()).toBe('/chat');
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(within(bar()).queryByText('Work')).toBeNull();
        expect(bar().textContent).toBe('');
    });

    it('goes home from the account’s name in the sheet, closing it', async () => {
        asPhone();
        open('/resources');
        await waitFor(() => expect(within(screen.getByRole('banner')).getByText('Resources')).toBeTruthy());
        fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
        const sheet = await screen.findByRole('dialog');
        fireEvent.click(await within(sheet).findByRole('link', { name: /Ada Lovelace/ }));
        expect(where()).toBe('/');
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(within(screen.getByRole('banner')).getByText('NoClick')).toBeTruthy();
    });
});
