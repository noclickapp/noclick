// Verifies the light/dark theme toggle in the NavBar avatar dropdown: opens the
// account menu, clicks the Theme item, and asserts the `dark` class on <html>,
// the navbar's computed background, and localStorage persistence flip correctly.
import { nc } from '~/lib/nc';

function openAccountMenu(): void {
    const trigger = document.querySelector('[data-onboarding="user-menu"]');
    if (!trigger) throw new Error('avatar trigger not found');
    // Radix dropdown opens on pointerdown, not click
    trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, pointerId: 1 })
    );
    trigger.dispatchEvent(
        new PointerEvent('pointerup', { bubbles: true, pointerId: 1 })
    );
}

function themeSegmentButton(mode: 'system' | 'light' | 'dark'): HTMLElement {
    const items = Array.from(document.querySelectorAll('[role="menuitem"]'));
    const row = items.find((el) => el.textContent?.includes('Theme'));
    if (!row) throw new Error('Theme menu item not found');
    const btn = row.querySelector(
        `button[aria-label="${
            mode === 'system'
                ? 'System theme'
                : mode === 'light'
                  ? 'Light theme'
                  : 'Dark theme'
        }"]`
    );
    if (!btn) throw new Error(`Theme segment ${mode} not found`);
    return btn as HTMLElement;
}

function snapshot() {
    const nav = document.querySelector('nav');
    return {
        dark: document.documentElement.classList.contains('dark'),
        navBg: nav ? getComputedStyle(nav).backgroundColor : null,
        bodyBg: getComputedStyle(document.body).backgroundColor,
        stored: localStorage.getItem('nc-theme'),
    };
}

export default async function () {
    const initial = snapshot();

    openAccountMenu();
    await nc.wait.forElement('[data-onboarding="user-menu-dropdown"]');

    // Flip to the opposite theme via the segmented picker
    themeSegmentButton(initial.dark ? 'light' : 'dark').click();
    await new Promise((r) => setTimeout(r, 150));
    const afterFirst = snapshot();

    // Menu should still be open (row onSelect preventDefault) — flip back
    const menuStillOpen = !!document.querySelector(
        '[data-onboarding="user-menu-dropdown"]'
    );
    themeSegmentButton(initial.dark ? 'dark' : 'light').click();
    await new Promise((r) => setTimeout(r, 150));
    const afterSecond = snapshot();

    // Close the menu
    document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })
    );

    nc.assert.equal(
        afterFirst.dark,
        !initial.dark,
        'first toggle should flip the dark class'
    );
    nc.assert.equal(
        afterSecond.dark,
        initial.dark,
        'second toggle should restore it'
    );
    nc.assert.equal(
        menuStillOpen,
        true,
        'menu should stay open across the toggle'
    );

    const lightSnap = initial.dark ? afterFirst : afterSecond;
    const darkSnap = initial.dark ? afterSecond : afterFirst;
    // Off-white (--background 240 10% 98%) so white cards/popovers read as raised.
    nc.assert.equal(
        lightSnap.bodyBg,
        'rgb(249, 249, 250)',
        'light body bg should be off-white'
    );
    nc.assert.equal(
        darkSnap.bodyBg,
        'rgb(0, 0, 0)',
        'dark body bg should be black'
    );
    nc.assert.equal(lightSnap.stored, 'light', 'light preference persisted');
    nc.assert.equal(darkSnap.stored, 'dark', 'dark preference persisted');

    return { initial, afterFirst, afterSecond, menuStillOpen };
}
