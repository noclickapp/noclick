// The shell's grid of tiles (Connections' catalog) on a 360px phone, in a real browser: an app's long name runs to a
// second line in place of being cut off, its row grows to hold it and pushes the next one down, and a short name's row
// keeps its height.
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { page } from 'vitest/browser';
import { afterEach, expect, it } from 'vitest';
import { Tile, VirtualTileGrid } from '~/components/shell/Tile';

const APPS = ['Gmail', 'Google AI Studio (Gemini)', 'Slack', 'Notion'];
const mark = <span className="h-10 w-10 shrink-0 rounded-xl bg-foreground/10" />;

let unmount: (() => void) | null = null;
afterEach(() => {
    unmount?.();
    unmount = null;
});

it('lets a long app name wrap to a second line, its row as tall as it needs', async () => {
    await page.viewport(360, 740);
    const host = document.createElement('div');
    host.style.cssText = 'position:fixed;inset:0;overflow-y:auto;padding:0 20px';
    document.body.appendChild(host);
    const root = createRoot(host);
    const grid = (
        <VirtualTileGrid
            items={APPS}
            testId="grid"
            renderTile={(name) => <Tile key={name} mark={mark} title={name} label={name} onOpen={() => undefined} trailing={<button type="button">Connect</button>} />}
        />
    );
    const router = createMemoryRouter([{ path: '/', element: grid }]);
    flushSync(() => root.render(<RouterProvider router={router} />));
    unmount = () => {
        flushSync(() => root.unmount());
        host.remove();
    };

    const tiles = () => [...host.querySelectorAll<HTMLElement>('[role="button"][aria-label]')];
    await expect.poll(() => tiles().length).toBe(APPS.length);
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
    const [short, long, after] = tiles().map((t) => t.getBoundingClientRect());
    const name = [...tiles()[1].querySelectorAll<HTMLElement>('span')].find((s) => s.textContent === APPS[1] && !s.children.length)!;
    const lineHeight = parseFloat(getComputedStyle(name).lineHeight);
    expect(Math.round(name.getBoundingClientRect().height / lineHeight), 'The long name runs to two lines').toBe(2);
    expect(name.scrollHeight, 'and none of it is cut off').toBeLessThanOrEqual(name.clientHeight + 1);
    expect(long.height, 'Its tile grows to hold it').toBeGreaterThan(short.height);
    expect(after.top, 'and pushes the next one down, never under it').toBeGreaterThanOrEqual(long.bottom);
    expect(after.height, 'A short name’s tile keeps its height').toBe(short.height);
}, 30_000);
