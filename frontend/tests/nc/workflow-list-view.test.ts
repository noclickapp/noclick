// Verifies the WorkflowBrowser grid/list layout toggle: the header control
// switches between the card grid and the compact list, aria-pressed tracks the
// active layout, the list view shows a search bar, and a white "New Workflow"
// button lives in the header. Data-independent so it stays reliable on an empty
// workspace.
import { nc } from '~/lib/nc';

const GRID_BTN = '[aria-label="Grid view"]';
const LIST_BTN = '[aria-label="List view"]';
const SEARCH = 'input[placeholder="Search workflows and folders..."]';
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

const pressed = (sel: string) =>
    document.querySelector(sel)?.getAttribute('aria-pressed') === 'true';
const hasGridContainer = () => !!document.querySelector('.grid.grid-cols-1');
const newWorkflowCard = () =>
    Array.from(document.querySelectorAll('h3')).some(
        (h) => h.textContent === 'New Workflow'
    );
const whiteNewWorkflowButton = () =>
    Array.from(document.querySelectorAll('button')).some(
        (b) =>
            b.textContent?.trim() === 'New Workflow' &&
            b.className.includes('bg-white')
    );

export default async function () {
    await nc.wait.forElement(GRID_BTN);

    // Header CTA is present regardless of layout
    nc.assert.truthy(
        whiteNewWorkflowButton(),
        'white New Workflow button should be in the header'
    );

    // Grid layout
    document.querySelector<HTMLButtonElement>(GRID_BTN)!.click();
    await sleep(150);
    nc.assert.truthy(pressed(GRID_BTN), 'grid toggle should be pressed');
    nc.assert.truthy(
        hasGridContainer(),
        'grid container should render in grid mode'
    );
    nc.assert.truthy(
        newWorkflowCard(),
        'New Workflow card should render in grid mode'
    );

    // List layout
    document.querySelector<HTMLButtonElement>(LIST_BTN)!.click();
    await sleep(150);
    nc.assert.truthy(pressed(LIST_BTN), 'list toggle should be pressed');
    nc.assert.truthy(
        !hasGridContainer(),
        'grid container should NOT render in list mode'
    );
    nc.assert.truthy(
        !!document.querySelector(SEARCH),
        'search bar should render in list mode'
    );

    return { gridOk: true, listOk: true, headerCtaOk: true };
}
