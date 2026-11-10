// @vitest-environment happy-dom
// VirtualTileGrid draws only the rows near the viewport of the page that scrolls it, with as many columns as its
// grid lays out. happy-dom lays nothing out, so sizes and resolved grid tracks are given here as a browser would
// compute them: a 300px viewport, 78px rows, and the three tracks `lg:grid-cols-3` resolves to.
import { act, cleanup, render } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { VirtualTileGrid } from '~/components/shell/Tile';
import { gridColumnCount, scrollParentOf } from '~/hooks/useVirtualGrid';

const VIEWPORT = 300;
const ROW = 78;
const COUNT = 1200;
const COLUMNS = 3;

const offsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
        configurable: true,
        get(this: HTMLElement) {
            return this.dataset.page ? VIEWPORT : ROW;
        },
    });
    const computed = window.getComputedStyle.bind(window);
    vi.spyOn(window, 'getComputedStyle').mockImplementation((element, pseudo) => {
        const style = computed(element, pseudo);
        if ((element as HTMLElement).dataset?.testid !== 'grid') return style;
        return new Proxy(style, {
            get: (target, key) => (key === 'gridTemplateColumns' ? Array(COLUMNS).fill('330px').join(' ') : Reflect.get(target, key)),
        });
    });
});
afterAll(() => {
    if (offsetHeight) Object.defineProperty(HTMLElement.prototype, 'offsetHeight', offsetHeight);
    vi.restoreAllMocks();
});
afterEach(cleanup);

function Page() {
    return (
        <div data-page="1" style={{ overflowY: 'auto', height: VIEWPORT }}>
            <h1>Connections</h1>
            <VirtualTileGrid
                items={Array.from({ length: COUNT }, (_, i) => i)}
                testId="grid"
                renderTile={(i) => (
                    <div key={i} data-tile={i}>
                        App {i}
                    </div>
                )}
            />
        </div>
    );
}

const drawn = (container: HTMLElement) => [...container.querySelectorAll<HTMLElement>('[data-tile]')].map((el) => Number(el.dataset.tile));

describe('useVirtualGrid', () => {
    it('counts the columns a grid resolves to, one when it declares none', () => {
        const grid = document.createElement('div');
        document.body.append(grid);
        expect(gridColumnCount(grid)).toBe(1);
        grid.dataset.testid = 'grid';
        expect(gridColumnCount(grid)).toBe(COLUMNS);
        grid.remove();
    });

    it('scrolls with the nearest ancestor that scrolls', () => {
        const { getByTestId } = render(<Page />);
        expect(scrollParentOf(getByTestId('grid')).dataset.page).toBe('1');
    });
});

describe('VirtualTileGrid', () => {
    it('draws only the rows near the viewport, in whole rows, and keeps the height of every row', () => {
        const { container, getByTestId } = render(<Page />);
        const tiles = drawn(container);
        expect(tiles[0]).toBe(0);
        expect(tiles.length).toBeLessThan(40);
        expect(tiles.length % COLUMNS).toBe(0);
        expect(tiles).toEqual(tiles.map((_, i) => i));
        expect(parseFloat(getByTestId('grid').style.height)).toBe((COUNT / COLUMNS) * ROW);
    });

    it('draws the last row once the page scrolls to the end', async () => {
        const { container } = render(<Page />);
        const page = container.querySelector<HTMLElement>('[data-page]')!;
        await act(async () => {
            page.scrollTop = (COUNT / COLUMNS) * ROW;
            page.dispatchEvent(new Event('scroll'));
        });
        const tiles = drawn(container);
        expect(tiles).toContain(COUNT - 1);
        expect(tiles).not.toContain(0);
        expect(tiles.length).toBeLessThan(40);
    });
});
