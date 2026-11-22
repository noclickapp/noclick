// @vitest-environment happy-dom
// The app's frame and its sidebar. With no host's fills: the pages the app serves, the account's name atop it, nothing
// at the foot but the account, whose plan the platform API names and whose menu offers the console, Usage and Community. With
// a host's: every page, its card, balance and row at the foot (the balance kept, hidden, on a rail), its menu rows and
// staff's, what opens around the account, and its banner. And how it moves: Resources' kinds from the address, the
// builder's row, and on a phone the bar's name, a page's actions and way back, the sheet that closes as it goes, and
// the builder's toggle.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { NoClick } from 'noclick';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fill, type Slot } from '@/slots';
import { ClientProvider } from '@/sdk/client';
import type { KindId } from '@/screens/resources/kinds';
import { DropdownMenuItem } from '@/ui/dropdown-menu';
import { PhoneBarActions, PhoneBarBack } from '@/ui/phoneBar';
import { AppShell } from './AppShell';
import { SHELL_PAGES, shellPageFor } from './pages';
import { ShellSidebarContent } from './ShellSidebar';
import { ACCOUNT_AROUND, ACCOUNT_BILLING, ACCOUNT_ITEMS, ACCOUNT_SESSION, ACCOUNT_STAFF, ACCOUNT_SWITCH, BANNER, FOOT_BALANCE, FOOT_CARD, FOOT_INVITE, PAGES, WORKSPACE } from './slots';

const SLOTS: Slot<unknown>[] = [PAGES, WORKSPACE, FOOT_CARD, FOOT_BALANCE, FOOT_INVITE, ACCOUNT_SESSION, ACCOUNT_SWITCH, ACCOUNT_BILLING, ACCOUNT_ITEMS, ACCOUNT_STAFF, ACCOUNT_AROUND, BANNER];

beforeEach(() => window.localStorage.clear());
afterEach(() => {
    cleanup();
    // Each test starts from the standards: a host's fills stand until filled again.
    for (const s of SLOTS) fill(s, s.standard);
});

const STATUS = {
    object: 'status',
    account: { id: 'acct_7f3a', name: 'Ada Lovelace', email: 'ada@example.test', acting_for: null },
    user_id: null,
    plan: { name: 'member' },
    balance: { remaining_usd: 42.5, unlimited: false },
    month: { period_start: '2026-11-01T00:00:00+00:00', resets_at: '2026-12-01T00:00:00+00:00', spent_usd: 7.25 },
};

/** A client whose every call reads the account's status. */
const client = new NoClick({
    apiKey: 'held-by-this-app-server',
    baseUrl: 'http://app.test/api',
    maxRetries: 0,
    fetch: async () => new Response(JSON.stringify(STATUS), { status: 200, headers: { 'content-type': 'application/json' } }),
});

interface Options {
    mobile?: boolean;
    current?: string;
    address?: string;
    collapsed?: boolean;
    builder?: { open: boolean; onToggle: () => void };
    children?: ReactNode;
}

function shell({ mobile = false, current = 'chat', address = '/', collapsed = false, builder, children }: Options = {}) {
    const onPage = vi.fn<(page: string) => void>();
    const onKind = vi.fn<(kind: KindId | null) => void>();
    render(
        <ClientProvider client={client}>
            <MemoryRouter initialEntries={[address]}>
                <AppShell
                    isMobile={mobile}
                    sidebar={(frame) => (
                        <ShellSidebarContent
                            {...frame}
                            user={{ email: 'ada@example.test', display_name: 'Ada Lovelace' }}
                            onSearch={() => undefined}
                            builder={builder}
                            current={current}
                            onPage={onPage}
                            onKind={onKind}
                        />
                    )}
                    collapsed={collapsed}
                    onCollapsedChange={() => undefined}
                    title="Work"
                    builder={<aside aria-label="Builder chat" />}
                    builderShown={!!builder?.open}
                    builderToggle={builder}
                    builderWidth={400}
                    animate={false}
                >
                    {children ?? <Where />}
                </AppShell>
            </MemoryRouter>
        </ClientProvider>
    );
    return { onPage, onKind };
}

