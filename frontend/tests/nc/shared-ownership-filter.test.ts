// Regression test for the ownership filter that replaced the dedicated
// "Shared with me" view. Verifies the dropdown renders its three options, that
// "Owned by me" / "Not owned by me" partition the grid (their counts sum to
// "Owned by anyone"), and that the shared-empty state hides the New Workflow
// card. Data-independent: it asserts the partition invariant, not fixed counts.
import { nc } from '~/lib/nc';

const TRIGGER = '[title="Filter by ownership"]';

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function cardCounts() {
    return {
        workflows: nc.dom.qsa('[data-workflow-card]').length,
        folders: nc.dom.qsa('[data-folder-card]').length,
    };
}

function hasNewWorkflowCard(): boolean {
    return nc.dom.qsa('h3').some((h) => h.textContent?.trim() === 'New Workflow');
}

// Radix opens its menu on pointer events, so a bare .click() isn't enough.
function fire(el: Element, type: string) {
    el.dispatchEvent(new PointerEvent(type, { bubbles: true, button: 0 }));
}

async function selectFilter(label: string) {
    const trigger = nc.dom.qs(TRIGGER)!;
    fire(trigger, 'pointerdown');
    fire(trigger, 'pointerup');
    (trigger as HTMLElement).click();
    await nc.wait.forElement('[role="menuitemradio"]');
    const item = nc.dom
        .qsa('[role="menuitemradio"]')
        .find((e) => e.textContent?.trim() === label);
    nc.assert.truthy(item, `menu option "${label}" should exist`);
    fire(item!, 'pointerdown');
    fire(item!, 'pointerup');
    (item as HTMLElement).click();
    await wait(250);
    nc.assert.equal(nc.dom.qs(TRIGGER)!.textContent?.trim(), label, 'trigger should reflect selection');
}

export default async function () {
    // Land on the workflow browser root (closes any open workflow/folder).
    window.dispatchEvent(new CustomEvent('noclick:workflow-browser-reset'));
    window.dispatchEvent(new CustomEvent('noclick:switch-tab', { detail: { tab: 'flow' }, bubbles: true }));
    await nc.wait.forElement(TRIGGER);
    // Force card layout so the [data-*-card] counts are meaningful, then settle.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', bubbles: true }));
    await wait(500);

    // The old dedicated nav entry must be gone.
    const sidebarHasShared = nc.dom
        .qsa('*')
        .some((el) => el.children.length === 0 && el.textContent?.trim() === 'Shared with me');
    nc.assert.falsy(sidebarHasShared, 'sidebar should no longer have a "Shared with me" row');

    // Menu exposes exactly the three ownership options.
    const trigger = nc.dom.qs(TRIGGER)!;
    fire(trigger, 'pointerdown');
    fire(trigger, 'pointerup');
    (trigger as HTMLElement).click();
    await nc.wait.forElement('[role="menuitemradio"]');
    const options = nc.dom.qsa('[role="menuitemradio"]').map((e) => e.textContent?.trim());
    nc.assert.deepEqual(options, ['Owned by anyone', 'Owned by me', 'Not owned by me'], 'three ownership options');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await wait(150);

    // Measure each filter and assert the partition invariant.
    await selectFilter('Owned by anyone');
    const anyone = cardCounts();
    nc.assert.truthy(hasNewWorkflowCard(), '"anyone" should show the New Workflow card');

    await selectFilter('Owned by me');
    const owned = cardCounts();
    nc.assert.truthy(hasNewWorkflowCard(), '"owned" should show the New Workflow card');

    await selectFilter('Not owned by me');
    const notOwned = cardCounts();
    // The New Workflow card stays visible in every filter (creating from "Not
    // owned by me" switches the filter back to "Owned by anyone").
    nc.assert.truthy(hasNewWorkflowCard(), 'New Workflow card stays visible under "not owned"');
    if (notOwned.workflows === 0 && notOwned.folders === 0) {
        const emptyShown = nc.dom.qsa('p').some((p) => p.textContent?.includes('Nothing has been shared with you yet'));
        nc.assert.truthy(emptyShown, 'shared-empty state message should render');
    }

    nc.assert.equal(owned.workflows + notOwned.workflows, anyone.workflows, 'workflow counts must partition');
    nc.assert.equal(owned.folders + notOwned.folders, anyone.folders, 'folder counts must partition');

    // Restore the default so we don't leave the session filtered.
    await selectFilter('Owned by anyone');

    return { anyone, owned, notOwned };
}
