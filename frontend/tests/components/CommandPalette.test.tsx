// @vitest-environment jsdom
// The command palette as a person meets it: ⌘K, type, the place they meant on top. A place named by the query leads
// (domains → Domains, ahead of the Resources page), a word for it finds it (logout → Sign out), a deployment's own
// places arrive through the registered source, the person's own things are found by name, and what they went to
// last is offered first the next time.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const WORKFLOWS = [{ id: 'wf1', name: 'Weekly digest', updated_at: '2026-10-20T00:00:00Z', node_count: 3 }];
const FOLDERS = [{ id: 'f1', name: 'Marketing', description: '', workflow_count: 1 }];
const store = vi.hoisted(() => ({
    getAllWorkflows: () => WORKFLOWS,
    getAllFolders: () => FOLDERS,
    loadAllWorkflows: () => undefined,
}));
vi.mock('~/hooks/WorkflowBrowserDataProvider', () => ({ useWorkflowBrowserDataContext: () => store }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ logActivity: () => undefined }) }));
vi.mock('~/hooks/useCachedValtioState', () => ({ useCachedValtioState: <T,>(_p: string, _k: string, initial: T) => useState(initial) }));
vi.mock('~/hooks/useValtioState', () => ({ useValtioState: <T,>(_p: string, _k: string, initial: T) => useState(initial) }));
vi.mock('~/hooks/useInstanceCapabilities', () => ({ useInstanceCapabilities: () => ({ billing: true }) }));
vi.mock('~/hooks/usePhoneLinking', () => ({ usePhoneLinkingAvailable: () => true }));
vi.mock('~/hooks/useTheme', () => ({ useTheme: () => ['dark', () => undefined] }));
vi.mock('~/components/shell/resources/platform', () => ({ hasPlatformResources: () => true }));
const credentials = vi.hoisted(() => ({
    rows: [
        {
            id: 'c1',
            name: 'Work mail',
            credential_type: 'gmail_oauth',
            access_type: 'owner',
            created_at: '2026-10-01T00:00:00Z',
            metadata: { email: 'sam@example.com' },
        },
    ],
}));
vi.mock('~/hooks/useCachedCredentialList', () => ({ useCredentialList: () => ({ credentials: credentials.rows, loaded: true }) }));
vi.mock('~/components/workflow/MCPConnectModal', () => ({ NoClickMCPSetupModal: () => null }));
vi.mock('~/components/workflow/WorkflowBrowserCards', () => ({ relativeShort: () => '1d' }));
vi.mock('~/components/shared/NodeIconStack', () => ({ NodeIconStack: () => null }));

import { CommandPalette } from '~/components/command/CommandPalette';
import { registerPaletteSource, rememberPaletteEntries, type PaletteSourceProps } from '~/components/command/sources';
import { Globe, Wrench } from 'lucide-react';
import { consumePendingFlowIntent } from '~/lib/navigation';

// A deployment's source: one place, and one thing done in place.
const added = vi.fn();
const ENTRIES = [
    { id: 'nav:elsewhere', label: 'Elsewhere', context: 'Another app', icon: Globe, keywords: 'faraway', run: added },
    { id: 'account:tool', label: 'Fix it', icon: Wrench, action: true, run: added },
];
function Source({ onEntries }: PaletteSourceProps) {
    useEffect(() => onEntries(ENTRIES), [onEntries]);
    return null;
}
registerPaletteSource(Source);

beforeAll(() => {
    Element.prototype.scrollIntoView ??= () => undefined;
});

let switches: { tab: string; params?: Record<string, string | null> }[] = [];
const onSwitch = (e: Event) => switches.push((e as CustomEvent).detail);

beforeEach(() => {
    window.localStorage.clear();
    switches = [];
    window.addEventListener('noclick:switch-tab', onSwitch);
});
afterEach(() => {
    window.removeEventListener('noclick:switch-tab', onSwitch);
    cleanup();
});

function openPalette() {
    act(() => {
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }));
    });
    return screen.getByTestId('command-palette');
}

function search(text: string) {
    fireEvent.change(screen.getByRole('textbox'), { target: { value: text } });
}

/** The rows on screen, top first, as "Name · Context". */
function rows(): string[] {
    return [...document.querySelectorAll<HTMLElement>('[data-cmd-index]')].map((row) => {
        const context = row.querySelector('[data-cmd-context]')?.textContent;
        const name = row.querySelector('span > span')?.textContent ?? '';
        return context ? `${name} · ${context}` : name;
    });
}

const sectionTitles = () => [...document.querySelectorAll('[data-cmd-section]')].map((h) => h.textContent);

describe('the command palette', () => {
    it('puts Domains first for "domains", and goes there', () => {
        render(<CommandPalette />);
        openPalette();
        search('domains');
        expect(rows()[0]).toBe('Domains · Resources');
        expect(rows()).not.toContain('Resources');

        fireEvent.keyDown(screen.getByTestId('command-palette'), { key: 'Enter' });
        expect(switches).toEqual([{ tab: 'resources', params: expect.objectContaining({ kind: 'domains', resource: null, new: null }) }]);
    });

    it('finds a place by another word for it, and a command by its own', () => {
        render(<CommandPalette />);
        openPalette();
        search('dns');
        expect(rows()[0]).toBe('Domains · Resources');
        search('logout');
        expect(rows()[0]).toBe('Sign out');
        search('api key');
        expect(rows()[0]).toBe('Developer · Settings');
    });

    it("lists a deployment's places with the app's, and its in-place commands with the account's", () => {
        render(<CommandPalette />);
        openPalette();
        search('faraway');
        expect(rows()).toEqual(['Elsewhere · Another app']);
        expect(sectionTitles()).toEqual(['Go to']);
        search('fix it');
        expect(sectionTitles()[0]).toBe('Account');
    });

    it("finds the person's own things by name: automations, folders, accounts, and what pages handed over", () => {
        act(() =>
            rememberPaletteEntries('Channels', [{ id: 'channel:x', label: 'launch-week', context: 'Acme', icon: Globe, run: () => undefined }])
        );
        render(<CommandPalette />);
        openPalette();
        search('weekly');
        expect(rows()[0]).toBe('Weekly digest');
        search('marketing');
        expect(rows()[0]).toBe('Marketing');
        fireEvent.keyDown(screen.getByTestId('command-palette'), { key: 'Enter' });
        expect(consumePendingFlowIntent()).toEqual({ kind: 'folder', folderId: 'f1' });

        openPalette();
        search('sam@example');
        expect(rows()[0]).toMatch(/· sam@example\.com$/);
        search('launch');
        expect(rows()[0]).toBe('launch-week · Acme');
        expect(sectionTitles()[0]).toBe('Channels');
    });

    it('offers where you went last before anything is typed', () => {
        render(<CommandPalette />);
        openPalette();
        expect(sectionTitles()).not.toContain('Recent');
        search('skills');
        expect(rows()[0]).toBe('Skills · Settings');
        fireEvent.keyDown(screen.getByTestId('command-palette'), { key: 'Enter' });
        expect(screen.queryByTestId('command-palette')).toBeNull();

        openPalette();
        expect(sectionTitles()[0]).toBe('Recent');
        expect(rows()[0]).toBe('Skills · Settings');
    });
});
