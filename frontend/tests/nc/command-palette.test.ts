// Regression test for the global command palette. Verifies it opens on ⌘K from
// any dashboard screen, renders the command sections, filters as you type, and
// supports keyboard navigation + the keyboard-shortcuts sub-page. Run with the
// nc bridge while authenticated on /dashboard.
import { nc } from '~/lib/nc';

const PALETTE = '[data-testid="command-palette"]';

function pressMetaK() {
    // ⌘K (and Ctrl+K) — the global open/toggle shortcut.
    window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true })
    );
}

function pressKey(key: string) {
    const input = document.querySelector<HTMLInputElement>(`${PALETTE} input`);
    const target = input ?? document.querySelector(PALETTE);
    target?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
}

export default async function () {
    // ── Opens on ⌘K ────────────────────────────────────────────────────────
    pressMetaK();
    await nc.wait.forElement(PALETTE);
    nc.assert.truthy(
        document.querySelector(PALETTE),
        'Palette should open on ⌘K'
    );

    const input = document.querySelector<HTMLInputElement>(`${PALETTE} input`);
    nc.assert.truthy(input, 'Palette has a search input');

    // ── Default view shows command sections ────────────────────────────────
    const headers = Array.from(
        document.querySelectorAll(`${PALETTE} .uppercase`)
    ).map((el) => el.textContent?.trim());
    nc.assert.truthy(
        headers.includes('Navigation') &&
            headers.includes('Actions') &&
            headers.includes('Account'),
        `Expected Navigation/Actions/Account sections, got: ${headers.join(', ')}`
    );

    const defaultRows = document.querySelectorAll(
        `${PALETTE} [data-cmd-index]`
    ).length;
    nc.assert.gt(defaultRows, 0, 'Default view renders command rows');

    // ── Keyboard nav wraps at both ends ────────────────────────────────────
    const activeIdx = () =>
        Array.from(
            document.querySelectorAll<HTMLElement>(`${PALETTE} [data-cmd-index]`)
        ).findIndex((r) => r.className.includes('bg-white/[0.08]'));
    pressKey('ArrowUp');
    await nc.wait.until(() => activeIdx() === defaultRows - 1, 2000);
    nc.assert.equal(
        activeIdx(),
        defaultRows - 1,
        'ArrowUp on the first row wraps to the last'
    );
    pressKey('ArrowDown');
    await nc.wait.until(() => activeIdx() === 0, 2000);
    nc.assert.equal(activeIdx(), 0, 'ArrowDown on the last row wraps to the first');

    // ── Typing filters the list ────────────────────────────────────────────
    nc.dom.type(`${PALETTE} input`, 'billing');
    await nc.wait.ms(150);
    const billingText = document.querySelector(PALETTE)?.textContent ?? '';
    nc.assert.truthy(
        !/Upgrade \/ add credits/i.test(billingText),
        'The community palette has no managed purchase command'
    );

    nc.dom.type(`${PALETTE} input`, 'workflow');
    await nc.wait.ms(150);
    // First result should be highlighted (index 0).
    const firstRow = document.querySelector(`${PALETTE} [data-cmd-index="0"]`);
    nc.assert.truthy(firstRow, 'There is a highlighted first result');

    // ── Cross-section ranking: the strongest match wins regardless of which
    // section it lives in. "chat"/"ai"/"copilot" must surface the Account-section
    // "Toggle chat sidebar" as the top row, not a weaker subsequence match in an
    // earlier section (regression for "chat" → "Create new credential…").
    for (const q of ['chat', 'ai', 'copilot']) {
        nc.dom.type(`${PALETTE} input`, q);
        await nc.wait.ms(150);
        const top = document
            .querySelector(`${PALETTE} [data-cmd-index="0"]`)
            ?.textContent?.trim();
        nc.assert.truthy(
            /Toggle chat sidebar/i.test(top ?? ''),
            `Query "${q}" should rank "Toggle chat sidebar" first, got: ${top}`
        );
    }

    // ── No-results state ───────────────────────────────────────────────────
    nc.dom.type(`${PALETTE} input`, 'zzzqqqnomatch');
    await nc.wait.ms(150);
    nc.assert.truthy(
        /No results/i.test(document.querySelector(PALETTE)?.textContent ?? ''),
        'Unmatched query shows the no-results state'
    );

    // ── Keyboard-shortcuts sub-page ────────────────────────────────────────
    nc.dom.type(`${PALETTE} input`, 'keyboard');
    await nc.wait.ms(150);
    const shortcutsRow = document.querySelector<HTMLElement>(
        `${PALETTE} [data-cmd-index="0"]`
    );
    nc.assert.truthy(shortcutsRow, 'Keyboard shortcuts command is present');
    shortcutsRow?.click();
    await nc.wait.ms(150);
    nc.assert.truthy(
        /Open command palette/i.test(
            document.querySelector(PALETTE)?.textContent ?? ''
        ),
        'Shortcuts sub-page lists shortcuts'
    );

    // The Back button returns to the root search view (palette stays open).
    // Root and the shortcuts sub-page both have a search input now, so they're
    // told apart by placeholder.
    const placeholder = () =>
        document
            .querySelector<HTMLInputElement>(`${PALETTE} input`)
            ?.getAttribute('placeholder') ?? '';
    const backBtn = document.querySelector<HTMLElement>(
        `${PALETTE} [data-testid="command-palette-back"]`
    );
    nc.assert.truthy(backBtn, 'Shortcuts sub-page has a Back button');
    backBtn?.click();
    await nc.wait.ms(120);
    nc.assert.truthy(
        document.querySelector(PALETTE),
        'Back keeps the palette open'
    );
    nc.assert.truthy(
        /workflows, settings/i.test(placeholder()),
        'Back returns to the root search view'
    );

    // ── Escape closes the palette ──────────────────────────────────────────
    pressKey('Escape');
    await nc.wait.ms(150);
    nc.assert.truthy(
        !document.querySelector(PALETTE),
        'Escape closes the palette'
    );

    // ── ⌘/ opens straight to the searchable keyboard-shortcuts panel ───────
    window.dispatchEvent(
        new KeyboardEvent('keydown', { key: '/', metaKey: true, bubbles: true })
    );
    await nc.wait.forElement(PALETTE);
    const openedToShortcuts =
        !!document.querySelector(
            `${PALETTE} [data-testid="command-palette-back"]`
        ) && /shortcuts/i.test(placeholder());
    nc.assert.truthy(
        openedToShortcuts,
        '⌘/ opens directly to the keyboard-shortcuts panel'
    );
    // The panel lists the Go to / Open groups and is searchable.
    const panelText = () => document.querySelector(PALETTE)?.textContent ?? '';
    nc.assert.truthy(
        /Go to/i.test(panelText()) && /Open/i.test(panelText()),
        'Shortcuts panel shows the Go to / Open groups'
    );
    nc.dom.type(`${PALETTE} input`, 'usage');
    await nc.wait.ms(150);
    nc.assert.truthy(
        /Usage/i.test(panelText()) && !/Open chat sidebar/i.test(panelText()),
        'Searching shortcuts filters the list'
    );
    pressKey('Escape');
    await nc.wait.ms(120);

    return { ok: true, defaultRows, sections: headers, openedToShortcuts };
}
