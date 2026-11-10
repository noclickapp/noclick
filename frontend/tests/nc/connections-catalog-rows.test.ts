// Connections' All apps grid draws only the rows on screen: a thousand-odd apps once took seconds to draw and
// fetched every app's icon. Verifies the grid stays small, scrolls to its last app, and search still finds an app.
// Run with the nc bridge while signed in on /dashboard.
import { nc } from '~/lib/nc';

const GRID = '[data-testid="app-catalog"]';
const TILE = `${GRID} [role="button"][aria-label]`;

function sidebarLink(name: string): HTMLElement | undefined {
    return [...document.querySelectorAll<HTMLElement>('a, button')].find((el) => (el.textContent ?? '').trim() === name);
}

function scroller(): HTMLElement {
    let node = nc.dom.qs(GRID)?.parentElement ?? null;
    while (node && !/(auto|scroll)/.test(getComputedStyle(node).overflowY)) node = node.parentElement;
    nc.assert.truthy(node, 'The catalog scrolls inside the page');
    return node!;
}

const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

export default async function () {
    sidebarLink('Connections')?.click();
    await nc.wait.forElement(GRID);
    await nc.wait.until(() => nc.dom.qsa(TILE).length > 0);

    const total = Number(nc.dom.qs('[role="tab"][aria-selected="true"]')?.textContent?.replace(/\D/g, '') ?? 0);
    nc.assert.gt(total, 200, 'All apps counts the whole catalog');
    const drawn = nc.dom.qsa(TILE).length;
    nc.assert.equal(drawn < 150, true, `Only the rows near the screen are drawn (${drawn} of ${total})`);

    // The grid is as tall as every row, so the page scrolls to the last app.
    const page = scroller();
    page.scrollTop = page.scrollHeight;
    await frame();
    // The last row is drawn where the grid ends.
    await nc.wait.until(() => {
        const tiles = nc.dom.qsa(TILE);
        const gridBottom = nc.dom.qs(GRID)!.getBoundingClientRect().bottom;
        return tiles.length > 0 && gridBottom - tiles[tiles.length - 1].getBoundingClientRect().bottom < 40;
    }, 3000);
    nc.assert.equal(nc.dom.qsa(TILE).length < 150, true, 'Scrolled to the end, the grid still draws only what is near');

    page.scrollTop = 0;
    nc.dom.type('input[placeholder="Search apps"]', 'slack');
    await nc.wait.until(() => /Slack/.test(nc.dom.qsa(TILE)[0]?.getAttribute('aria-label') ?? ''), 3000);
    nc.dom.type('input[placeholder="Search apps"]', '');
}