/** The page, saying where the app is. */
function Where() {
    return <div data-testid="where">{useLocation().pathname}</div>;
}

const navButtons = () => within(screen.getByRole('navigation', { name: 'Main' })).getAllByRole('button');

async function openAccountMenu() {
    const trigger = document.querySelector<HTMLElement>('[data-onboarding="user-menu"]')!;
    act(() => {
        trigger.focus();
        fireEvent.keyDown(trigger, { key: 'Enter' });
    });
    return screen.findByRole('menu');
}

describe('the pages', () => {
    it('are named once each, and found by their id', () => {
        expect(new Set(SHELL_PAGES.map((p) => p.id)).size).toBe(SHELL_PAGES.length);
        expect(shellPageFor('flow')?.label).toBe('Automations');
        expect(shellPageFor('debug')).toBeUndefined();
    });
});

describe('the sidebar with nothing filled', () => {
    it('lists the pages the app serves, under the account’s name', () => {
        shell({ current: 'work' });
        expect(navButtons().map((b) => b.textContent)).toEqual(['Chat', 'Work', 'Automations', 'Connections', 'Resources', 'Settings']);
        expect(screen.getByRole('button', { name: 'Work' }).getAttribute('aria-current')).toBe('page');
        expect(screen.getByText('Ada Lovelace', { selector: 'span.truncate.px-1\\.5' })).toBeTruthy();
    });

    it('keeps nothing at the foot but the account, its plan as the API names it', async () => {
        shell();
        expect(document.querySelector('[data-onboarding="balance"]')).toBeNull();
        await waitFor(() => expect(screen.getByText('Member plan')).toBeTruthy());
    });

    it('offers the console, feedback and Community in the account menu', async () => {
        shell();
        const menu = await openAccountMenu();
        expect(within(menu).getByText('Community')).toBeTruthy();
        expect(within(menu).getByText('Send feedback')).toBeTruthy();
        fireEvent.click(within(menu).getByText('Developers'));
        expect(screen.getByTestId('where').textContent).toBe('/developers');
    });

    it('offers what each thing cost in the account menu, at /usage', async () => {
        shell();
        fireEvent.click(within(await openAccountMenu()).getByText('Usage'));
        expect(screen.getByTestId('where').textContent).toBe('/usage');
    });
});

