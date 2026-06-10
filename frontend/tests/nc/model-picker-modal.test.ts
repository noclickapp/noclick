// Verifies the centered ModelPickerModal on the FlowCanvas agent node: trigger
// opens a screen-centered dialog with the filter rail expanded, search filters
// the list, ↑↓/↵ keyboard navigation works, Esc closes, and selecting a model
// writes node config. Restores the original model at the end.
import { nc } from '~/lib/nc';

const TRIGGER = '[data-testid="agent-node-model-trigger"]';
const MODAL = '[data-testid="model-picker-modal"]';
const SEARCH = '[data-testid="model-picker-search"]';
const ROW = `${MODAL} [role="option"]`;
// Model short name lives in the row's `.truncate` span — the provider icon
// also contributes hidden text to the row's textContent, so never compare
// against the whole row.
const ROW_NAME = `${ROW} .truncate`;
const HIGHLIGHT_CLASS = 'bg-zinc-700/50';

function agentNode() {
    const agents = nc.nodes.summary().filter((n) => n.type === 'agent');
    nc.assert.gt(agents.length, 0, 'Canvas should have an agent node');
    return agents[0].id;
}

function highlightedRowText(): string {
    const row = nc.dom
        .qsa(ROW)
        .find((el) => (el as HTMLElement).classList.contains(HIGHLIGHT_CLASS));
    return row?.querySelector('.truncate')?.textContent?.trim() ?? '';
}

async function openModal() {
    nc.assert.equal(nc.dom.click(TRIGGER), true, 'Trigger button should exist');
    await nc.wait.forElement(MODAL);
    await nc.wait.until(() => document.activeElement === nc.dom.qs(SEARCH));
}

export default async function () {
    const agentId = agentNode();
    const originalModel = nc.node(agentId)?.config?.model as string;
    nc.assert.equal(typeof originalModel, 'string', 'Agent should have a model');

    // 1. Open: centered dialog with search focused and filter rail expanded.
    await openModal();
    const dialog = nc.dom.qs(MODAL)!.closest('[role="dialog"]') as HTMLElement;
    nc.assert.equal(!!dialog, true, 'Modal should render inside a dialog');
    const rect = dialog.getBoundingClientRect();
    const centerDelta = Math.abs(rect.left + rect.width / 2 - window.innerWidth / 2);
    nc.assert.equal(centerDelta < 2, true, `Dialog should be horizontally centered (delta ${centerDelta})`);
    const featureFilters = nc.dom.getTexts(`${MODAL} button`).filter((t) =>
        ['Image Analysis', 'Reasoning', 'Tool Support'].includes(t),
    );
    nc.assert.gt(featureFilters.length, 2, 'Feature filters should be visible without opening anything');
    await nc.wait.until(() => nc.dom.qsa(ROW).length > 0);

    // 2. Search filters the list.
    nc.dom.type(SEARCH, 'claude');
    await nc.wait.until(() => {
        const rows = nc.dom.getTexts(ROW_NAME);
        return rows.length > 0 && rows[0].toLowerCase().includes('claude');
    }, 3000);

    // 3. Keyboard navigation: ↓↓↑ moves the highlight.
    const first = highlightedRowText();
    nc.dom.pressKey(SEARCH, 'ArrowDown');
    await nc.wait.until(() => highlightedRowText() !== first);
    const second = highlightedRowText();
    nc.dom.pressKey(SEARCH, 'ArrowDown');
    await nc.wait.until(() => highlightedRowText() !== second);
    nc.dom.pressKey(SEARCH, 'ArrowUp');
    await nc.wait.until(() => highlightedRowText() === second);

    // 4. Enter selects the highlighted model, closes the modal, writes config.
    const toSelect = highlightedRowText();
    nc.dom.pressKey(SEARCH, 'Enter');
    await nc.wait.until(() => !nc.dom.qs(MODAL));
    await nc.wait.until(
        () => (nc.node(agentId)?.config?.model as string).split('/').pop() === toSelect,
    );

    // 5. Esc closes without selecting.
    await openModal();
    nc.dom.pressKey(SEARCH, 'Escape');
    await nc.wait.until(() => !nc.dom.qs(MODAL));
    const afterEsc = nc.node(agentId)?.config?.model as string;
    nc.assert.equal(afterEsc.split('/').pop(), toSelect, 'Esc should not change the model');

    // 6. Restore the original model through the picker itself — click the row
    // with the exact short name (a full-id search can also match variants like
    // "<id>-fast", which may sort first).
    await openModal();
    nc.dom.type(SEARCH, originalModel);
    const originalShortName = originalModel.split('/').pop();
    await nc.wait.until(() => nc.dom.getTexts(ROW_NAME).includes(originalShortName!));
    const originalRow = nc.dom
        .qsa(ROW)
        .find((el) => el.querySelector('.truncate')?.textContent?.trim() === originalShortName);
    nc.dom.click(originalRow!);
    await nc.wait.until(() => nc.node(agentId)?.config?.model === originalModel);

    return {
        agentId,
        originalModel,
        keyboardSelected: toSelect,
        restored: nc.node(agentId)?.config?.model === originalModel,
    };
}
