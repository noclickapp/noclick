// @vitest-environment jsdom
// The sidebar's Resources row is one disclosure, as in Cloudflare's sidebar: it opens onto the overview, and clicked
// again while open it folds its kinds away. The chevron is part of the row, never a button of its own.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ResourcesNav } from '~/components/shell/AppSidebar';
import { SHELL_PAGES } from '~/components/shell/pages';

const page = SHELL_PAGES.find((p) => p.id === 'resources')!;
let switches: { tab: string; params?: Record<string, string | null> }[] = [];
const onSwitch = (e: Event) => switches.push((e as CustomEvent).detail);

function renderNav(current: boolean) {
    return render(
        <MemoryRouter initialEntries={[current ? '/dashboard?tab=resources' : '/dashboard?tab=chat']}>
            <ResourcesNav page={page} current={current} collapsed={false} />
        </MemoryRouter>
    );
}

const row = () => screen.getByRole('button', { name: 'Resources' });
const kinds = () => screen.queryByRole('group', { name: 'Resource kinds' });

describe('the Resources row', () => {
    beforeEach(() => {
        switches = [];
        window.localStorage.clear();
        window.addEventListener('noclick:switch-tab', onSwitch);
    });
    afterEach(() => {
        window.removeEventListener('noclick:switch-tab', onSwitch);
        cleanup();
    });

    it('folds its kinds when clicked while open, and opens onto the overview when clicked again', () => {
        renderNav(true);
        expect(kinds()).not.toBeNull();
        expect(row().getAttribute('aria-expanded')).toBe('true');

        fireEvent.click(row());
        expect(kinds()).toBeNull();
        expect(row().getAttribute('aria-expanded')).toBe('false');
        expect(switches).toEqual([]);
        expect(window.localStorage.getItem('nc-sidebar-resources-open')).toBe('0');

        fireEvent.click(row());
        expect(kinds()).not.toBeNull();
        expect(switches.map((s) => s.tab)).toEqual(['resources']);
        // The overview: no kind, no item, no buy page and nothing from inside an item.
        expect(switches[0].params).toMatchObject({ kind: null, resource: null, new: null, path: null });
    });

    it('goes to the overview from another page, keeping its kinds open', () => {
        window.localStorage.setItem('nc-sidebar-resources-open', '1');
        renderNav(false);
        expect(kinds()).not.toBeNull();
        fireEvent.click(row());
        expect(kinds()).not.toBeNull();
        expect(switches.map((s) => s.tab)).toEqual(['resources']);
    });

    it('leaves a buy page for the kind it names', () => {
        render(
            <MemoryRouter initialEntries={['/dashboard?tab=resources&kind=numbers&new=1']}>
                <ResourcesNav page={page} current collapsed={false} />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByRole('button', { name: 'Files' }));
        expect(switches).toEqual([{ tab: 'resources', params: expect.objectContaining({ kind: 'files', new: null, resource: null }) }]);
    });

    it('has no button for the chevron of its own', () => {
        renderNav(true);
        expect(screen.queryByRole('button', { name: /resource kinds/i })).toBeNull();
    });
});
