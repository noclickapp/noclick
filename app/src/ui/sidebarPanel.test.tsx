// @vitest-environment happy-dom
// Whether the laptop sidebar is folded to its rail: one value for every sidebar drawn (the app's and the developer
// console's), remembered on this device.
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

beforeEach(() => {
    window.localStorage.clear();
    vi.resetModules();
});
afterEach(cleanup);

async function load() {
    return import('@/ui/sidebarPanel');
}

it('folds every sidebar drawn at once, and remembers it on this device', async () => {
    const { useSidebarCollapsed } = await load();
    let fold: (collapsed: boolean) => void = () => undefined;
    function Sidebar({ name }: { name: string }) {
        const [collapsed, setCollapsed] = useSidebarCollapsed();
        fold = setCollapsed;
        return <p data-testid={name}>{collapsed ? 'rail' : 'open'}</p>;
    }
    const view = render(
        <>
            <Sidebar name="app" />
            <Sidebar name="console" />
        </>
    );
    expect([view.getByTestId('app').textContent, view.getByTestId('console').textContent]).toEqual(['open', 'open']);
    act(() => fold(true));
    expect([view.getByTestId('app').textContent, view.getByTestId('console').textContent]).toEqual(['rail', 'rail']);
    expect(window.localStorage.getItem('nc-sidebar-collapsed')).toBe('1');
});

it('opens folded where this device folded it last', async () => {
    window.localStorage.setItem('nc-sidebar-collapsed', '1');
    const { useSidebarCollapsed } = await load();
    function Sidebar() {
        return <p data-testid="sidebar">{useSidebarCollapsed()[0] ? 'rail' : 'open'}</p>;
    }
    expect(render(<Sidebar />).getByTestId('sidebar').textContent).toBe('rail');
});
