// @vitest-environment happy-dom
// The frame told where a host's pages are (`places`), as NoClick's own app tells it its `?tab=` addresses: it marks the
// page the host says is open, goes to a page or a Resources kind through the host, offers the builder's toggle the host
// hands it in the sidebar and the phone bar, and opens its palette from search.
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { NoClick } from 'noclick';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import type { KindId } from '@/screens/resources/kinds';
import { AppFrame } from './AppFrame';

const client = new NoClick({
    apiKey: 'held-by-this-app-server',
    baseUrl: 'http://app.test/api',
    maxRetries: 0,
    fetch: async () => Response.json({ object: 'status', account: { id: 'acct_7f3a', name: 'Ada Lovelace', email: 'ada@example.test' }, plan: { name: 'member' } }),
});

function frame({ current, mobile = false, builder }: { current: string; mobile?: boolean; builder?: { open: boolean; onToggle: () => void } }) {
    const go = vi.fn<(page: string) => void>();
    const goKind = vi.fn<(kind: KindId | null) => void>();
    render(
        <ClientProvider client={client}>
            <MemoryRouter initialEntries={[`/dashboard?tab=${current}`]}>
                <AppFrame
                    isMobile={mobile}
                    user={{ email: 'ada@example.test', display_name: 'Ada Lovelace' }}
                    places={{ current, go, goKind }}
                    builderToggle={builder}
                    collapsed={false}
                    onCollapsedChange={() => undefined}
                    title="Automations"
                    builder={<aside aria-label="Builder chat" />}
                    builderShown={!!builder?.open}
                    builderWidth={400}
                    animate={false}
                >
                    <p>The page</p>
                </AppFrame>
            </MemoryRouter>
        </ClientProvider>
    );
    return { go, goKind };
}

const nav = () => within(screen.getByRole('navigation', { name: 'Main' }));

beforeAll(() => {
    Element.prototype.scrollIntoView ??= () => undefined;
});
afterEach(cleanup);

describe('the frame at a host’s places', () => {
    it('marks the page the host says is open, and goes to a page and a kind through the host', () => {
        const { go, goKind } = frame({ current: 'resources' });
        expect(nav().getByRole('button', { name: 'Resources' }).getAttribute('aria-current')).toBe('page');
        fireEvent.click(nav().getByRole('button', { name: 'Work' }));
        expect(go).toHaveBeenCalledWith('work');
        fireEvent.click(within(screen.getByRole('group', { name: 'Resource kinds' })).getByRole('button', { name: 'Domains' }));
        expect(goKind).toHaveBeenCalledWith('domains');
    });

    it('offers the host’s builder toggle in the sidebar, and on a phone in the bar', () => {
        const onToggle = vi.fn();
        frame({ current: 'flow', builder: { open: false, onToggle } });
        fireEvent.click(screen.getByRole('button', { name: 'Builder' }));
        expect(onToggle).toHaveBeenCalledTimes(1);
        cleanup();
        frame({ current: 'flow', mobile: true, builder: { open: true, onToggle } });
        expect(screen.getByRole('button', { name: 'Builder' }).getAttribute('aria-pressed')).toBe('true');
    });

    it('opens its palette from search', () => {
        frame({ current: 'chat' });
        fireEvent.click(screen.getByRole('button', { name: 'Search' }));
        expect(screen.getByTestId('command-palette')).toBeTruthy();
    });
});
