// @vitest-environment happy-dom
// The ⌘K palette as the open app has it: it goes to the pages the app serves and Resources' kinds by their routes, finds
// what a page handed it and offers the theme, the keyboard shortcuts and signing out; nothing of pages it doesn't serve.
// And with a host's commands in its slot: those rows, its "Open …" narrowing with the placeholder it names, and what
// it draws beside the palette.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NoClick } from 'noclick';
import { Globe } from 'lucide-react';
import { MemoryRouter, useLocation } from 'react-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fill } from '@/slots';
import { ClientProvider } from '@/sdk/client';
import { PALETTE, type PaletteHost } from '../slots';
import { CommandPalette } from './CommandPalette';
import { openCommandPalette } from './open';
import { forgetPaletteEntries, rememberPaletteEntries } from './sources';

const client = new NoClick({
    apiKey: 'held-by-this-app-server',
    baseUrl: 'http://app.test/api',
    maxRetries: 0,
    fetch: async () => new Response(JSON.stringify({ object: 'status', account: { id: 'acct_7f3a' }, plan: null }), { status: 200, headers: { 'content-type': 'application/json' } }),
});

function Where() {
    return <div data-testid="where">{useLocation().pathname + useLocation().search}</div>;
}

function show() {
    render(
        <ClientProvider client={client}>
            <MemoryRouter initialEntries={['/chat']}>
                <CommandPalette />
                <Where />
            </MemoryRouter>
        </ClientProvider>
    );
}

function openPalette() {
    act(() => {
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }));
    });
    return screen.getByTestId('command-palette');
}

const search = (text: string) => fireEvent.change(screen.getByRole('textbox'), { target: { value: text } });
const rows = () =>
    [...document.querySelectorAll<HTMLElement>('[data-cmd-index]')].map((row) => {
        const context = row.querySelector('[data-cmd-context]')?.textContent;
        const name = row.querySelector('span > span')?.textContent ?? '';
        return context ? `${name} · ${context}` : name;
    });
const sections = () => [...document.querySelectorAll('[data-cmd-section]')].map((h) => h.textContent);

beforeAll(() => {
    Element.prototype.scrollIntoView ??= () => undefined;
});
beforeEach(() => window.localStorage.clear());
afterEach(() => {
    cleanup();
    forgetPaletteEntries();
    fill(PALETTE, PALETTE.standard);
});

describe('the open app’s palette', () => {
    it('goes to the pages the app serves, and offers the account’s commands', () => {
        show();
        openPalette();
        expect(sections()).toEqual(['Go to', 'Account']);
        expect(rows()).toEqual(['Chat', 'Work', 'Resources', 'Switch to light theme', 'Switch to dark theme', 'Switch to system theme', 'Open keyboard shortcuts', 'Sign out']);
    });

    it('finds a Resources kind by a word for it and goes to its route', () => {
        show();
        openPalette();
        search('dom');
        expect(rows()[0]).toBe('Domains · Resources');
        fireEvent.keyDown(screen.getByTestId('command-palette'), { key: 'Enter' });
        expect(screen.getByTestId('where').textContent).toBe('/resources?kind=domains');
        expect(screen.queryByTestId('command-palette')).toBeNull();
    });

    it('lists nothing of a page it doesn’t serve', () => {
        show();
        openPalette();
        search('automations');
        expect(rows()).not.toContain('Automations');
        search('connections');
        expect(rows()).not.toContain('Connections');
    });

    it('finds what a page handed it', () => {
        const run = vi.fn();
        rememberPaletteEntries('Work', [{ id: 'work:channel:c1', label: 'launch-room', context: 'Channels', icon: Globe, run }]);
        show();
        openPalette();
        search('launch');
        expect(rows()[0]).toBe('launch-room · Channels');
        fireEvent.keyDown(screen.getByTestId('command-palette'), { key: 'Enter' });
        expect(run).toHaveBeenCalled();
    });

    it('opens its keyboard shortcuts on "?"', () => {
        show();
        act(() => {
            window.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));
        });
        expect(screen.getByPlaceholderText('Search shortcuts…')).toBeTruthy();
        expect(sections()).toEqual(['General']);
    });
});

describe('a host’s palette', () => {
    it('lists its commands, narrows to a scope with its placeholder, and draws what it keeps beside', () => {
        const run = vi.fn();
        const host: PaletteHost = {
            useCommands: () => ({
                commands: [
                    { id: 'wf:1', label: 'Weekly digest', section: 'Workflows', icon: Globe, run },
                    { id: 'nav:elsewhere', label: 'Elsewhere', section: 'Go to', icon: Globe, browse: true, run },
                ],
                beside: <div data-testid="beside" />,
            }),
            scopes: [{ scope: 'Workflows', label: 'Open automation…' }],
            shortcuts: [],
        };
        fill(PALETTE, host);
        show();
        expect(screen.getByTestId('beside')).toBeTruthy();
        openPalette();
        expect(rows()).toEqual(['Elsewhere', 'Weekly digest']);
        act(() => openCommandPalette('Workflows'));
        expect(screen.getByPlaceholderText('Open automation…')).toBeTruthy();
        expect(rows()).toEqual(['Weekly digest']);
    });
});
