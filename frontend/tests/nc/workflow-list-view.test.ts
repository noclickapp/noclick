// Verifies the WorkflowBrowser grid/list layout toggle: the header control
// switches between the card grid and the compact list, aria-pressed tracks the
// active layout, the list view shows a search bar, and the primary "New
// automation" button lives in the header. Data-independent so it stays reliable
// on an empty workspace.
import { nc } from '~/lib/nc';

const GRID_BTN = '[aria-label="Card view"]';
const LIST_BTN = '[aria-label="List view"]';
const GRID = '[data-testid="automations-grid"]';
const SEARCH = 'input[placeholder="Search automations and folders"]';
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

const pressed = (sel: string) =>
    document.querySelector(sel)?.getAttribute('aria-pressed') === 'true';
const primaryNewButton = () =>
    Array.from(document.querySelectorAll('button')).some(
        (b) =>
            b.textContent?.trim() === 'New automation' &&
            b.className.includes('bg-primary')
    );
// The grid holds cards, or says there are none — never a bare void.
const gridHasContent = () =>
    !!document.querySelector(`${GRID} [data-workflow-card], ${GRID} [data-folder-card]`) ||
    !!document.querySelector(GRID)?.textContent?.includes('No automations yet');

export default async function () {
    await nc.wait.forElement(GRID_BTN);

    // Header CTA is present regardless of layout
    nc.assert.truthy(
        primaryNewButton(),
        'primary New automation button should be in the header'
    );

    // Grid layout
    document.querySelector<HTMLButtonElement>(GRID_BTN)!.click();
    await sleep(150);
    nc.assert.truthy(pressed(GRID_BTN), 'grid toggle should be pressed');
    nc.assert.truthy(!!document.querySelector(GRID), 'grid container should render in grid mode');
    nc.assert.truthy(gridHasContent(), 'grid shows cards or the empty state');

    // List layout
    document.querySelector<HTMLButtonElement>(LIST_BTN)!.click();
    await sleep(150);
    nc.assert.truthy(pressed(LIST_BTN), 'list toggle should be pressed');
    nc.assert.truthy(
        !document.querySelector(GRID),
        'grid container should NOT render in list mode'
    );
    nc.assert.truthy(
        !!document.querySelector(SEARCH),
        'search bar should render in list mode'
    );

    return { gridOk: true, listOk: true, headerCtaOk: true };
}
