// Verifies the add-node button re-focuses the node search field even when the
// FlowHelperView is already open. Regression test for the memo comparator that
// was swallowing searchFocusSignal bumps (so clicking add-node while the panel
// was already open never re-focused the search input).
import { nc } from '~/lib/nc';

const SEARCH_SELECTOR = 'input[placeholder="Search nodes..."]';
const ADD_BTN = '[aria-label="Add a node"]';
const raf = () => new Promise<void>((r) => requestAnimationFrame(() => r()));
const clickAdd = () =>
    document.querySelector<HTMLButtonElement>(ADD_BTN)?.click();

export default async function () {
    // 1. Open the helper view + focus search (closed -> open path).
    clickAdd();
    await nc.wait.forElement(SEARCH_SELECTOR);
    await raf();
    await raf();

    const input = document.querySelector<HTMLInputElement>(SEARCH_SELECTOR);
    nc.assert.truthy(
        input,
        'search input should be present after opening helper'
    );

    // 2. Blur the search input so we can detect a genuine re-focus.
    input!.blur();
    await raf();
    nc.assert.truthy(
        document.activeElement !== input,
        'search input should be blurred before re-triggering'
    );

    // 3. Click add-node again while the helper is ALREADY open. This is the case
    //    the bug broke: the searchFocusSignal bump must now re-focus the input.
    clickAdd();
    await raf();
    await raf();
    const refocused = document.activeElement === input;
    nc.assert.truthy(
        refocused,
        'search input should be re-focused when add-node clicked while helper already open'
    );

    return { refocused };
}