describe('the sidebar a host fills', () => {
    it('lists every page, its workspace atop it, and its card, balance and row at the foot', () => {
        fill(PAGES, SHELL_PAGES.map((p) => p.id));
        fill(WORKSPACE, () => <span>Acme</span>);
        fill(FOOT_CARD, () => <section aria-label="A card" />);
        fill(FOOT_BALANCE, () => <span>$12 left</span>);
        fill(FOOT_INVITE, () => <span>Invite</span>);
        const { onPage } = shell();
        expect(navButtons().map((b) => b.textContent)).toEqual(['Chat', 'Work', 'Automations', 'Connections', 'Resources', 'Settings']);
        expect(screen.getByText('Acme')).toBeTruthy();
        expect(screen.getByRole('region', { name: 'A card' })).toBeTruthy();
        expect(screen.getByText('Invite')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Connections' }));
        expect(onPage).toHaveBeenCalledWith('connections');
    });

    it('folds to a rail, keeping the balance mounted but hidden and the card and row out', () => {
        fill(FOOT_CARD, () => <section aria-label="A card" />);
        fill(FOOT_BALANCE, () => <span>$12 left</span>);
        fill(FOOT_INVITE, () => <span>Invite</span>);
        shell({ collapsed: true });
        expect(screen.queryByRole('region', { name: 'A card' })).toBeNull();
        expect(screen.queryByText('Invite')).toBeNull();
        expect(screen.getByText('$12 left').closest('[data-onboarding="balance"]')?.className).toContain('hidden');
    });

    it('puts its rows in the account menu, its plan and sign-out on the account, and wraps the row', async () => {
        const signOut = vi.fn();
        fill(ACCOUNT_SESSION, { usePlan: () => 'pro', useSignOut: () => signOut });
        fill(ACCOUNT_SWITCH, null);
        fill(ACCOUNT_BILLING, () => <DropdownMenuItem>Upgrade</DropdownMenuItem>);
        fill(ACCOUNT_ITEMS, () => <DropdownMenuItem>Chat with us</DropdownMenuItem>);
        fill(ACCOUNT_STAFF, ({ go }) => <DropdownMenuItem onClick={() => go('debug')}>Debug</DropdownMenuItem>);
        fill(ACCOUNT_AROUND, ({ children }) => <div data-testid="around">{children}</div>);
        const { onPage } = shell();
        expect(screen.getByTestId('around').querySelector('[data-onboarding="user-menu"]')).toBeTruthy();
        expect(screen.getByText('Pro plan')).toBeTruthy();
        const menu = await openAccountMenu();
        expect(within(menu).queryByText('Developers')).toBeNull();
        const rows = within(menu).getAllByRole('menuitem').map((row) => row.textContent?.trim());
        // The host's rows stand in the standard's place: no feedback row of the app's.
        expect(rows).not.toContain('Send feedback');
        expect(rows.indexOf('Upgrade')).toBeLessThan(rows.indexOf('Chat with us'));
        expect(rows.indexOf('Chat with us')).toBeLessThan(rows.indexOf('Community'));
        expect(rows.indexOf('Community')).toBeLessThan(rows.indexOf('Debug'));
        fireEvent.click(within(menu).getByText('Debug'));
        expect(onPage).toHaveBeenCalledWith('debug');
        fireEvent.click(within(await openAccountMenu()).getByText('Log out'));
        expect(signOut).toHaveBeenCalled();
    });

    it('draws its banner over the page, on a laptop and a phone', () => {
        fill(BANNER, () => <div role="status">Viewing as someone</div>);
        shell();
        expect(screen.getByRole('status').textContent).toBe('Viewing as someone');
        cleanup();
        shell({ mobile: true });
        expect(screen.getByRole('status').textContent).toBe('Viewing as someone');
    });
});

describe('moving about', () => {
    it('opens Resources onto its kinds, the address’s kind marked, and goes to one', () => {
        const { onKind } = shell({ current: 'resources', address: '/resources?kind=domains' });
        const kinds = screen.getByRole('group', { name: 'Resource kinds' });
        expect(within(kinds).getByRole('button', { name: 'Domains' }).getAttribute('aria-current')).toBe('page');
        fireEvent.click(within(kinds).getByRole('button', { name: 'Numbers' }));
        expect(onKind).toHaveBeenCalledWith('numbers');
    });

    it('shows the builder’s row while a canvas is open', () => {
        const onToggle = vi.fn();
        shell({ builder: { open: false, onToggle } });
        fireEvent.click(screen.getByRole('button', { name: 'Builder' }));
        expect(onToggle).toHaveBeenCalled();
    });

    it('on a phone, opens the sidebar as a sheet that closes once it goes somewhere', () => {
        const { onPage } = shell({ mobile: true });
        expect(screen.getByText('Work')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
        const sheet = screen.getByRole('dialog');
        fireEvent.click(within(sheet).getByRole('button', { name: 'Resources' }));
        expect(screen.queryByRole('dialog')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
        fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Work' }));
        expect(onPage).toHaveBeenCalledWith('work');
        expect(screen.queryByRole('dialog')).toBeNull();
    });

    it('on a phone, puts a page’s actions and its way back in the bar, in place of the menu and the name', () => {
        const back = vi.fn();
        shell({
            mobile: true,
            children: (
                <>
                    <PhoneBarBack label="Settings" title="Alerts" onBack={back} />
                    <PhoneBarActions>
                        <button type="button">Save</button>
                    </PhoneBarActions>
                </>
            ),
        });
        expect(screen.getByRole('button', { name: 'Save' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Open menu' }).className).toContain('hidden');
        fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
        expect(back).toHaveBeenCalled();
    });

    it('on a phone, toggles the builder over a canvas', () => {
        const onToggle = vi.fn();
        shell({ mobile: true, builder: { open: true, onToggle } });
        const toggle = screen.getByRole('button', { name: 'Builder' });
        expect(toggle.getAttribute('aria-pressed')).toBe('true');
        fireEvent.click(toggle);
        expect(onToggle).toHaveBeenCalled();
    });
});
