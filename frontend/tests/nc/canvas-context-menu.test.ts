// Smoke test for the right-click context menus on the workflow canvas.
// Verifies that contextmenu on the pane renders the canvas-menu items, and
// contextmenu on a node renders the node-menu items (with sticky-note-only
// items hidden for non-sticky nodes — we test against a regular node).

import { nc } from '~/lib/nc';

const MENU = '[role="menu"]';
const ITEM = (label: string) => `[role="menuitem"]`;

function menuLabels(): string[] {
    return Array.from(document.querySelectorAll(`${MENU} [role="menuitem"]`)).map(
        (el) => el.textContent?.replace(/[⌘⌫A-Z\s]+$/, '').trim() ?? ''
    );
}

function dispatchContextMenu(target: Element, x: number, y: number) {
    const ev = new MouseEvent('contextmenu', {
        bubbles: true,
        cancelable: true,
        clientX: x,
        clientY: y,
        button: 2,
    });
    target.dispatchEvent(ev);
}

function closeOpenMenu() {
    if (!document.querySelector(MENU)) return;
    // Click outside the menu — context menu's click-outside is on pointerdown
    document.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
}

export default async function () {
    closeOpenMenu();

    // ── Pane (canvas) right-click ────────────────────────────────────────
    const pane = document.querySelector('.react-flow__pane');
    nc.assert.truthy(pane, 'react-flow pane is present');

    const paneRect = (pane as Element).getBoundingClientRect();
    dispatchContextMenu(pane!, paneRect.left + 200, paneRect.top + 200);

    await nc.wait.forElement(MENU);
    const paneItems = menuLabels();
    nc.assert.gt(paneItems.length, 4, `Pane menu should have items (got ${paneItems.length})`);
    for (const expected of ['Add node', 'Add sticky note', 'Paste', 'Select all', 'Auto-layout', 'Fit view']) {
        nc.assert.truthy(
            paneItems.some((l) => l.includes(expected)),
            `Pane menu should include "${expected}" (got ${JSON.stringify(paneItems)})`
        );
    }
    closeOpenMenu();
    await nc.wait.forElementGone?.(MENU);
    // Fallback wait — some test harnesses don't implement forElementGone
    if (document.querySelector(MENU)) {
        await new Promise((r) => setTimeout(r, 50));
    }

    // ── Node right-click ─────────────────────────────────────────────────
    const node = document.querySelector('.react-flow__node:not(.react-flow__node-stickyNote)');
    nc.assert.truthy(node, 'a non-sticky node is present on canvas');
    const nodeRect = (node as Element).getBoundingClientRect();
    dispatchContextMenu(node!, nodeRect.left + 10, nodeRect.top + 10);

    await nc.wait.forElement(MENU);
    const nodeItems = menuLabels();
    nc.assert.gt(nodeItems.length, 4, `Node menu should have items (got ${nodeItems.length})`);
    for (const expected of ['Open', 'Run from this node', 'Duplicate', 'Copy', 'Cut', 'Rename', 'Delete']) {
        nc.assert.truthy(
            nodeItems.some((l) => l.includes(expected)),
            `Node menu should include "${expected}" (got ${JSON.stringify(nodeItems)})`
        );
    }
    // Disable/Enable toggles based on current node state, so accept either form.
    nc.assert.truthy(
        nodeItems.some((l) => l.includes('Disable') || l.includes('Enable')),
        `Node menu should include Disable/Enable (got ${JSON.stringify(nodeItems)})`
    );
    closeOpenMenu();

    return { paneItems, nodeItems };
}
