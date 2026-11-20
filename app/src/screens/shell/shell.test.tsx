// @vitest-environment happy-dom
// The app's frame and its sidebar, over what a host hands them: the pages with the open one marked, Resources' kinds
// under its row from the address, the foot kept as a rail folds it (the balance stays mounted, hidden), and on a
// phone the bar's name, a page's own actions and way back, the menu as a sheet that closes as it goes somewhere, and
// the builder's toggle.
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { KindId } from '@/screens/resources/kinds';
import { PhoneBarActions, PhoneBarBack } from '@/ui/phoneBar';
import { AppShell } from './AppShell';
import { SHELL_PAGES, shellPageFor, type ShellPageId } from './pages';
import { ShellSidebarContent } from './ShellSidebar';

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

function shell({ mobile = false, current = 'chat', address = '/', collapsed = false, builder, children }: { mobile?: boolean; current?: string; address?: string; collapsed?: boolean; builder?: { open: boolean; onToggle: () => void }; children?: React.ReactNode } = {}) {
    const onPage = vi.fn<(id: ShellPageId) => void>();
    const onKind = vi.fn<(kind: KindId | null) => void>();
    const onSearch = vi.fn();
    render(
        <MemoryRouter initialEntries={[address]}>
            <AppShell
                isMobile={mobile}
                sidebar={(frame) => (
                    <ShellSidebarContent
                        {...frame}
                        workspace={<span>Acme</span>}
                        onSearch={onSearch}
                        builder={builder}
                        pages={SHELL_PAGES}
                        current={current}
                        onPage={onPage}
                        onKind={onKind}
                        card={<section aria-label="A card">Card</section>}
                        balance={<span>$12 left</span>}
                        belowBalance={<span>Invite</span>}
                        account={<button type="button">Ada</button>}
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
                {children ?? <div>The page</div>}
            </AppShell>
        </MemoryRouter>
    );
    return { onPage, onKind, onSearch };
}

describe('the pages', () => {
    it('are named once each, and found by their id', () => {
        expect(new Set(SHELL_PAGES.map((p) => p.id)).size).toBe(SHELL_PAGES.length);
        expect(shellPageFor('flow')?.label).toBe('Automations');
        expect(shellPageFor('debug')).toBeUndefined();
    });
});

describe('the sidebar on a laptop', () => {
    it('lists the pages, marks the open one and goes to another', () => {
        const { onPage } = shell({ current: 'work' });
        const nav = screen.getByRole('navigation', { name: 'Main' });
        expect(within(nav).getAllByRole('button').map((b) => b.textContent)).toEqual(['Chat', 'Work', 'Automations', 'Connections', 'Resources', 'Settings']);
        expect(within(nav).getByRole('button', { name: 'Work' }).getAttribute('aria-current')).toBe('page');
        fireEvent.click(within(nav).getByRole('button', { name: 'Connections' }));
        expect(onPage).toHaveBeenCalledWith('connections');
    });

    it('opens Resources onto its kinds, the address’s kind marked, and goes to one', () => {
        const { onKind } = shell({ current: 'resources', address: '/resources?kind=domains' });
        const kinds = screen.getByRole('group', { name: 'Resource kinds' });
        expect(within(kinds).getByRole('button', { name: 'Domains' }).getAttribute('aria-current')).toBe('page');
        fireEvent.click(within(kinds).getByRole('button', { name: 'Numbers' }));
        expect(onKind).toHaveBeenCalledWith('numbers');
    });

    it('folds to a rail, keeping the balance mounted but hidden and the card and the row under it out', () => {
        shell({ collapsed: true });
        expect(screen.queryByRole('region', { name: 'A card' })).toBeNull();
        expect(screen.queryByText('Invite')).toBeNull();
        expect(screen.getByText('$12 left').closest('[data-onboarding="balance"]')?.className).toContain('hidden');
        expect(screen.getByRole('button', { name: 'Ada' })).toBeTruthy();
    });

    it('shows the builder’s row while a canvas is open', () => {
        const onToggle = vi.fn();
        shell({ current: 'flow', builder: { open: false, onToggle } });
        fireEvent.click(screen.getByRole('button', { name: 'Builder' }));
        expect(onToggle).toHaveBeenCalled();
    });
});

describe('the frame on a phone', () => {
    it('names the page, and opens the sidebar as a sheet that closes once it goes somewhere', () => {
        const { onPage } = shell({ mobile: true });
        expect(screen.getByText('Work')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
        const sheet = screen.getByRole('dialog');
        expect(within(sheet).getByText('Acme')).toBeTruthy();
        fireEvent.click(within(sheet).getByRole('button', { name: 'Settings' }));
        expect(onPage).toHaveBeenCalledWith('settings');
        expect(screen.queryByRole('dialog')).toBeNull();
    });

    it('puts a page’s actions and its way back in the bar, in place of the menu and the name', () => {
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
        act(() => fireEvent.click(screen.getByRole('button', { name: /Settings/ })));
        expect(back).toHaveBeenCalled();
    });

    it('toggles the builder over a canvas', () => {
        const onToggle = vi.fn();
        shell({ mobile: true, builder: { open: true, onToggle } });
        const toggle = screen.getByRole('button', { name: 'Builder' });
        expect(toggle.getAttribute('aria-pressed')).toBe('true');
        fireEvent.click(toggle);
        expect(onToggle).toHaveBeenCalled();
    });
});
